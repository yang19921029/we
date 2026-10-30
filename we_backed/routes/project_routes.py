"""Organization, project, and dataset API routes."""

import app as app_module

from datetime import datetime
from datetime import timezone
from elasticsearch.exceptions import ApiError
from elasticsearch.exceptions import TransportError
from flask import current_app
from flask import jsonify
from flask import request
from flask import session
from pymysql.err import IntegrityError
import csv
import io
import json
import uuid

from app import (
    can_access_dataset,
    elastic_error_response,
    is_global_project_admin,
    login_required,
    role_required,
    user_can_access_project,
    write_audit_log,
)


def register_project_routes(app):
    @app.get("/api/organizations")
    @login_required
    def list_organizations():
        with app_module.get_db().cursor() as cursor:
            if is_global_project_admin():
                cursor.execute(
                    "SELECT id, name, description FROM organizations ORDER BY id"
                )
            else:
                cursor.execute(
                    """
                    SELECT DISTINCT o.id, o.name, o.description
                    FROM organizations o
                    JOIN projects p ON p.organization_id = o.id
                    JOIN project_members pm ON pm.project_id = p.id
                    WHERE pm.user_id = %s
                    ORDER BY o.id
                    """,
                    (session["user_id"],),
                )
            organizations = cursor.fetchall()
        return jsonify(
            code=0,
            message="ok",
            data=[dict(organization) for organization in organizations],
        )

    @app.post("/api/organizations")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def create_organization():
        payload = request.get_json(silent=True)
        name = payload.get("name") if isinstance(payload, dict) else None
        description = payload.get("description", "") if isinstance(payload, dict) else None
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 191:
            return jsonify(code=400, message="组织名称不能为空且不能超过 191 个字符。", data=None), 400
        if not isinstance(description, str) or len(description) > 2000:
            return jsonify(code=400, message="组织说明不能超过 2000 个字符。", data=None), 400
        db = app_module.get_db()
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO organizations (name, description, created_by)
                    VALUES (%s, %s, %s)
                    """,
                    (name.strip(), description.strip(), session["username"]),
                )
                organization_id = cursor.lastrowid
                cursor.execute(
                    "SELECT id, name, description FROM organizations WHERE id = %s",
                    (organization_id,),
                )
                organization = dict(cursor.fetchone())
            write_audit_log("创建", "组织", organization_id, {"name": name.strip()})
            db.commit()
        except IntegrityError:
            return jsonify(code=409, message="组织名称已存在。", data=None), 409
        return jsonify(code=0, message="组织已创建。", data=organization), 201

    @app.get("/api/projects")
    @login_required
    def list_projects():
        with app_module.get_db().cursor() as cursor:
            if is_global_project_admin():
                cursor.execute(
                    """
                    SELECT p.id, p.name, p.description, p.organization_id,
                        o.name AS organization_name
                    FROM projects p
                    JOIN organizations o ON o.id = p.organization_id
                    ORDER BY p.id
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT p.id, p.name, p.description, p.organization_id,
                        o.name AS organization_name
                    FROM projects p
                    JOIN organizations o ON o.id = p.organization_id
                    JOIN project_members pm ON pm.project_id = p.id
                    WHERE pm.user_id = %s
                    ORDER BY p.id
                    """,
                    (session["user_id"],),
                )
            projects = cursor.fetchall()
        return jsonify(
            code=0,
            message="ok",
            data=[dict(project) for project in projects],
        )

    @app.post("/api/projects")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def create_project():
        payload = request.get_json(silent=True)
        name = payload.get("name") if isinstance(payload, dict) else None
        description = payload.get("description", "") if isinstance(payload, dict) else None
        organization_id = payload.get("organization_id", 1) if isinstance(payload, dict) else None
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 191:
            return jsonify(code=400, message="项目名称不能为空且不能超过 191 个字符。", data=None), 400
        if not isinstance(description, str) or len(description) > 2000:
            return jsonify(code=400, message="项目说明不能超过 2000 个字符。", data=None), 400
        if not isinstance(organization_id, int) or isinstance(organization_id, bool) or organization_id < 1:
            return jsonify(code=400, message="组织编号无效。", data=None), 400
        db = app_module.get_db()
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT id FROM organizations WHERE id = %s", (organization_id,))
                if cursor.fetchone() is None:
                    return jsonify(code=404, message="组织不存在。", data=None), 404
                cursor.execute(
                    """
                    INSERT INTO projects
                        (organization_id, name, description, created_by)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (organization_id, name.strip(), description.strip(), session["username"]),
                )
                project_id = cursor.lastrowid
                cursor.execute(
                    """
                    SELECT p.id, p.name, p.description, p.organization_id,
                        o.name AS organization_name
                    FROM projects p JOIN organizations o ON o.id = p.organization_id
                    WHERE p.id = %s
                    """,
                    (project_id,),
                )
                project = dict(cursor.fetchone())
            write_audit_log("创建", "项目", project_id, {"name": name.strip()})
            db.commit()
        except IntegrityError:
            return jsonify(code=409, message="该组织下已存在同名项目。", data=None), 409
        return jsonify(code=0, message="项目已创建。", data=project), 201

    @app.get("/api/projects/<int:project_id>/members")
    @login_required
    def list_project_members(project_id: int):
        if not user_can_access_project(project_id):
            return jsonify(code=403, message="无权访问该项目。", data=None), 403
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id, u.username, u.role, pm.created_at, adder.username AS added_by
                FROM project_members pm
                JOIN users u ON u.id = pm.user_id
                JOIN users adder ON adder.id = pm.added_by
                WHERE pm.project_id = %s
                ORDER BY u.username
                """,
                (project_id,),
            )
            members = cursor.fetchall()
        return jsonify(
            code=0,
            message="ok",
            data=[dict(member) for member in members],
        )

    @app.post("/api/projects/<int:project_id>/members")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def add_project_member(project_id: int):
        payload = request.get_json(silent=True)
        user_id = payload.get("user_id") if isinstance(payload, dict) else None
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1:
            return jsonify(code=400, message="用户编号无效。", data=None), 400
        db = app_module.get_db()
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
                if cursor.fetchone() is None:
                    return jsonify(code=404, message="项目不存在。", data=None), 404
                cursor.execute("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
                user = cursor.fetchone()
                if user is None:
                    return jsonify(code=404, message="用户不存在。", data=None), 404
                cursor.execute(
                    """
                    INSERT INTO project_members (project_id, user_id, added_by)
                    VALUES (%s, %s, %s)
                    """,
                    (project_id, user_id, session["user_id"]),
                )
            write_audit_log(
                "添加项目成员",
                "项目",
                project_id,
                {"user_id": user_id, "username": user["username"]},
            )
            db.commit()
        except IntegrityError:
            return jsonify(code=409, message="该用户已是项目成员。", data=None), 409
        return jsonify(code=0, message="项目成员已添加。", data=dict(user)), 201

    @app.delete("/api/projects/<int:project_id>/members/<int:user_id>")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def remove_project_member(project_id: int, user_id: int):
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if cursor.fetchone() is None:
                return jsonify(code=404, message="项目不存在。", data=None), 404
            cursor.execute(
                "SELECT username FROM users WHERE id = %s",
                (user_id,),
            )
            user = cursor.fetchone()
            if user is None:
                return jsonify(code=404, message="用户不存在。", data=None), 404
            cursor.execute(
                "DELETE FROM project_members WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            if cursor.rowcount == 0:
                return jsonify(code=404, message="项目成员不存在。", data=None), 404
        write_audit_log(
            "移除项目成员",
            "项目",
            project_id,
            {"user_id": user_id, "username": user["username"]},
        )
        db.commit()
        return jsonify(code=0, message="项目成员已移除。", data={"user_id": user_id})

    @app.get("/api/datasets")
    @login_required
    def list_datasets():
        with app_module.get_db().cursor() as cursor:
            if is_global_project_admin():
                cursor.execute(
                    """
                    SELECT d.id, d.name, d.description, d.record_count, d.created_by,
                        d.created_at, d.project_id, p.name AS project_name
                    FROM datasets d JOIN projects p ON p.id = d.project_id
                    ORDER BY d.id
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT d.id, d.name, d.description, d.record_count, d.created_by,
                        d.created_at, d.project_id, p.name AS project_name
                    FROM datasets d
                    JOIN projects p ON p.id = d.project_id
                    JOIN project_members pm ON pm.project_id = d.project_id
                    WHERE pm.user_id = %s
                    ORDER BY d.id
                    """,
                    (session["user_id"],),
                )
            rows = cursor.fetchall()
        return jsonify(code=0, message="ok", data=[dict(row) for row in rows])

    @app.post("/api/datasets")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人")
    def create_dataset():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        name = payload.get("name")
        description = payload.get("description", "")
        project_id = payload.get("project_id", 1)
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 191:
            return jsonify(code=400, message="数据集名称不能为空且不能超过 191 个字符。", data=None), 400
        if not isinstance(description, str) or len(description) > 2000:
            return jsonify(code=400, message="数据集说明不能超过 2000 个字符。", data=None), 400
        if not isinstance(project_id, int) or isinstance(project_id, bool) or project_id < 1:
            return jsonify(code=400, message="项目编号无效。", data=None), 400

        db = app_module.get_db()
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
                if cursor.fetchone() is None:
                    return jsonify(code=404, message="项目不存在。", data=None), 404
                if not user_can_access_project(project_id):
                    return jsonify(code=403, message="无权在该项目创建数据集。", data=None), 403
                cursor.execute(
                    """
                    INSERT INTO datasets
                        (name, description, created_by, project_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (name.strip(), description.strip(), session["username"], project_id),
                )
                dataset_id = cursor.lastrowid
                cursor.execute(
                    """
                    SELECT d.id, d.name, d.description, d.record_count, d.created_by,
                        d.created_at, d.project_id, p.name AS project_name
                    FROM datasets d JOIN projects p ON p.id = d.project_id
                    WHERE d.id = %s
                    """,
                    (dataset_id,),
                )
                row = cursor.fetchone()
            write_audit_log("创建", "数据集", dataset_id, {"name": name.strip()})
            db.commit()
        except IntegrityError:
            return jsonify(code=409, message="该项目下已存在同名数据集。", data=None), 409
        return jsonify(code=0, message="数据集已创建。", data=dict(row)), 201

    @app.post("/api/datasets/<int:dataset_id>/import")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人")
    def import_dataset_records(dataset_id: int):
        if not can_access_dataset(dataset_id):
            return jsonify(code=403, message="无权访问该数据集。", data=None), 403
        uploaded_file = request.files.get("file")
        if uploaded_file is None or not uploaded_file.filename:
            return jsonify(code=400, message="请选择要导入的文件。", data=None), 400
        filename = uploaded_file.filename.lower()
        try:
            text = uploaded_file.read(10 * 1024 * 1024 + 1).decode("utf-8-sig")
        except UnicodeDecodeError:
            return jsonify(code=400, message="文件必须使用 UTF-8 编码。", data=None), 400
        if len(text.encode("utf-8")) > 10 * 1024 * 1024:
            return jsonify(code=413, message="单个导入文件不能超过 10 MB。", data=None), 413
        try:
            if filename.endswith(".csv"):
                records = list(csv.DictReader(io.StringIO(text)))
            elif filename.endswith((".jsonl", ".ndjson")):
                records = [
                    json.loads(line)
                    for line in text.splitlines()
                    if line.strip()
                ]
            elif filename.endswith(".json"):
                parsed = json.loads(text)
                records = parsed if isinstance(parsed, list) else parsed.get("items", [parsed])
            else:
                return jsonify(
                    code=400,
                    message="仅支持 CSV、JSON、JSONL 文件。",
                    data=None,
                ), 400
        except (json.JSONDecodeError, csv.Error, AttributeError) as error:
            return jsonify(code=400, message=f"文件格式错误：{error}", data=None), 400
        if (
            not isinstance(records, list)
            or not records
            or len(records) > 5000
            or any(not isinstance(record, dict) for record in records)
        ):
            return jsonify(
                code=400,
                message="文件必须包含 1 到 5000 条 JSON 对象记录。",
                data=None,
            ), 400

        with app_module.get_db().cursor() as cursor:
            cursor.execute("SELECT id FROM datasets WHERE id = %s", (dataset_id,))
            dataset = cursor.fetchone()
        if dataset is None:
            return jsonify(code=404, message="数据集不存在。", data=None), 404

        indexed = 0
        skipped_duplicates = 0
        imported_ids = set()
        try:
            client = app_module.get_es_client()
            for record in records:
                external_id = record.get("_id", record.get("source_id"))
                item_id = (
                    f"ds-{dataset_id}-{external_id}"
                    if isinstance(external_id, (str, int))
                    and str(external_id).strip()
                    and len(str(external_id)) <= 200
                    else uuid.uuid4().hex
                )
                if item_id in imported_ids:
                    skipped_duplicates += 1
                    continue
                imported_ids.add(item_id)
                document = dict(record)
                document.pop("_id", None)
                document["dataset_id"] = dataset_id
                document.setdefault(
                    "inserted_at", datetime.now(timezone.utc).isoformat()
                )
                client.index(
                    index=current_app.config["ELASTICSEARCH_INDEX"],
                    id=item_id,
                    document=document,
                    refresh="wait_for",
                )
                indexed += 1
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)

        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE datasets SET record_count = record_count + %s WHERE id = %s",
                (indexed, dataset_id),
            )
        write_audit_log(
            "导入数据",
            "数据集",
            dataset_id,
            {"imported_count": indexed, "skipped_duplicate_count": skipped_duplicates},
        )
        db.commit()
        return jsonify(
            code=0,
            message="数据导入完成。",
            data={
                "dataset_id": dataset_id,
                "imported_count": indexed,
                "skipped_duplicate_count": skipped_duplicates,
            },
        )
