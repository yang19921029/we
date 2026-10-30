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

from app import (
    accessible_dataset_ids,
    can_access_data_source,
    elastic_error_response,
    get_data_item,
    is_global_project_admin,
    login_required,
    role_required,
    scoped_dataset_filter,
    user_can_access_project,
    write_audit_log,
)


def register_admin_routes(app):
    @app.get("/api/users")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def list_users():
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT id, username, role FROM users ORDER BY username"
            )
            rows = cursor.fetchall()
        return jsonify(code=0, message="ok", data=[dict(row) for row in rows])

    @app.patch("/api/users/<int:user_id>/role")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def update_user_role(user_id: int):
        payload = request.get_json(silent=True)
        roles = {
            "超级管理员",
            "项目管理员",
            "任务负责人",
            "标注员",
            "审核员",
            "数据分析员",
        }
        role = payload.get("role") if isinstance(payload, dict) else None
        if not isinstance(role, str) or role not in roles:
            return jsonify(code=400, message="用户角色无效。", data=None), 400
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id, role FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            if user is None:
                return jsonify(code=404, message="用户不存在。", data=None), 404
            if (
                user["role"] in {"超级管理员", "项目管理员"}
                and role not in {"超级管理员", "项目管理员"}
            ):
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total FROM users
                    WHERE role IN ('超级管理员', '项目管理员')
                    """
                )
                if cursor.fetchone()["total"] <= 1:
                    return jsonify(
                        code=409,
                        message="至少需要保留一名管理员。",
                        data=None,
                    ), 409
            cursor.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
        write_audit_log("更新角色", "用户", user_id, {"role": role})
        db.commit()
        if session.get("user_id") == user_id:
            session["role"] = role
        return jsonify(code=0, message="用户角色已更新。", data={"id": user_id, "role": role})

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
        try:
            response = app_module.get_es_client().search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query={"bool": {"filter": filters}},
                from_=0,
                size=100,
                track_total_hits=True,
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
            if not can_access_data_source(document.get("_source") or {}):
                return jsonify(code=403, message="无权审核该项目的数据。", data=None), 403
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

    @app.get("/api/data-items/<path:item_id>/quality-check")
    @login_required
    @role_required("超级管理员", "项目管理员", "任务负责人", "审核员")
    def quality_check_data_item(item_id: str):
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
            if not content.strip():
                warnings.append("数据内容为空。")
            elif len(content.strip()) < 3:
                warnings.append("数据内容过短，请确认是否完整。")
            if not isinstance(source.get("label"), str) or not source["label"].strip():
                warnings.append("尚未设置标注结果。")
            if isinstance(source.get("label"), str) and not source.get("labeled_by"):
                warnings.append("缺少标注人信息。")
            if content.strip():
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
