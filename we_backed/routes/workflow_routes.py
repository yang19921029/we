"""Issue tracking, in-app notifications, and quality-rule configuration."""

import app as app_module

from flask import jsonify
from flask import request
from flask import session

from app import (
    is_global_project_admin,
    login_required,
    role_required,
    user_can_access_project,
    write_audit_log,
)
from .notification_helpers import add_notification

MANAGER_ROLES = ("超级管理员", "项目管理员", "任务负责人", "审核员")
QUALITY_RULES = {
    "empty_content": "内容完整性",
    "min_length": "内容长度",
    "missing_label": "标注结果",
    "missing_annotator": "标注人信息",
    "duplicate_content": "数据集内重复内容",
}


def register_workflow_routes(app):
    @app.get("/api/issues")
    @login_required
    @role_required(*MANAGER_ROLES, "标注员")
    def list_issues():
        try:
            page = int(request.args.get("page", "1"))
            page_size = int(request.args.get("page_size", "20"))
        except ValueError:
            return jsonify(code=400, message="page 和 page_size 必须是整数。", data=None), 400
        if page < 1 or not 1 <= page_size <= 100:
            return jsonify(code=400, message="分页参数无效。", data=None), 400
        status_filter = request.args.get("status", "").strip()
        if status_filter and status_filter not in {"待处理", "处理中", "已解决", "已关闭"}:
            return jsonify(code=400, message="异常处理状态无效。", data=None), 400

        clauses = []
        params = []
        if session.get("role") == "标注员":
            clauses.append("reported_by = %s")
            params.append(session["username"])
        elif not is_global_project_admin():
            clauses.append(
                """
                EXISTS (
                    SELECT 1 FROM project_members pm
                    WHERE pm.project_id = annotation_issues.project_id
                        AND pm.user_id = %s
                )
                """
            )
            params.append(session["user_id"])
        if status_filter:
            clauses.append("status = %s")
            params.append(status_filter)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) AS total FROM annotation_issues {where_clause}",
                tuple(params),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"""
                SELECT id, item_id, dataset_id, project_id, issue_type, description,
                    reported_by, status, assignee, resolution, created_at, updated_at
                FROM annotation_issues {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, page_size, (page - 1) * page_size),
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return jsonify(
            code=0,
            message="ok",
            data={"items": rows, "total": total, "page": page, "page_size": page_size},
        )

    @app.patch("/api/issues/<int:issue_id>")
    @login_required
    @role_required(*MANAGER_ROLES)
    def update_issue(issue_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not payload:
            return jsonify(code=400, message="请求体必须是非空 JSON 对象。", data=None), 400
        if set(payload) - {"status", "assignee", "resolution"}:
            return jsonify(code=400, message="包含不支持的异常字段。", data=None), 400
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT project_id, item_id, reported_by, status FROM annotation_issues WHERE id = %s",
                (issue_id,),
            )
            issue = cursor.fetchone()
            if issue is None:
                return jsonify(code=404, message="异常记录不存在。", data=None), 404
            if not user_can_access_project(issue["project_id"]):
                return jsonify(code=403, message="无权处理该项目的异常记录。", data=None), 403

            updates = []
            values = []
            next_status = payload.get("status", issue["status"])
            if "status" in payload:
                if next_status not in {"待处理", "处理中", "已解决", "已关闭"}:
                    return jsonify(code=400, message="异常处理状态无效。", data=None), 400
                updates.append("status = %s")
                values.append(next_status)
            assignee = payload.get("assignee")
            if "assignee" in payload:
                if assignee is not None and (
                    not isinstance(assignee, str) or not assignee.strip()
                ):
                    return jsonify(code=400, message="处理人格式无效。", data=None), 400
                if assignee:
                    cursor.execute(
                        """
                        SELECT u.id FROM users u
                        JOIN project_members pm ON pm.user_id = u.id
                        WHERE u.username = %s AND u.is_active = 1
                            AND pm.project_id = %s
                        """,
                        (assignee.strip(), issue["project_id"]),
                    )
                    if cursor.fetchone() is None:
                        return jsonify(code=400, message="处理人必须是该项目有效成员。", data=None), 400
                updates.append("assignee = %s")
                values.append(assignee.strip() if assignee else None)
            resolution = payload.get("resolution")
            if "resolution" in payload:
                if not isinstance(resolution, str) or len(resolution.strip()) > 1000:
                    return jsonify(code=400, message="处理说明不能超过 1000 个字符。", data=None), 400
                if next_status == "已解决" and not resolution.strip() and not issue.get("resolution"):
                    return jsonify(code=400, message="标记为已解决时必须填写处理说明。", data=None), 400
                updates.append("resolution = %s")
                values.append(resolution.strip())
            elif "status" in payload and next_status == "已解决" and not issue.get("resolution"):
                return jsonify(code=400, message="标记为已解决时必须填写处理说明。", data=None), 400
            if not updates:
                return jsonify(code=400, message="没有可更新的异常字段。", data=None), 400
            values.append(issue_id)
            cursor.execute(
                f"UPDATE annotation_issues SET {', '.join(updates)} WHERE id = %s",
                tuple(values),
            )
            if next_status in {"已解决", "已关闭"}:
                add_notification(
                    cursor,
                    issue["reported_by"],
                    "异常反馈已处理",
                    f"数据 {issue['item_id']} 的反馈状态已更新为“{next_status}”。",
                    f"/data/detail/{issue['item_id']}",
                )
        write_audit_log("更新", "异常反馈", issue_id, payload)
        db.commit()
        return jsonify(code=0, message="异常反馈已更新。", data={"id": issue_id})

    @app.get("/api/quality-rules")
    @login_required
    @role_required(*MANAGER_ROLES)
    def get_quality_rules():
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT rule_key, name, enabled, threshold FROM quality_rules ORDER BY rule_key"
            )
            rules = [
                {
                    "key": row["rule_key"],
                    "name": row["name"],
                    "enabled": bool(row["enabled"]),
                    "threshold": row["threshold"],
                }
                for row in cursor.fetchall()
            ]
        return jsonify(code=0, message="ok", data=rules)

    @app.put("/api/quality-rules")
    @login_required
    @role_required("超级管理员", "项目管理员")
    def save_quality_rules():
        payload = request.get_json(silent=True)
        rules = payload.get("rules") if isinstance(payload, dict) else None
        if not isinstance(rules, list) or len(rules) != len(QUALITY_RULES):
            return jsonify(code=400, message="必须提交完整的质检规则列表。", data=None), 400
        by_key = {}
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("key") not in QUALITY_RULES:
                return jsonify(code=400, message="包含未知质检规则。", data=None), 400
            key = rule["key"]
            if key in by_key or not isinstance(rule.get("enabled"), bool):
                return jsonify(code=400, message="质检规则配置无效。", data=None), 400
            threshold = rule.get("threshold")
            if key == "min_length":
                if not isinstance(threshold, int) or isinstance(threshold, bool) or not 1 <= threshold <= 1000:
                    return jsonify(code=400, message="最小内容长度必须在 1 到 1000 之间。", data=None), 400
            elif threshold is not None:
                return jsonify(code=400, message="该规则不支持长度阈值。", data=None), 400
            by_key[key] = (rule["enabled"], threshold)
        if set(by_key) != set(QUALITY_RULES):
            return jsonify(code=400, message="必须提交完整的质检规则列表。", data=None), 400
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.executemany(
                "UPDATE quality_rules SET enabled = %s, threshold = %s WHERE rule_key = %s",
                [
                    (int(enabled), threshold, key)
                    for key, (enabled, threshold) in by_key.items()
                ],
            )
        write_audit_log("更新", "质检规则", "all", {"rules": rules})
        db.commit()
        return jsonify(code=0, message="质检规则已保存。", data=rules)

    @app.get("/api/notifications")
    @login_required
    def list_notifications():
        try:
            page = int(request.args.get("page", "1"))
            page_size = int(request.args.get("page_size", "20"))
        except ValueError:
            return jsonify(code=400, message="分页参数必须是整数。", data=None), 400
        if page < 1 or not 1 <= page_size <= 100:
            return jsonify(code=400, message="分页参数无效。", data=None), 400
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM notifications WHERE recipient = %s",
                (session["username"],),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                """
                SELECT id, title, body, link, is_read, created_at
                FROM notifications WHERE recipient = %s
                ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s
                """,
                (session["username"], page_size, (page - 1) * page_size),
            )
            items = [dict(row) for row in cursor.fetchall()]
        for item in items:
            item["is_read"] = bool(item["is_read"])
        return jsonify(
            code=0,
            message="ok",
            data={"items": items, "total": total, "page": page, "page_size": page_size},
        )

    @app.patch("/api/notifications/<int:notification_id>/read")
    @login_required
    def mark_notification_read(notification_id):
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE notifications SET is_read = 1 WHERE id = %s AND recipient = %s",
                (notification_id, session["username"]),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    "SELECT id FROM notifications WHERE id = %s AND recipient = %s",
                    (notification_id, session["username"]),
                )
                if cursor.fetchone() is None:
                    return jsonify(code=404, message="通知不存在。", data=None), 404
        db.commit()
        return jsonify(code=0, message="通知已读。", data={"id": notification_id})
