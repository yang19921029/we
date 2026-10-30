"""Annotation task and assignment routes."""

import app as app_module

from datetime import datetime
from elasticsearch.exceptions import ApiError
from elasticsearch.exceptions import TransportError
from flask import current_app
from flask import jsonify
from flask import request
from flask import session

from app import (
    can_access_task,
    elastic_error_response,
    is_global_project_admin,
    login_required,
    role_required,
    user_can_access_project,
    write_audit_log,
)


def register_task_routes(app):
    @app.get("/api/tasks")
    @login_required
    def list_tasks():
        with app_module.get_db().cursor() as cursor:
            where_clauses = []
            params = []
            if session.get("role") == "标注员":
                where_clauses.append("t.assignee = %s")
                params.append(session["username"])
            if not is_global_project_admin():
                where_clauses.append(
                    """
                    EXISTS (
                        SELECT 1 FROM project_members pm
                        WHERE pm.project_id = d.project_id AND pm.user_id = %s
                    )
                    """
                )
                params.append(session["user_id"])
            where_clause = (
                f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            )
            cursor.execute(
                f"""
                SELECT t.id, t.name, t.dataset_id, d.name AS dataset_name,
                    d.project_id, p.name AS project_name,
                    t.label_schema_id, s.name AS label_schema_name,
                    t.assignee, t.priority, t.status, t.deadline,
                    t.instructions, t.created_by, t.created_at,
                    COUNT(i.item_id) AS total_items,
                    SUM(CASE WHEN i.status = '已标注' THEN 1 ELSE 0 END) AS labeled_items
                FROM annotation_tasks t
                JOIN datasets d ON d.id = t.dataset_id
                JOIN projects p ON p.id = d.project_id
                JOIN label_schemas s ON s.id = t.label_schema_id
                LEFT JOIN task_items i ON i.task_id = t.id
                {where_clause}
                GROUP BY t.id, t.name, t.dataset_id, d.name, d.project_id, p.name,
                    t.label_schema_id, s.name, t.assignee, t.priority, t.status,
                    t.deadline, t.instructions, t.created_by, t.created_at
                ORDER BY t.created_at DESC, t.id DESC
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
        return jsonify(code=0, message="ok", data=[dict(row) for row in rows])

    @app.post("/api/tasks")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人")
    def create_task():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        name = payload.get("name")
        dataset_id = payload.get("dataset_id")
        schema_id = payload.get("label_schema_id")
        assignee = payload.get("assignee", session["username"])
        priority = payload.get("priority", "中")
        instructions = payload.get("instructions", "")
        deadline = payload.get("deadline") or None
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 191:
            return jsonify(code=400, message="任务名称不能为空且不能超过 191 个字符。", data=None), 400
        if (
            not isinstance(dataset_id, int)
            or isinstance(dataset_id, bool)
            or not isinstance(schema_id, int)
            or isinstance(schema_id, bool)
            or not isinstance(assignee, str)
            or not assignee.strip()
            or not isinstance(priority, str)
            or priority not in {"高", "中", "低"}
            or not isinstance(instructions, str)
            or len(instructions) > 2000
        ):
            return jsonify(code=400, message="任务配置无效。", data=None), 400
        if deadline is not None:
            if not isinstance(deadline, str):
                return jsonify(code=400, message="截止时间格式无效。", data=None), 400
            try:
                deadline = datetime.fromisoformat(deadline).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                return jsonify(code=400, message="截止时间格式无效。", data=None), 400
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id, project_id FROM datasets WHERE id = %s", (dataset_id,))
            dataset = cursor.fetchone()
            if dataset is None:
                return jsonify(code=400, message="所选数据集不存在。", data=None), 400
            if not user_can_access_project(dataset["project_id"]):
                return jsonify(code=403, message="无权在该项目创建标注任务。", data=None), 403
            cursor.execute("SELECT id FROM label_schemas WHERE id = %s", (schema_id,))
            if cursor.fetchone() is None:
                return jsonify(code=400, message="所选标签体系不存在。", data=None), 400
            cursor.execute(
                """
                SELECT u.id
                FROM users u
                JOIN project_members pm ON pm.user_id = u.id
                WHERE u.username = %s AND pm.project_id = %s
                """,
                (assignee.strip(), dataset["project_id"]),
            )
            if cursor.fetchone() is None:
                return jsonify(code=400, message="负责人必须是该项目成员。", data=None), 400
        try:
            search_query = (
                {
                    "bool": {
                        "should": [
                            {"term": {"dataset_id": dataset_id}},
                            {"bool": {"must_not": [{"exists": {"field": "dataset_id"}}]}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
                if dataset_id == 1
                else {"term": {"dataset_id": dataset_id}}
            )
            search_result = app_module.get_es_client().search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query=search_query,
                from_=0,
                size=10000,
                track_total_hits=True,
            )
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            db.rollback()
            return elastic_error_response(error)
        task_hits = search_result["hits"]
        task_total = task_hits["total"]
        if isinstance(task_total, dict):
            task_total = task_total["value"]
        if task_total > 10000:
            db.rollback()
            return jsonify(
                code=413,
                message="单个任务最多包含 10000 条数据，请先拆分数据集。",
                data=None,
            ), 413
        if not task_hits["hits"]:
            db.rollback()
            return jsonify(code=409, message="所选数据集没有可分配的数据。", data=None), 409
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO annotation_tasks
                    (name, dataset_id, label_schema_id, assignee, priority,
                     status, deadline, instructions, created_by)
                VALUES (%s, %s, %s, %s, %s, '待分配', %s, %s, %s)
                """,
                (
                    name.strip(),
                    dataset_id,
                    schema_id,
                    assignee.strip(),
                    priority,
                    deadline,
                    instructions.strip(),
                    session["username"],
                ),
            )
            task_id = cursor.lastrowid
            cursor.executemany(
                """
                INSERT INTO task_items (task_id, item_id, assignee, status)
                VALUES (%s, %s, %s, '待标注')
                """,
                [
                    (task_id, str(hit["_id"]), assignee.strip())
                    for hit in task_hits["hits"]
                ],
            )
        write_audit_log("创建", "标注任务", task_id, {"name": name.strip()})
        db.commit()
        return jsonify(
            code=0,
            message="标注任务已创建。",
            data={
                "id": task_id,
                "name": name.strip(),
                "dataset_id": dataset_id,
                "label_schema_id": schema_id,
                "assignee": assignee.strip(),
                "priority": priority,
                "status": "待分配",
            },
        ), 201

    @app.patch("/api/tasks/<int:task_id>")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人")
    def update_task(task_id: int):
        if not can_access_task(task_id):
            return jsonify(code=403, message="无权访问该标注任务。", data=None), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not payload:
            return jsonify(code=400, message="请求体必须是非空 JSON 对象。", data=None), 400
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT d.project_id FROM annotation_tasks t
                JOIN datasets d ON d.id = t.dataset_id WHERE t.id = %s
                """,
                (task_id,),
            )
            task_scope = cursor.fetchone()
        if task_scope is None:
            return jsonify(code=404, message="标注任务不存在。", data=None), 404
        updates = []
        values = []
        if "assignee" in payload:
            assignee = payload["assignee"]
            if not isinstance(assignee, str) or not assignee.strip():
                return jsonify(code=400, message="负责人不能为空。", data=None), 400
            with app_module.get_db().cursor() as cursor:
                cursor.execute(
                    """
                    SELECT u.id FROM users u
                    JOIN project_members pm ON pm.user_id = u.id
                    WHERE u.username = %s AND pm.project_id = %s
                    """,
                    (assignee.strip(), task_scope["project_id"]),
                )
                if cursor.fetchone() is None:
                    return jsonify(code=400, message="负责人必须是该项目成员。", data=None), 400
            updates.append("assignee = %s")
            values.append(assignee.strip())
        if "status" in payload:
            status = payload["status"]
            if not isinstance(status, str) or status not in {
                "待分配",
                "待标注",
                "标注中",
                "待审核",
                "已完成",
                "已退回",
                "已暂停",
            }:
                return jsonify(code=400, message="任务状态无效。", data=None), 400
            updates.append("status = %s")
            values.append(status)
        if not updates:
            return jsonify(code=400, message="没有可更新的任务字段。", data=None), 400
        values.append(task_id)
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                f"UPDATE annotation_tasks SET {', '.join(updates)} WHERE id = %s",
                tuple(values),
            )
            if cursor.rowcount == 0:
                cursor.execute("SELECT id FROM annotation_tasks WHERE id = %s", (task_id,))
                if cursor.fetchone() is None:
                    return jsonify(code=404, message="标注任务不存在。", data=None), 404
            if "assignee" in payload:
                cursor.execute(
                    "UPDATE task_items SET assignee = %s WHERE task_id = %s",
                    (payload["assignee"].strip(), task_id),
                )
        write_audit_log("更新", "标注任务", task_id, payload)
        db.commit()
        return jsonify(code=0, message="任务已更新。", data={"id": task_id})

    @app.post("/api/tasks/<int:task_id>/auto-assign")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人")
    def auto_assign_task(task_id: int):
        if not can_access_task(task_id):
            return jsonify(code=403, message="无权访问该标注任务。", data=None), 403
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id, d.project_id FROM annotation_tasks t
                JOIN datasets d ON d.id = t.dataset_id WHERE t.id = %s
                """,
                (task_id,),
            )
            task = cursor.fetchone()
            if task is None:
                return jsonify(code=404, message="标注任务不存在。", data=None), 404
            cursor.execute(
                """
                SELECT u.username, COUNT(t.id) AS active_tasks
                FROM users u
                JOIN project_members pm ON pm.user_id = u.id
                LEFT JOIN annotation_tasks t
                    ON t.assignee = u.username
                    AND t.status IN ('待分配', '待标注', '标注中', '已退回')
                WHERE u.role = '标注员' AND pm.project_id = %s
                GROUP BY u.id, u.username
                ORDER BY active_tasks, u.username
                LIMIT 1
                """,
                (task["project_id"],),
            )
            annotator = cursor.fetchone()
            if annotator is None:
                return jsonify(
                    code=409,
                    message="没有可分配的标注员，请先在人员与权限中添加标注员账号。",
                    data=None,
                ), 409
            cursor.execute(
                """
                UPDATE annotation_tasks
                SET assignee = %s, status = '待标注'
                WHERE id = %s
                """,
                (annotator["username"], task_id),
            )
            cursor.execute(
                "UPDATE task_items SET assignee = %s WHERE task_id = %s",
                (annotator["username"], task_id),
            )
        write_audit_log(
            "自动分配",
            "标注任务",
            task_id,
            {"assignee": annotator["username"]},
        )
        db.commit()
        return jsonify(
            code=0,
            message="任务已自动分配。",
            data={"id": task_id, "assignee": annotator["username"]},
        )

    @app.post("/api/tasks/<int:task_id>/items/<path:item_id>/skip")
    @login_required
    def skip_task_item(task_id: int, item_id: str):
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT i.assignee, t.status AS task_status, d.project_id
                FROM task_items i
                JOIN annotation_tasks t ON t.id = i.task_id
                JOIN datasets d ON d.id = t.dataset_id
                WHERE i.task_id = %s AND i.item_id = %s
                """,
                (task_id, item_id),
            )
            task_item = cursor.fetchone()
            if task_item is None:
                return jsonify(code=404, message="任务数据不存在。", data=None), 404
            if not user_can_access_project(task_item["project_id"]):
                return jsonify(code=403, message="无权访问该项目任务。", data=None), 403
            if task_item["assignee"] != session["username"]:
                return jsonify(code=403, message="当前任务数据未分配给你。", data=None), 403
            if task_item["task_status"] == "已暂停":
                return jsonify(code=409, message="任务已暂停，不能跳过数据。", data=None), 409
            cursor.execute(
                """
                UPDATE task_items SET status = '已跳过'
                WHERE task_id = %s AND item_id = %s
                """,
                (task_id, item_id),
            )
            cursor.execute(
                """
                SELECT COUNT(*) AS remaining
                FROM task_items
                WHERE task_id = %s AND status NOT IN ('已标注', '已跳过')
                """,
                (task_id,),
            )
            remaining = cursor.fetchone()["remaining"]
            if remaining == 0:
                cursor.execute(
                    "UPDATE annotation_tasks SET status = '待审核' WHERE id = %s",
                    (task_id,),
                )
        write_audit_log("跳过数据", "标注任务", task_id, {"item_id": item_id})
        db.commit()
        return jsonify(code=0, message="数据已跳过。", data={"id": item_id})
