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
import ijson
from pymysql.err import IntegrityError
from werkzeug.exceptions import RequestEntityTooLarge
import csv
import io
import json
import sqlite3
import tempfile
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


MAX_IMPORT_FILE_BYTES = 1024 * 1024 * 1024
MAX_IMPORT_RECORD_BYTES = 50 * 1024 * 1024
MAX_IMPORT_REQUEST_OVERHEAD_BYTES = 1024 * 1024
IMPORT_BULK_MAX_RECORDS = 100
IMPORT_BULK_MAX_BYTES = 5 * 1024 * 1024


class DatasetImportError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def _iter_dataset_import_records(uploaded_file, filename):
    stream = uploaded_file.stream
    stream.seek(0)
    if filename.endswith(".csv"):
        text_stream = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
        try:
            yield from csv.DictReader(text_stream)
        finally:
            text_stream.detach()
        return
    if filename.endswith((".jsonl", ".ndjson")):
        first_line = True
        while line := stream.readline(MAX_IMPORT_RECORD_BYTES + 1):
            if len(line) > MAX_IMPORT_RECORD_BYTES:
                raise DatasetImportError("单条记录不能超过 50 MB。", 413)
            try:
                decoded_line = line.decode("utf-8-sig" if first_line else "utf-8")
            except UnicodeDecodeError:
                raise
            first_line = False
            if decoded_line.strip():
                yield json.loads(decoded_line)
        return
    if not filename.endswith(".json"):
        raise ValueError("仅支持 CSV、JSON、JSONL 文件。")

    stream.seek(0)
    has_bom = stream.read(3) == b"\xef\xbb\xbf"
    json_start = 3 if has_bom else 0
    stream.seek(json_start)
    first_content_byte = b""
    while chunk := stream.read(64 * 1024):
        non_whitespace = chunk.lstrip(b" \t\r\n")
        if non_whitespace:
            first_content_byte = non_whitespace[:1]
            break
    stream.seek(json_start)
    if first_content_byte == b"[":
        yield from ijson.items(stream, "item")
        return
    if first_content_byte == b"{":
        found_items = False
        for record in ijson.items(stream, "items.item"):
            found_items = True
            yield record
        if found_items:
            return

    stream.seek(0)
    stream_size = stream.seek(0, io.SEEK_END)
    stream.seek(0)
    if stream_size > MAX_IMPORT_RECORD_BYTES:
        raise DatasetImportError("JSON 文件中的单条记录不能超过 50 MB。", 413)
    text_stream = io.TextIOWrapper(stream, encoding="utf-8-sig")
    try:
        parsed = json.load(text_stream)
    finally:
        text_stream.detach()
    records = parsed if isinstance(parsed, list) else (
        parsed.get("items", [parsed]) if isinstance(parsed, dict) else parsed
    )
    if not isinstance(records, list):
        raise DatasetImportError(
            "JSON 文件必须是对象数组、包含 items 数组的对象或单个对象。"
        )
    yield from records


def _validate_dataset_import_records(uploaded_file, filename):
    return _inspect_dataset_import_records(uploaded_file, filename)["record_count"]


def _inspect_dataset_import_records(uploaded_file, filename, sample_limit=10):
    record_count = 0
    preview_records = []
    for record in _iter_dataset_import_records(uploaded_file, filename):
        if not isinstance(record, dict):
            raise DatasetImportError("文件中的每条记录都必须是 JSON 对象。")
        record_size = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if record_size > MAX_IMPORT_RECORD_BYTES:
            raise DatasetImportError("单条记录不能超过 50 MB。", 413)
        record_count += 1
        if len(preview_records) < sample_limit:
            preview_records.append(record)
    if record_count == 0:
        raise DatasetImportError("文件必须包含至少 1 条 JSON 对象记录。")
    fields = list(
        dict.fromkeys(
            field
            for record in preview_records
            for field in record
        )
    )
    return {
        "record_count": record_count,
        "fields": fields,
        "preview": preview_records,
    }


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
                SELECT u.id, u.username, u.role, u.is_active,
                    pm.created_at, adder.username AS added_by
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
                cursor.execute(
                    "SELECT id, username, role, is_active FROM users WHERE id = %s",
                    (user_id,),
                )
                user = cursor.fetchone()
                if user is None:
                    return jsonify(code=404, message="用户不存在。", data=None), 404
                if not user.get("is_active", 1):
                    return jsonify(code=409, message="不能将已禁用账号添加为项目成员。", data=None), 409
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
                        d.created_at, d.project_id, p.name AS project_name,
                        (SELECT MAX(dv.version) FROM dataset_versions dv
                         WHERE dv.dataset_id = d.id) AS latest_version
                    FROM datasets d JOIN projects p ON p.id = d.project_id
                    ORDER BY d.id
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT d.id, d.name, d.description, d.record_count, d.created_by,
                        d.created_at, d.project_id, p.name AS project_name,
                        (SELECT MAX(dv.version) FROM dataset_versions dv
                         WHERE dv.dataset_id = d.id) AS latest_version
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

    @app.get("/api/datasets/<int:dataset_id>/versions")
    @login_required
    def list_dataset_versions(dataset_id: int):
        if not can_access_dataset(dataset_id):
            return jsonify(code=403, message="无权访问该数据集。", data=None), 403
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT id, version, imported_count, status, source_name,
                    created_by, created_at
                FROM dataset_versions WHERE dataset_id = %s
                ORDER BY version DESC
                """,
                (dataset_id,),
            )
            versions = [dict(row) for row in cursor.fetchall()]
        return jsonify(code=0, message="ok", data=versions)

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
        request.max_content_length = (
            MAX_IMPORT_FILE_BYTES + MAX_IMPORT_REQUEST_OVERHEAD_BYTES
        )
        try:
            uploaded_file = request.files.get("file")
        except RequestEntityTooLarge:
            return jsonify(
                code=413,
                message="导入请求过大，单个文件上限为 1 GB（1024 MB）。",
                data=None,
            ), 413
        if uploaded_file is None or not uploaded_file.filename:
            return jsonify(code=400, message="请选择要导入的文件。", data=None), 400
        filename = uploaded_file.filename.lower()
        if not filename.endswith((".csv", ".json", ".jsonl", ".ndjson")):
            return jsonify(
                code=400,
                message="仅支持 CSV、JSON、JSONL 文件。",
                data=None,
            ), 400
        try:
            stream = uploaded_file.stream
            stream.seek(0, io.SEEK_END)
            file_size = stream.tell()
            stream.seek(0)
            if file_size > MAX_IMPORT_FILE_BYTES:
                return jsonify(
                    code=413,
                    message="单个导入文件不能超过 1 GB（1024 MB）。",
                    data=None,
                ), 413
            preview_only = request.form.get("preview_only", "").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if preview_only:
                preview = _inspect_dataset_import_records(uploaded_file, filename)
                return jsonify(
                    code=0,
                    message="文件预检通过。",
                    data={
                        "dataset_id": dataset_id,
                        **preview,
                    },
                )
            _validate_dataset_import_records(uploaded_file, filename)
        except UnicodeDecodeError:
            return jsonify(code=400, message="文件必须使用 UTF-8 编码。", data=None), 400
        except DatasetImportError as error:
            return jsonify(
                code=error.status_code,
                message=str(error),
                data=None,
            ), error.status_code
        except (json.JSONDecodeError, ijson.JSONError, csv.Error, ValueError) as error:
            return jsonify(code=400, message=f"文件格式错误：{error}", data=None), 400

        with app_module.get_db().cursor() as cursor:
            cursor.execute("SELECT id FROM datasets WHERE id = %s", (dataset_id,))
            dataset = cursor.fetchone()
        if dataset is None:
            return jsonify(code=404, message="数据集不存在。", data=None), 404

        indexed = 0
        skipped_duplicates = 0
        failed_records = 0
        import_error = None
        with tempfile.TemporaryDirectory() as temp_dir:
            dedupe_db = sqlite3.connect(f"{temp_dir}/import-ids.sqlite3")
            try:
                dedupe_db.execute(
                    "CREATE TABLE imported_ids (id TEXT PRIMARY KEY)"
                )
                client = app_module.get_es_client()
                operations = []
                batch_bytes = 0
                record_number = 0

                def write_batch():
                    nonlocal indexed, failed_records, skipped_duplicates, batch_bytes
                    if not operations:
                        return
                    result = client.bulk(
                        operations=operations,
                        refresh=False,
                    )
                    for item in result.get("items", []):
                        operation_result = next(iter(item.values()), {})
                        status_code = operation_result.get("status", 0)
                        if 200 <= status_code < 300:
                            indexed += 1
                        elif status_code == 409:
                            skipped_duplicates += 1
                        else:
                            failed_records += 1
                    if len(result.get("items", [])) != len(operations) // 2:
                        raise RuntimeError(
                            "Elasticsearch Bulk 响应中的记录数与请求不匹配。"
                        )
                    operations.clear()
                    batch_bytes = 0

                for record in _iter_dataset_import_records(uploaded_file, filename):
                    record_number += 1
                    external_id = record.get("_id", record.get("source_id"))
                    item_id = (
                        f"ds-{dataset_id}-{external_id}"
                        if isinstance(external_id, (str, int))
                        and str(external_id).strip()
                        and len(str(external_id)) <= 200
                        else "ds-{}-{}".format(
                            dataset_id,
                            uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                "{}:{}:{}".format(
                                    dataset_id,
                                    record_number,
                                    json.dumps(
                                        record,
                                        ensure_ascii=False,
                                        sort_keys=True,
                                        separators=(",", ":"),
                                    ),
                                ),
                            ).hex,
                        )
                    )
                    inserted = dedupe_db.execute(
                        "INSERT OR IGNORE INTO imported_ids (id) VALUES (?)",
                        (item_id,),
                    )
                    if inserted.rowcount == 0:
                        skipped_duplicates += 1
                        continue
                    document = dict(record)
                    document.pop("_id", None)
                    document["dataset_id"] = dataset_id
                    document.setdefault(
                        "inserted_at", datetime.now(timezone.utc).isoformat()
                    )
                    action = {
                        "create": {
                            "_index": current_app.config["ELASTICSEARCH_INDEX"],
                            "_id": item_id,
                        }
                    }
                    document_bytes = len(
                        json.dumps(document, ensure_ascii=False).encode("utf-8")
                    )
                    if operations and (
                        len(operations) // 2 >= IMPORT_BULK_MAX_RECORDS
                        or batch_bytes + document_bytes > IMPORT_BULK_MAX_BYTES
                    ):
                        write_batch()
                    operations.extend((action, document))
                    batch_bytes += document_bytes
                write_batch()
                if indexed:
                    client.indices.refresh(
                        index=current_app.config["ELASTICSEARCH_INDEX"]
                    )
            except (ApiError, TransportError, RuntimeError, ValueError) as error:
                import_error = error
            finally:
                dedupe_db.close()

        db = app_module.get_db()
        dataset_version = None
        if indexed:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM datasets WHERE id = %s FOR UPDATE",
                    (dataset_id,),
                )
                cursor.fetchone()
                cursor.execute(
                    "SELECT COALESCE(MAX(version), 0) AS current_version "
                    "FROM dataset_versions WHERE dataset_id = %s",
                    (dataset_id,),
                )
                dataset_version = cursor.fetchone()["current_version"] + 1
                cursor.execute(
                    "UPDATE datasets SET record_count = record_count + %s WHERE id = %s",
                    (indexed, dataset_id),
                )
                cursor.execute(
                    """
                    INSERT INTO dataset_versions
                        (dataset_id, version, imported_count, status, source_name, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        dataset_id,
                        dataset_version,
                        indexed,
                        "部分失败" if failed_records or import_error else "已完成",
                        filename[:255],
                        session["username"],
                    ),
                )
        write_audit_log(
            "导入数据",
            "数据集",
            dataset_id,
            {
                "imported_count": indexed,
                "failed_count": failed_records,
                "skipped_duplicate_count": skipped_duplicates,
                "dataset_version": dataset_version,
            },
        )
        db.commit()
        if import_error is not None:
            if indexed or failed_records:
                current_app.logger.error(
                    "Dataset import stopped after a Bulk request error; "
                    "%s successful and %s rejected records were confirmed.",
                    indexed,
                    failed_records,
                    exc_info=import_error,
                )
                return jsonify(
                    code=503,
                    message=(
                        f"导入中断：已确认写入 {indexed} 条，"
                        f"失败 {failed_records} 条。数据集计数已更新，"
                        "修复数据后可重新上传同一文件；已成功写入的记录会识别为重复项。"
                    ),
                    data={
                        "dataset_id": dataset_id,
                        "imported_count": indexed,
                        "failed_count": failed_records,
                        "skipped_duplicate_count": skipped_duplicates,
                        "dataset_version": dataset_version,
                    },
                ), 503
            return elastic_error_response(import_error)
        if failed_records:
            current_app.logger.error(
                "Elasticsearch rejected %s dataset import records.", failed_records
            )
            return jsonify(
                code=503,
                message=(
                    f"导入部分失败：成功 {indexed} 条，失败 {failed_records} 条。"
                    "数据集计数已按成功写入数更新；修复数据后重新上传时，"
                    "已成功写入的记录会识别为重复项。"
                ),
                data={
                    "dataset_id": dataset_id,
                    "imported_count": indexed,
                    "failed_count": failed_records,
                    "skipped_duplicate_count": skipped_duplicates,
                },
            ), 503
        return jsonify(
            code=0,
            message="数据导入完成。",
            data={
                "dataset_id": dataset_id,
                "imported_count": indexed,
                "skipped_duplicate_count": skipped_duplicates,
                "dataset_version": dataset_version,
            },
        )
