"""User, audit, statistics, and quality API routes."""

import app as app_module

from datetime import datetime
from datetime import timezone
from elasticsearch.exceptions import ApiError
from elasticsearch.exceptions import NotFoundError
from elasticsearch.exceptions import TransportError
from flask import current_app
from flask import jsonify
from flask import request
from flask import session
import json
from werkzeug.security import generate_password_hash
from pymysql.err import IntegrityError

from app import (
    accessible_dataset_ids,
    can_access_data_source,
    can_access_dataset,
    elastic_error_response,
    get_data_item,
    is_global_project_admin,
    login_required,
    role_required,
    scoped_dataset_filter,
    user_can_access_project,
    write_audit_log,
)
from .notification_helpers import add_notification

USER_ROLES = {
    "超级管理员",
    "项目管理员",
    "任务负责人",
    "标注员",
    "审核员",
    "数据分析员",
}


def register_admin_routes(app):
    @app.get("/api/users")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def list_users():
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT id, username, role, is_active FROM users ORDER BY username"
            )
            rows = cursor.fetchall()
        for row in rows:
            row["is_active"] = bool(row.get("is_active", 1))
        return jsonify(code=0, message="ok", data=[dict(row) for row in rows])

    @app.post("/api/users")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def create_user():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象。", data=None), 400
        username = payload.get("username")
        password = payload.get("password")
        role = payload.get("role", "标注员")
        if (
            not isinstance(username, str)
            or not username.strip()
            or len(username.strip()) > 191
        ):
            return jsonify(code=400, message="账号不能为空且不能超过 191 个字符。", data=None), 400
        if not isinstance(password, str) or len(password) < 8:
            return jsonify(code=400, message="初始密码至少需要 8 个字符。", data=None), 400
        if not isinstance(role, str) or role not in USER_ROLES:
            return jsonify(code=400, message="用户角色无效。", data=None), 400

        db = app_module.get_db()
        normalized_username = username.strip()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM users WHERE username = %s",
                (normalized_username,),
            )
            if cursor.fetchone() is not None:
                return jsonify(code=409, message="账号已存在。", data=None), 409
            try:
                cursor.execute(
                    """
                    INSERT INTO users (username, password_hash, role, is_active)
                    VALUES (%s, %s, %s, 1)
                    """,
                    (
                        normalized_username,
                        generate_password_hash(password),
                        role,
                    ),
                )
            except IntegrityError:
                return jsonify(code=409, message="账号已存在。", data=None), 409
            user_id = cursor.lastrowid
        write_audit_log(
            "创建用户",
            "用户",
            user_id,
            {"username": normalized_username, "role": role},
        )
        db.commit()
        return jsonify(
            code=0,
            message="用户已创建。",
            data={
                "id": user_id,
                "username": normalized_username,
                "role": role,
                "is_active": True,
            },
        ), 201

    def save_user(user_id: int, payload):
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象。", data=None), 400
        allowed_fields = {"username", "role", "password", "is_active"}
        if not payload or set(payload) - allowed_fields:
            return jsonify(code=400, message="用户修改内容无效。", data=None), 400

        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, username, role, is_active, password_hash
                FROM users WHERE id = %s
                """,
                (user_id,),
            )
            user = cursor.fetchone()
            if user is None:
                return jsonify(code=404, message="用户不存在。", data=None), 404

            username = user["username"]
            if "username" in payload:
                proposed_username = payload["username"]
                if (
                    not isinstance(proposed_username, str)
                    or not proposed_username.strip()
                    or len(proposed_username.strip()) > 191
                ):
                    return jsonify(code=400, message="账号不能为空且不能超过 191 个字符。", data=None), 400
                username = proposed_username.strip()
                if username != user["username"]:
                    cursor.execute(
                        "SELECT id FROM users WHERE username = %s AND id != %s",
                        (username, user_id),
                    )
                    if cursor.fetchone() is not None:
                        return jsonify(code=409, message="账号已存在。", data=None), 409

            role = payload.get("role", user["role"])
            if not isinstance(role, str) or role not in USER_ROLES:
                return jsonify(code=400, message="用户角色无效。", data=None), 400

            is_active = user.get("is_active", 1)
            if "is_active" in payload:
                if not isinstance(payload["is_active"], bool):
                    return jsonify(code=400, message="账号状态必须是布尔值。", data=None), 400
                is_active = payload["is_active"]

            password = payload.get("password")
            password_hash = user["password_hash"]
            if password is not None:
                if not isinstance(password, str) or len(password) < 8:
                    return jsonify(code=400, message="新密码至少需要 8 个字符。", data=None), 400
                password_hash = generate_password_hash(password)

            changed_admin_status = (
                user["role"] in {"超级管理员", "项目管理员"}
                and (role not in {"超级管理员", "项目管理员"} or not is_active)
            )
            if changed_admin_status:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total FROM users
                    WHERE role IN ('超级管理员', '项目管理员') AND is_active = 1
                    """
                )
                if cursor.fetchone()["total"] <= 1:
                    return jsonify(
                        code=409,
                        message="至少需要保留一名启用状态的管理员。",
                        data=None,
                    ), 409
            if session.get("user_id") == user_id and not is_active:
                return jsonify(code=409, message="不能禁用当前登录账号。", data=None), 409

            try:
                cursor.execute(
                    """
                    UPDATE users
                    SET username = %s, role = %s, password_hash = %s, is_active = %s,
                        auth_version = auth_version + %s
                    WHERE id = %s
                    """,
                    (
                        username,
                        role,
                        password_hash,
                        int(is_active),
                        int(password is not None),
                        user_id,
                    ),
                )
            except IntegrityError:
                return jsonify(code=409, message="账号已存在。", data=None), 409
            if username != user["username"]:
                cursor.execute(
                    "UPDATE annotation_tasks SET assignee = %s WHERE assignee = %s",
                    (username, user["username"]),
                )
            if session.get("user_id") == user_id and password is not None:
                cursor.execute(
                    """
                    UPDATE active_sessions SET auth_version = auth_version + 1
                    WHERE session_id = %s AND user_id = %s
                    """,
                    (session.get("session_id"), user_id),
                )
                cursor.execute(
                    "UPDATE task_items SET assignee = %s WHERE assignee = %s",
                    (username, user["username"]),
                )

        details = {
            "username": username,
            "role": role,
            "is_active": bool(is_active),
            "password_changed": password is not None,
        }
        write_audit_log("更新用户", "用户", user_id, details)
        db.commit()
        if session.get("user_id") == user_id:
            session["username"] = username
            session["role"] = role
            if password is not None:
                session["auth_version"] = session.get("auth_version", 0) + 1
        return jsonify(
            code=0,
            message="用户信息已更新。",
            data={
                "id": user_id,
                "username": username,
                "role": role,
                "is_active": bool(is_active),
            },
        )

    @app.patch("/api/users/<int:user_id>")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def update_user(user_id: int):
        return save_user(user_id, request.get_json(silent=True))

    @app.patch("/api/users/<int:user_id>/role")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def update_user_role(user_id: int):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"role"}:
            return jsonify(code=400, message="用户角色无效。", data=None), 400
        return save_user(user_id, payload)

    @app.get("/api/audit-logs")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def list_audit_logs():
        try:
            page = int(request.args.get("page", "1"))
            page_size = int(request.args.get("page_size", "50"))
        except ValueError:
            return jsonify(code=400, message="分页参数必须是整数。", data=None), 400
        if page < 1 or not 1 <= page_size <= 100:
            return jsonify(code=400, message="分页参数超出范围。", data=None), 400
        with app_module.get_db().cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM audit_logs")
            total = cursor.fetchone()["total"]
            cursor.execute(
                """
                SELECT id, actor, action, entity_type, entity_id, details_json, created_at
                FROM audit_logs ORDER BY id DESC LIMIT %s OFFSET %s
                """,
                (page_size, (page - 1) * page_size),
            )
            rows = cursor.fetchall()
        logs = []
        for row in rows:
            log = dict(row)
            log["details"] = json.loads(log.pop("details_json"))
            logs.append(log)
        return jsonify(
            code=0,
            message="ok",
            data={"items": logs, "total": total, "page": page, "page_size": page_size},
        )

    @app.get("/api/stats")
    @login_required
    @role_required("超级管理员", "项目管理员", "数据分析员")
    def get_statistics():
        project_id_value = request.args.get("project_id")
        dataset_ids = None if is_global_project_admin() else accessible_dataset_ids()
        if project_id_value is not None:
            try:
                project_id = int(project_id_value)
            except ValueError:
                return jsonify(code=400, message="项目编号必须是正整数。", data=None), 400
            if project_id < 1:
                return jsonify(code=400, message="项目编号必须是正整数。", data=None), 400
            if not user_can_access_project(project_id):
                return jsonify(code=403, message="无权查看该项目统计。", data=None), 403
            with app_module.get_db().cursor() as cursor:
                cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
                if cursor.fetchone() is None:
                    return jsonify(code=404, message="项目不存在。", data=None), 404
                cursor.execute("SELECT id FROM datasets WHERE project_id = %s", (project_id,))
                dataset_ids = [row["id"] for row in cursor.fetchall()]
        project_filter = scoped_dataset_filter(dataset_ids)
        stats_query = (
            {"bool": {"filter": [project_filter]}}
            if project_filter
            else {"match_all": {}}
        )
        try:
            response = app_module.get_es_client().search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query=stats_query,
                size=0,
                track_total_hits=True,
                aggregations={
                    "labels": {"terms": {"field": "label.keyword", "size": 100}},
                    "annotators": {
                        "terms": {"field": "labeled_by.keyword", "size": 100}
                    },
                    "reviews": {
                        "terms": {"field": "review_status.keyword", "size": 10}
                    },
                },
            )
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        total = response["hits"]["total"]
        if isinstance(total, dict):
            total = total["value"]
        aggregations = response.get("aggregations", {})
        label_buckets = aggregations.get("labels", {}).get("buckets", [])
        annotator_buckets = aggregations.get("annotators", {}).get("buckets", [])
        review_buckets = aggregations.get("reviews", {}).get("buckets", [])
        labeled_count = sum(bucket["doc_count"] for bucket in label_buckets)
        review_count = sum(bucket["doc_count"] for bucket in review_buckets)
        with app_module.get_db().cursor() as cursor:
            if dataset_ids is None:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS overdue_tasks
                    FROM annotation_tasks
                    WHERE deadline IS NOT NULL AND deadline < NOW()
                        AND status NOT IN ('已完成', '已暂停')
                    """
                )
            elif project_id_value is not None:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS overdue_tasks
                    FROM annotation_tasks t
                    JOIN datasets d ON d.id = t.dataset_id
                    WHERE d.project_id = %s AND t.deadline IS NOT NULL
                        AND t.deadline < NOW()
                        AND t.status NOT IN ('已完成', '已暂停')
                    """,
                    (project_id,),
                )
            elif dataset_ids:
                placeholders = ", ".join(["%s"] * len(dataset_ids))
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS overdue_tasks
                    FROM annotation_tasks
                    WHERE dataset_id IN ({placeholders})
                        AND deadline IS NOT NULL AND deadline < NOW()
                        AND status NOT IN ('已完成', '已暂停')
                    """,
                    tuple(sorted(dataset_ids)),
                )
            else:
                cursor.execute("SELECT 0 AS overdue_tasks")
            overdue_tasks = cursor.fetchone()["overdue_tasks"]
        return jsonify(
            code=0,
            message="ok",
            data={
                "total": total,
                "labeled": labeled_count,
                "unlabeled": max(total - labeled_count, 0),
                "completion_rate": round(labeled_count * 100 / total, 1)
                if total
                else 0,
                "reviewed": review_count,
                "overdue_tasks": overdue_tasks,
                "labels": [
                    {"name": bucket["key"], "count": bucket["doc_count"]}
                    for bucket in label_buckets
                ],
                "annotators": [
                    {"name": bucket["key"], "count": bucket["doc_count"]}
                    for bucket in annotator_buckets
                ],
            },
        )

    @app.get("/api/reviews")
    @login_required
    def list_reviews():
        status = request.args.get("status", "pending")
        if status not in {"pending", "approved", "returned"}:
            return jsonify(code=400, message="审核状态无效。", data=None), 400
        try:
            page = int(request.args.get("page", "1"))
            page_size = int(request.args.get("page_size", "20"))
        except ValueError:
            return jsonify(
                code=400, message="page 和 page_size 必须是整数。", data=None
            ), 400
        if page < 1 or not 1 <= page_size <= 100:
            return jsonify(
                code=400,
                message="page 必须大于 0，page_size 必须在 1 到 100 之间。",
                data=None,
            ), 400
        if page * page_size > 50000:
            return jsonify(
                code=400,
                message="审核列表最多支持读取前 50000 条记录，请缩小筛选范围。",
                data=None,
            ), 400
        review_filter = (
            {
                "bool": {
                    "should": [
                        {"term": {"review_status.keyword": "pending"}},
                        {"bool": {"must_not": [{"exists": {"field": "review_status"}}]}},
                    ],
                    "minimum_should_match": 1,
                }
            }
            if status == "pending"
            else {"term": {"review_status.keyword": status}}
        )
        filters = [{"exists": {"field": "label"}}, review_filter]
        dataset_filter = scoped_dataset_filter(accessible_dataset_ids())
        if dataset_filter:
            filters.append(dataset_filter)
        dataset_id_raw = request.args.get("dataset_id")
        if dataset_id_raw:
            try:
                dataset_id = int(dataset_id_raw)
            except ValueError:
                return jsonify(
                    code=400, message="dataset_id 必须是正整数。", data=None
                ), 400
            if dataset_id < 1 or not can_access_dataset(dataset_id):
                return jsonify(code=403, message="无权查看该数据集审核记录。", data=None), 403
            if dataset_id == 1:
                filters.append(
                    {
                        "bool": {
                            "should": [
                                {"term": {"dataset_id": 1}},
                                {"bool": {"must_not": [{"exists": {"field": "dataset_id"}}]}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                )
            else:
                filters.append({"term": {"dataset_id": dataset_id}})
        annotator = request.args.get("annotator", "").strip()
        if len(annotator) > 191:
            return jsonify(code=400, message="标注人筛选值过长。", data=None), 400
        if annotator:
            filters.append({"term": {"labeled_by.keyword": annotator}})
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        date_range = {}
        for field, value, key in (
            ("date_from", date_from, "gte"),
            ("date_to", date_to, "lte"),
        ):
            if value:
                try:
                    datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    return jsonify(
                        code=400, message=f"{field} 必须使用 YYYY-MM-DD 格式。", data=None
                    ), 400
                date_range[key] = f"{value}T00:00:00" if key == "gte" else f"{value}T23:59:59"
        if date_range:
            filters.append({"range": {"labeled_at": date_range}})
        if date_from and date_to and date_from > date_to:
            return jsonify(
                code=400, message="date_from 不能晚于 date_to。", data=None
            ), 400
        try:
            response = app_module.get_es_client().search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query={"bool": {"filter": filters}},
                from_=(page - 1) * page_size,
                size=page_size,
                track_total_hits=True,
                sort=[{"labeled_at": {"order": "desc", "missing": "_last"}}],
            )
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        hits = response["hits"]
        total = hits["total"]
        if isinstance(total, dict):
            total = total["value"]
        return jsonify(
            code=0,
            message="ok",
            data={
                "items": [get_data_item(hit) for hit in hits["hits"]],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        )

    @app.put("/api/data-items/<path:item_id>/review")
    @login_required
    @role_required("超级管理员", "项目管理员", "审核员")
    def review_data_item(item_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        decision = payload.get("decision")
        note = payload.get("note", "")
        if not isinstance(decision, str) or decision not in {"approved", "returned"}:
            return jsonify(code=400, message="审核结果必须是 approved 或 returned。", data=None), 400
        if not isinstance(note, str) or len(note) > 1000:
            return jsonify(code=400, message="审核意见不能超过 1000 个字符。", data=None), 400
        if decision == "returned" and not note.strip():
            return jsonify(code=400, message="退回时必须填写修改意见。", data=None), 400
        reviewed_at = datetime.now(timezone.utc).isoformat()
        try:
            client = app_module.get_es_client()
            document = client.get(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
            )
            source = document.get("_source") or {}
            if not can_access_data_source(source):
                return jsonify(code=403, message="无权审核该项目的数据。", data=None), 403
            if source.get("review_status") in {"approved", "returned"}:
                return jsonify(
                    code=409,
                    message="该记录已经审核，重新标注后才能再次审核。",
                    data=None,
                ), 409
            client.update(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
                script={
                    "lang": "painless",
                    "source": """
                        if (ctx._source.review_history == null) {
                            ctx._source.review_history = [];
                        }
                        def entry = [
                            'decision': params.decision,
                            'reviewer': params.reviewer,
                            'note': params.note,
                            'reviewed_at': params.reviewed_at
                        ];
                        ctx._source.review_history.add(entry);
                        ctx._source.review_status = params.decision;
                        ctx._source.reviewed_by = params.reviewer;
                        ctx._source.reviewed_at = params.reviewed_at;
                        ctx._source.review_note = params.note;
                    """,
                    "params": {
                        "decision": decision,
                        "reviewer": session["username"],
                        "note": note.strip(),
                        "reviewed_at": reviewed_at,
                    },
                },
                doc_as_upsert=False,
                refresh="wait_for",
            )
        except NotFoundError as error:
            return elastic_error_response(error)
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT task_id, assignee FROM task_items WHERE item_id = %s",
                (item_id,),
            )
            task_items = cursor.fetchall()
            task_ids = [row["task_id"] for row in task_items]
            if task_ids:
                item_status = "已审核" if decision == "approved" else "已退回"
                cursor.execute(
                    "UPDATE task_items SET status = %s WHERE item_id = %s",
                    (item_status, item_id),
                )
                if decision == "returned":
                    cursor.executemany(
                        "UPDATE annotation_tasks SET status = '已退回' WHERE id = %s",
                        [(task_id,) for task_id in task_ids],
                    )
                else:
                    for task_id in task_ids:
                        cursor.execute(
                            """
                            SELECT COUNT(*) AS remaining
                            FROM task_items
                            WHERE task_id = %s
                                AND status NOT IN ('已审核', '已跳过')
                            """,
                            (task_id,),
                        )
                        if cursor.fetchone()["remaining"] == 0:
                            cursor.execute(
                                """
                                UPDATE annotation_tasks SET status = '已完成'
                                WHERE id = %s
                                """,
                                (task_id,),
                            )
                for assignee in {
                    row.get("assignee")
                    for row in task_items
                    if row.get("assignee") and row["assignee"] != session["username"]
                }:
                    add_notification(
                        cursor,
                        assignee,
                        "标注审核结果已更新",
                        (
                            f"数据 {item_id} 已通过审核。"
                            if decision == "approved"
                            else f"数据 {item_id} 已退回，请根据审核意见修改。"
                        ),
                        f"/data/label/{task_ids[0]['task_id']}",
                    )
        db.commit()
        return jsonify(
            code=0,
            message="审核结果已保存。",
            data={
                "id": item_id,
                "decision": decision,
                "reviewed_by": session["username"],
                "reviewed_at": reviewed_at,
                "note": note.strip(),
            },
        )

    @app.get("/api/quality-trends")
    @login_required
    @role_required(*USER_ROLES - {"标注员", "数据分析员"})
    def quality_trends():
        dataset_id_raw = request.args.get("dataset_id")
        filters = [{"exists": {"field": "reviewed_at"}}]
        project_filter = scoped_dataset_filter(accessible_dataset_ids())
        if project_filter:
            filters.append(project_filter)
        if dataset_id_raw:
            try:
                dataset_id = int(dataset_id_raw)
            except ValueError:
                return jsonify(code=400, message="dataset_id 必须是正整数。", data=None), 400
            if dataset_id < 1:
                return jsonify(code=400, message="dataset_id 必须是正整数。", data=None), 400
            if not can_access_dataset(dataset_id):
                return jsonify(code=403, message="无权查看该数据集的质检趋势。", data=None), 403
            filters.append({"term": {"dataset_id": dataset_id}})
        try:
            response = app_module.get_es_client().search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query={"bool": {"filter": filters}},
                size=0,
                aggregations={
                    "monthly": {
                        "date_histogram": {
                            "field": "reviewed_at",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 0,
                        },
                        "aggs": {
                            "decisions": {
                                "terms": {
                                    "field": "review_status.keyword",
                                    "size": 2,
                                }
                            }
                        },
                    }
                },
            )
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        buckets = response.get("aggregations", {}).get("monthly", {}).get("buckets", [])
        trends = []
        for bucket in buckets:
            decisions = {
                decision["key"]: decision["doc_count"]
                for decision in bucket.get("decisions", {}).get("buckets", [])
            }
            trends.append(
                {
                    "month": bucket.get("key_as_string"),
                    "approved": decisions.get("approved", 0),
                    "returned": decisions.get("returned", 0),
                    "total": bucket["doc_count"],
                }
            )
        return jsonify(code=0, message="ok", data=trends)

    @app.get("/api/data-items/<path:item_id>/quality-check")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人", "审核员")
    def quality_check_data_item(item_id: str):
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT rule_key, enabled, threshold FROM quality_rules"
            )
            rules = {
                row["rule_key"]: row
                for row in cursor.fetchall()
            }
        client = app_module.get_es_client()
        try:
            response = client.get(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
            )
            source = response.get("_source") or {}
            if not can_access_data_source(source):
                return jsonify(code=403, message="无权检查该项目的数据。", data=None), 403
            content = next(
                (
                    source[key]
                    for key in ("content", "text")
                    if isinstance(source.get(key), str)
                ),
                "",
            )
            warnings = []
            if rules["empty_content"]["enabled"] and not content.strip():
                warnings.append("数据内容为空。")
            elif (
                rules["min_length"]["enabled"]
                and len(content.strip()) < rules["min_length"]["threshold"]
            ):
                warnings.append(
                    f"数据内容短于 {rules['min_length']['threshold']} 个字符，请确认是否完整。"
                )
            if rules["missing_label"]["enabled"] and (
                not isinstance(source.get("label"), str) or not source["label"].strip()
            ):
                warnings.append("尚未设置标注结果。")
            if (
                rules["missing_annotator"]["enabled"]
                and isinstance(source.get("label"), str)
                and not source.get("labeled_by")
            ):
                warnings.append("缺少标注人信息。")
            if rules["duplicate_content"]["enabled"] and content.strip():
                duplicates = client.search(
                    index=current_app.config["ELASTICSEARCH_INDEX"],
                    query={
                        "bool": {
                            "must": [{"match_phrase": {"content": content.strip()}}],
                            "filter": [
                                {
                                    "term": {
                                        "dataset_id": source.get("dataset_id", 1)
                                    }
                                }
                            ],
                            "must_not": [{"ids": {"values": [item_id]}}],
                        }
                    },
                    from_=0,
                    size=1,
                    track_total_hits=True,
                )
                if duplicates["hits"]["hits"]:
                    warnings.append("发现相同内容的数据记录，请检查重复标注。")
        except NotFoundError as error:
            return elastic_error_response(error)
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        return jsonify(
            code=0,
            message="自动质检完成。",
            data={"passed": not warnings, "warnings": warnings},
        )
