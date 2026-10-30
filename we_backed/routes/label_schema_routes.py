"""Label schema management routes."""

import app as app_module

from flask import jsonify
from flask import request
from flask import session
from pymysql.err import IntegrityError
import json

from app import (
    login_required,
    parse_label_options,
    role_required,
    write_audit_log,
)


def register_label_schema_routes(app):
    @app.get("/api/label-schemas")
    @login_required
    def list_label_schemas():
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, description, labels_json, version, updated_by, updated_at
                FROM label_schemas ORDER BY id
                """
            )
            rows = cursor.fetchall()
        schemas = []
        for row in rows:
            schema = dict(row)
            schema["labels"] = json.loads(schema.pop("labels_json"))
            schemas.append(schema)
        return jsonify(code=0, message="ok", data=schemas)

    @app.post("/api/label-schemas")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人")
    def create_label_schema():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        name = payload.get("name")
        description = payload.get("description", "")
        labels = parse_label_options(payload.get("labels"))
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 191:
            return jsonify(code=400, message="标签体系名称不能为空且不能超过 191 个字符。", data=None), 400
        if not isinstance(description, str) or len(description) > 2000 or labels is None:
            return jsonify(
                code=400,
                message="说明长度不能超过 2000 个字符，且标签需包含 2 到 100 个唯一编码与名称。",
                data=None,
            ), 400
        db = app_module.get_db()
        try:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO label_schemas
                        (name, description, labels_json, updated_by)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        name.strip(),
                        description.strip(),
                        json.dumps(labels, ensure_ascii=False),
                        session["username"],
                    ),
                )
                schema_id = cursor.lastrowid
                cursor.execute(
                    """
                    INSERT INTO label_schema_versions
                        (schema_id, version, labels_json, changed_by)
                    VALUES (%s, 1, %s, %s)
                    """,
                    (schema_id, json.dumps(labels, ensure_ascii=False), session["username"]),
                )
            write_audit_log("创建", "标签体系", schema_id, {"name": name.strip()})
            db.commit()
        except IntegrityError:
            return jsonify(code=409, message="标签体系名称已存在。", data=None), 409
        return jsonify(
            code=0,
            message="标签体系已创建。",
            data={
                "id": schema_id,
                "name": name.strip(),
                "description": description.strip(),
                "labels": labels,
                "version": 1,
            },
        ), 201

    @app.put("/api/label-schemas/<int:schema_id>")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人")
    def update_label_schema(schema_id: int):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        labels = parse_label_options(payload.get("labels"))
        description = payload.get("description", "")
        if labels is None or not isinstance(description, str) or len(description) > 2000:
            return jsonify(code=400, message="标签配置无效或说明超过 2000 个字符。", data=None), 400
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT version FROM label_schemas WHERE id = %s",
                (schema_id,),
            )
            schema = cursor.fetchone()
            if schema is None:
                return jsonify(code=404, message="标签体系不存在。", data=None), 404
            version = schema["version"] + 1
            labels_json = json.dumps(labels, ensure_ascii=False)
            cursor.execute(
                """
                UPDATE label_schemas
                SET labels_json = %s, description = %s, version = %s, updated_by = %s
                WHERE id = %s
                """,
                (labels_json, description.strip(), version, session["username"], schema_id),
            )
            cursor.execute(
                """
                INSERT INTO label_schema_versions
                    (schema_id, version, labels_json, changed_by)
                VALUES (%s, %s, %s, %s)
                """,
                (schema_id, version, labels_json, session["username"]),
            )
        write_audit_log("更新", "标签体系", schema_id, {"version": version})
        db.commit()
        return jsonify(
            code=0,
            message="标签体系已更新。",
            data={"id": schema_id, "labels": labels, "version": version},
        )

    @app.get("/api/label-schemas/<int:schema_id>/versions")
    @login_required
    def label_schema_versions(schema_id: int):
        with app_module.get_db().cursor() as cursor:
            cursor.execute("SELECT id FROM label_schemas WHERE id = %s", (schema_id,))
            if cursor.fetchone() is None:
                return jsonify(code=404, message="标签体系不存在。", data=None), 404
            cursor.execute(
                """
                SELECT version, labels_json, changed_by, changed_at
                FROM label_schema_versions WHERE schema_id = %s ORDER BY version DESC
                """,
                (schema_id,),
            )
            rows = cursor.fetchall()
        versions = [
            {
                **dict(row),
                "labels": json.loads(row["labels_json"]),
            }
            for row in rows
        ]
        for version in versions:
            version.pop("labels_json", None)
        return jsonify(code=0, message="ok", data=versions)
