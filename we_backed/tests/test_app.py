from io import BytesIO
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch.exceptions import NotFoundError
from werkzeug.security import generate_password_hash

from app import create_app, request_ai_preannotation
from routes.project_routes import (
    DatasetImportError,
    _inspect_dataset_import_records,
    _iter_dataset_import_records,
    _validate_dataset_import_records,
)


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.result = None
        self.rowcount = 0
        self.lastrowid = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=()):
        self.database.last_query = query
        if "INSERT INTO active_sessions" in query:
            session_id, user_id, auth_version = params
            self.database.active_sessions[session_id] = {
                "session_id": session_id,
                "user_id": user_id,
                "auth_version": auth_version,
                "last_seen_at": datetime.now(timezone.utc).replace(tzinfo=None),
            }
            self.result = None
        elif "UPDATE active_sessions SET auth_version = %s" in query:
            auth_version, session_id, user_id = params
            active_session = self.database.active_sessions.get(session_id)
            if active_session and active_session["user_id"] == user_id:
                active_session["auth_version"] = auth_version
            self.result = None
        elif "UPDATE active_sessions SET auth_version = auth_version + 1" in query:
            session_id, user_id = params
            active_session = self.database.active_sessions.get(session_id)
            if active_session and active_session["user_id"] == user_id:
                active_session["auth_version"] += 1
            self.result = None
        elif "UPDATE active_sessions SET last_seen_at" in query:
            session_id, user_id = params
            active_session = self.database.active_sessions.get(session_id)
            if active_session and active_session["user_id"] == user_id:
                active_session["last_seen_at"] = datetime.now(
                    timezone.utc
                ).replace(tzinfo=None)
            self.result = None
        elif "DELETE FROM active_sessions" in query:
            if "WHERE session_id = %s" in query:
                self.database.active_sessions.pop(params[0], None)
            else:
                expiry = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                    minutes=5
                )
                self.database.active_sessions = {
                    session_id: active_session
                    for session_id, active_session
                    in self.database.active_sessions.items()
                    if active_session["last_seen_at"] >= expiry
                }
            self.result = None
        elif "COUNT(DISTINCT s.user_id)" in query:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            online_user_ids = {
                active_session["user_id"]
                for active_session in self.database.active_sessions.values()
                if active_session["last_seen_at"] >= now - timedelta(minutes=5)
                and active_session["user_id"] in self.database.users
                and self.database.users[active_session["user_id"]].get("is_active", 1)
                and active_session["auth_version"]
                == self.database.users[active_session["user_id"]].get(
                    "auth_version", 0
                )
            }
            self.result = {"total": len(online_user_ids)}
        elif "JOIN active_sessions s ON s.user_id" in query:
            session_id, user_id = params
            active_session = self.database.active_sessions.get(session_id)
            user = self.database.users.get(user_id)
            self.result = (
                dict(user)
                if active_session
                and user
                and active_session["user_id"] == user_id
                and active_session["auth_version"]
                == user.get("auth_version", 0)
                else None
            )
        elif "INSERT INTO account_verification_codes" in query:
            user_id, purpose, email, code_hash, expiry_minutes = params
            self.database.verification_codes[(user_id, purpose)] = {
                "user_id": user_id,
                "purpose": purpose,
                "email": email,
                "code_hash": code_hash,
                "expires_at": datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(minutes=expiry_minutes),
                "attempts": 0,
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
            }
            self.result = None
        elif "SELECT created_at FROM account_verification_codes" in query:
            self.result = self.database.verification_codes.get(
                (params[0], params[1])
            )
        elif "SELECT email, code_hash, expires_at, attempts" in query:
            self.result = self.database.verification_codes.get(
                (params[0], params[1])
            )
        elif "DELETE FROM account_verification_codes" in query:
            self.database.verification_codes.pop((params[0], params[1]), None)
            self.result = None
        elif "UPDATE account_verification_codes" in query:
            code_record = self.database.verification_codes.get(
                (params[0], params[1])
            )
            if code_record:
                code_record["attempts"] += 1
            self.result = None
        elif "UPDATE users SET password_hash = %s" in query:
            password_hash, user_id = params
            self.database.users[user_id]["password_hash"] = password_hash
            if "auth_version = auth_version + 1" in query:
                self.database.users[user_id]["auth_version"] += 1
            self.result = None
        elif "UPDATE users SET email = %s, email_verified_at" in query:
            email, user_id = params
            self.database.users[user_id]["email"] = email
            self.database.users[user_id]["email_verified_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None)
            self.result = None
        elif "INSERT INTO users" in query:
            username, password_hash, role = params
            user_id = max(self.database.users) + 1
            self.database.users[user_id] = {
                "id": user_id,
                "username": username,
                "password_hash": password_hash,
                "role": role,
                "is_active": 1,
                "email": None,
                "email_verified_at": None,
                "auth_version": 0,
            }
            self.lastrowid = user_id
            self.result = None
        elif "UPDATE users" in query:
            username, role, password_hash, is_active, *remaining = params
            user_id = remaining[-1]
            self.database.users[user_id].update(
                username=username,
                role=role,
                password_hash=password_hash,
                is_active=is_active,
            )
            if len(remaining) == 2:
                self.database.users[user_id]["auth_version"] += remaining[0]
            self.result = None
        elif "FROM users" in query:
            if "COUNT(*) AS total" in query:
                self.result = {
                    "total": sum(
                        user["role"] in {"超级管理员", "项目管理员"}
                        and user["is_active"]
                        for user in self.database.users.values()
                    )
                }
            elif "ORDER BY username" in query:
                self.result = sorted(
                    [dict(user) for user in self.database.users.values()],
                    key=lambda user: user["username"],
                )
            elif "WHERE username = %s AND id !=" in query:
                self.result = next(
                    (
                        {"id": user["id"]}
                        for user in self.database.users.values()
                        if user["username"] == params[0] and user["id"] != params[1]
                    ),
                    None,
                )
            elif "WHERE email = %s" in query:
                self.result = next(
                    (
                        {"id": user["id"]}
                        for user in self.database.users.values()
                        if user.get("email") == params[0]
                        and user["id"] != params[1]
                    ),
                    None,
                )
            elif "email_verified_at IS NOT NULL" in query:
                self.result = next(
                    (
                        dict(user)
                        for user in self.database.users.values()
                        if user["username"] == params[0]
                        and user.get("is_active", 1)
                        and user.get("email_verified_at")
                    ),
                    None,
                )
            elif "WHERE u.username = %s" in query:
                user = next(
                    (
                        user
                        for user in self.database.users.values()
                        if user["username"] == params[0] and user["is_active"]
                    ),
                    None,
                )
                self.result = (
                    {"id": user["id"]}
                    if user and params[1] in self.database.member_project_ids
                    else None
                )
            elif "WHERE username = %s" in query:
                self.result = next(
                    (
                        dict(user)
                        for user in self.database.users.values()
                        if user["username"] == params[0]
                    ),
                    None,
                )
            elif "WHERE id = %s" in query:
                self.result = next(
                    (
                        dict(user)
                        for user in self.database.users.values()
                        if user["id"] == params[0]
                    ),
                    None,
                )
            elif "WHERE id =" in query and params and params[0] == 7:
                self.result = dict(self.database.users[7])
            else:
                self.result = None
        elif "UPDATE annotation_tasks SET assignee" in query:
            assignee, task_id = params
            for task in self.database.tasks:
                if task.get("id") == task_id:
                    task["assignee"] = assignee
            self.result = None
        elif "UPDATE annotation_tasks SET status = %s WHERE id = %s" in query:
            status, task_id = params
            for task in self.database.tasks:
                if task.get("id") == task_id:
                    task["status"] = status
            self.rowcount = 1
            self.result = None
        elif "UPDATE annotation_tasks SET status = '已完成'" in query:
            task_id = params[0]
            for task in self.database.tasks:
                if task.get("id") == task_id:
                    task["status"] = "已完成"
            self.result = None
        elif "SELECT t.id, t.name, d.project_id" in query and "FROM annotation_tasks" in query:
            task_id = params[0]
            task = next(
                (task for task in self.database.tasks if task.get("id") == task_id),
                None,
            )
            self.result = (
                {
                    "id": task_id,
                    "name": task.get("name", f"任务 {task_id}"),
                    "project_id": self.database.dataset_projects.get(task.get("dataset_id", 1), 1),
                }
                if task
                else None
            )
        elif "SELECT t.status, d.project_id FROM annotation_tasks" in query:
            task_id = params[0]
            self.result = next(
                (dict(task) for task in self.database.tasks if task.get("id") == task_id),
                None,
            )
        elif "SELECT task_id" in query and "FROM task_items WHERE item_id" in query:
            self.result = [
                {
                    "task_id": item["task_id"],
                    "assignee": item.get("assignee"),
                }
                for item in self.database.task_items
                if item["item_id"] == params[0]
            ]
        elif "UPDATE task_items SET status = %s WHERE item_id = %s" in query:
            status, item_id = params
            for item in self.database.task_items:
                if item["item_id"] == item_id:
                    item["status"] = status
            self.result = None
        elif "SELECT COUNT(*) AS remaining" in query and "task_items" in query:
            task_id = params[0]
            self.result = {
                "remaining": sum(
                    item["task_id"] == task_id
                    and item["status"] not in {"已审核", "已跳过"}
                    for item in self.database.task_items
                )
            }
        elif "UPDATE task_items SET assignee" in query:
            assignee, task_id = params
            for item in self.database.task_items:
                if item["task_id"] == task_id:
                    item["assignee"] = assignee
            self.result = None
        elif "INSERT INTO annotation_issues" in query:
            item_id, dataset_id, project_id, issue_type, description, reported_by = params
            issue_id = len(self.database.issues) + 1
            self.database.issues.append(
                {
                    "id": issue_id,
                    "item_id": item_id,
                    "dataset_id": dataset_id,
                    "project_id": project_id,
                    "issue_type": issue_type,
                    "description": description,
                    "reported_by": reported_by,
                    "status": "待处理",
                    "assignee": None,
                    "resolution": "",
                    "created_at": "2026-10-30",
                    "updated_at": "2026-10-30",
                }
            )
            self.lastrowid = issue_id
            self.result = None
        elif "INSERT INTO notifications" in query:
            recipient, title, body, link = params
            notification_id = len(self.database.notifications) + 1
            self.database.notifications.append(
                {
                    "id": notification_id,
                    "recipient": recipient,
                    "title": title,
                    "body": body,
                    "link": link,
                    "is_read": 0,
                    "created_at": "2026-10-30",
                }
            )
            self.result = None
        elif "FROM quality_rules" in query and "SELECT rule_key" in query:
            self.result = [dict(rule) for rule in self.database.quality_rules]
        elif "UPDATE quality_rules SET enabled" in query:
            enabled, threshold, rule_key = params
            rule = next(rule for rule in self.database.quality_rules if rule["rule_key"] == rule_key)
            rule.update(enabled=enabled, threshold=threshold)
            self.result = None
        elif "FROM annotation_issues" in query:
            if "COUNT(*) AS total" in query:
                self.result = {"total": len(self.database.issues)}
            elif "WHERE id = %s" in query:
                self.result = next(
                    (dict(issue) for issue in self.database.issues if issue["id"] == params[0]),
                    None,
                )
            else:
                self.result = [dict(issue) for issue in self.database.issues]
        elif "UPDATE annotation_issues SET" in query:
            updates = query.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            fields = [part.split(" = ", 1)[0] for part in updates.split(", ")]
            issue = next(
                (issue for issue in self.database.issues if issue["id"] == params[-1]),
                None,
            )
            if issue:
                issue.update(dict(zip(fields, params[:-1])))
                self.rowcount = 1
            self.result = None
        elif "SELECT COUNT(*) AS total FROM notifications" in query:
            self.result = {
                "total": sum(
                    notification["recipient"] == params[0]
                    for notification in self.database.notifications
                )
            }
        elif "FROM notifications WHERE recipient" in query:
            recipient = params[0]
            self.result = [
                {key: value for key, value in notification.items() if key != "recipient"}
                for notification in self.database.notifications
                if notification["recipient"] == recipient
            ]
        elif "UPDATE notifications SET is_read" in query:
            notification_id, recipient = params
            matched = next(
                (
                    notification
                    for notification in self.database.notifications
                    if notification["id"] == notification_id
                    and notification["recipient"] == recipient
                ),
                None,
            )
            self.rowcount = int(matched is not None)
            if matched:
                matched["is_read"] = 1
            self.result = None
        elif "SELECT id FROM notifications WHERE id" in query:
            notification_id, recipient = params
            self.result = (
                {"id": notification_id}
                if any(
                    notification["id"] == notification_id
                    and notification["recipient"] == recipient
                    for notification in self.database.notifications
                )
                else None
            )
        elif "UPDATE datasets SET record_count = record_count +" in query:
            self.result = None
        elif "SELECT project_id FROM project_members" in query:
            self.result = [
                {"project_id": project_id}
                for project_id in self.database.member_project_ids
            ]
        elif "SELECT project_id FROM datasets WHERE id" in query:
            project_id = self.database.dataset_projects.get(params[0])
            self.result = {"project_id": project_id} if project_id else None
        elif "SELECT id FROM projects WHERE id" in query:
            self.result = {"id": params[0]} if params[0] in {1, 2} else None
        elif "SELECT t.dataset_id, t.label_schema_id" in query:
            self.result = {
                "id": params[0],
                "dataset_id": 1,
                "label_schema_id": 1,
                "project_id": 1,
                "status": "标注中",
                "assignee": "tester",
            }
        elif "FROM task_items" in query and "SELECT assignee" in query:
            self.result = {"assignee": "tester"}
        elif "FROM label_schemas" in query and "SELECT labels_json" in query:
            self.result = {
                "labels_json": json.dumps(
                    [{"code": "positive", "name": "正向"}],
                    ensure_ascii=False,
                )
            }
        elif "INSERT INTO audit_logs" in query:
            self.result = None
        elif "INSERT INTO project_members" in query:
            project_id, user_id, _added_by = params
            self.database.member_relations.add((project_id, user_id))
            if user_id == 7:
                self.database.member_project_ids.add(project_id)
            self.result = None
        elif "DELETE FROM project_members" in query:
            project_id, user_id = params
            self.rowcount = int(
                (project_id, user_id) in self.database.member_relations
                or (user_id == 7 and project_id in self.database.member_project_ids)
            )
            self.database.member_relations.discard((project_id, user_id))
            if user_id == 7:
                self.database.member_project_ids.discard(project_id)
            self.result = None
        elif "FROM organizations o" in query:
            self.result = (
                [{"id": 1, "name": "默认组织", "description": "默认组织"}]
                if 1 in self.database.member_project_ids
                else []
            )
        elif "FROM projects" in query:
            rows = [
                {
                    "id": 1,
                    "name": "默认项目",
                    "description": "默认项目",
                    "organization_id": 1,
                    "organization_name": "默认组织",
                },
                {
                    "id": 2,
                    "name": "受限项目",
                    "description": "受限项目",
                    "organization_id": 1,
                    "organization_name": "默认组织",
                },
            ]
            self.result = (
                [row for row in rows if row["id"] in self.database.member_project_ids]
                if "JOIN project_members" in query
                else rows
            )
        elif "FROM datasets d" in query:
            rows = [
                {
                    "id": dataset_id,
                    "name": "默认数据集" if dataset_id == 1 else "受限数据集",
                    "description": "数据集",
                    "record_count": 1,
                    "created_by": "system",
                    "created_at": "2026-10-30",
                    "project_id": project_id,
                    "project_name": "默认项目" if project_id == 1 else "受限项目",
                }
                for dataset_id, project_id in self.database.dataset_projects.items()
            ]
            self.result = (
                [row for row in rows if row["project_id"] in self.database.member_project_ids]
                if "JOIN project_members" in query
                else rows
            )
        elif "FROM annotation_tasks" in query and "overdue_tasks" in query:
            self.result = {"overdue_tasks": 0}
        elif "FROM annotation_tasks" in query and "COUNT(*) AS total" in query:
            self.result = {"total": len(self.database.tasks)}
        elif "FROM annotation_tasks" in query and "LIMIT %s OFFSET %s" in query:
            page_size, offset = params[-2:]
            self.result = [
                dict(task)
                for task in self.database.tasks[offset : offset + page_size]
            ]
        elif "FROM annotation_tasks" in query:
            self.result = [dict(task) for task in self.database.tasks]
        elif "FROM organizations" in query:
            self.result = [
                {"id": 1, "name": "默认组织", "description": "默认组织"}
            ]
        elif "FROM projects" in query:
            self.result = [
                {
                    "id": 1,
                    "name": "默认项目",
                    "description": "默认项目",
                    "organization_id": 1,
                    "organization_name": "默认组织",
                }
            ]
        elif "FROM datasets" in query:
            self.result = [
                {
                    "id": 1,
                    "name": "默认数据集",
                    "description": "默认数据集",
                    "record_count": 2,
                    "created_by": "system",
                    "created_at": "2026-10-30",
                    "project_id": 1,
                    "project_name": "默认项目",
                }
            ]
        elif "FROM menus" in query and "WHERE id =" in query:
            self.result = (
                {"id": params[0]}
                if params[0] in {1, 2, 3, 4, 5, 17, 22, 23, 24, 28}
                else None
            )
        elif "FROM menus AS parent" in query:
            menus = [
                (1, "首页", "/dashboard", None),
                (2, "数据标注", "/data/list", None),
                (3, "项目与任务管理", "/tasks/list", None),
                (4, "质量管理", "/operations", None),
                (5, "规范与帮助", "/policies", None),
                (17, "标签体系管理", "/labels", None),
                (22, "统计分析", "/analytics", None),
                (23, "数据交付与导出", "/data/export", None),
                (24, "人员与权限", "/users", None),
                (28, "系统设置", "/settings", None),
            ]
            allowed_paths = set(params)
            parent_ids = {
                parent_id
                for _, _, path, parent_id in self.database.menu_items
                if parent_id is not None and path in allowed_paths
            }
            self.result = [
                {"id": menu_id, "name": name, "path": path}
                for menu_id, name, path, _ in menus
                if menu_id in parent_ids
            ]
        elif "WHERE parent_id IS NULL" in query:
            self.result = [
                {"id": 1, "name": "首页", "path": "/dashboard"},
                {"id": 2, "name": "数据标注", "path": "/data/list"},
                {"id": 3, "name": "项目与任务管理", "path": "/tasks/list"},
                {"id": 4, "name": "质量管理", "path": "/operations"},
                {"id": 5, "name": "规范与帮助", "path": "/policies"},
                {"id": 17, "name": "标签体系管理", "path": "/labels"},
                {"id": 22, "name": "统计分析", "path": "/analytics"},
                {"id": 23, "name": "数据交付与导出", "path": "/data/export"},
                {"id": 24, "name": "人员与权限", "path": "/users"},
                {"id": 28, "name": "系统设置", "path": "/settings"},
            ]
        elif "WHERE parent_id =" in query:
            menu_names = {
                6: "标注工作台",
                7: "数据展示列表",
                8: "数据打标",
                9: "数据集管理",
                31: "组织与项目",
                20: "任务列表",
                21: "任务分配",
                12: "质检任务",
                13: "质检规则",
                14: "质检报告",
                15: "标注规范",
                16: "操作指南",
                18: "标签体系",
                19: "版本历史",
                25: "统计看板",
                26: "数据导出",
                27: "用户与角色",
                29: "平台设置",
                30: "操作日志",
            }
            rows = [
                {
                    "id": menu_id,
                    "name": menu_names[menu_id],
                    "path": path,
                    "parent_id": parent_id,
                }
                for menu_id, _, path, parent_id in self.database.menu_items
                if parent_id == params[0]
            ]
            if len(params) > 1:
                allowed_paths = set(params[1:])
                rows = [row for row in rows if row["path"] in allowed_paths]
            self.result = rows
        else:
            raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def executemany(self, query, rows):
        for params in rows:
            self.execute(query, params)


class FakeDatabase:
    def __init__(self):
        self.member_project_ids = set()
        self.member_relations = set()
        self.tasks = []
        self.task_items = []
        self.issues = []
        self.notifications = []
        self.quality_rules = [
            {"rule_key": "empty_content", "name": "内容完整性", "enabled": 1, "threshold": None},
            {"rule_key": "min_length", "name": "内容长度", "enabled": 1, "threshold": 3},
            {"rule_key": "missing_label", "name": "标注结果", "enabled": 1, "threshold": None},
            {"rule_key": "missing_annotator", "name": "标注人信息", "enabled": 1, "threshold": None},
            {"rule_key": "duplicate_content", "name": "数据集内重复内容", "enabled": 1, "threshold": None},
        ]
        self.dataset_projects = {1: 1, 2: 2}
        self.users = {
            7: {
                "id": 7,
                "username": "tester",
                "password_hash": generate_password_hash("correct-password"),
                "role": "项目管理员",
                "is_active": 1,
                "email": None,
                "email_verified_at": None,
                "auth_version": 0,
            }
        }
        self.verification_codes = {}
        self.active_sessions = {}
        self.last_query = ""
        self.menu_items = [
            (6, "标注工作台", "/dashboard", 1),
            (7, "数据展示列表", "/data/list", 2),
            (8, "数据打标", "/data/label", 2),
            (9, "数据集管理", "/datasets", 2),
            (31, "组织与项目", "/projects", 3),
            (20, "任务列表", "/tasks/list", 3),
            (21, "任务分配", "/tasks/assign", 3),
            (12, "质检任务", "/operations/reports", 4),
            (13, "质检规则", "/operations/security", 4),
            (14, "质检报告", "/operations/complaints", 4),
            (15, "标注规范", "/policies/documents", 5),
            (16, "操作指南", "/policies/guides", 5),
            (18, "标签体系", "/labels", 17),
            (19, "版本历史", "/labels/versions", 17),
            (25, "统计看板", "/analytics", 22),
            (26, "数据导出", "/data/export", 23),
            (27, "用户与角色", "/users", 24),
            (29, "平台设置", "/settings", 28),
            (30, "操作日志", "/audit-logs", 28),
        ]

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        return None


class FakeIndices:
    def __init__(self):
        self.created = False
        self.mapping = None
        self.settings = None
        self.put_mapping_properties = None
        self.refresh_calls = []

    def exists(self, *, index):
        return self.created

    def create(self, *, index, mappings, settings):
        self.created = True
        self.mapping = mappings
        self.settings = settings

    def put_settings(self, *, index, settings):
        self.settings = settings

    def put_mapping(self, *, index, properties):
        self.put_mapping_properties = properties

    def refresh(self, *, index):
        self.refresh_calls.append(index)


class FakeElastic:
    def __init__(self):
        self.indices = FakeIndices()
        self.items = {
            "doc-1": {
                "order_id": 55,
                "order_date": "2026-10-28T08:30:00Z",
                "customer_full_name": "测试用户",
                "products": [{"product_name": "示例商品"}],
                "label": None,
                "labeled_by": None,
            },
            "doc-2": {
                "order_id": 56,
                "order_date": "2026-10-28T09:30:00Z",
                "customer_full_name": "另一位用户",
                "products": [{"product_name": "另一件商品"}],
                "label": "中性",
                "labeled_by": "seed",
                "updated_at": "2026-10-29T10:00:00Z",
            },
        }
        self.indexed_documents = []
        self.search_queries = []
        self.search_sorts = []
        self.scroll_hits = {}
        self.next_scroll_id = 1
        self.bulk_requests = []
        self.pit_counter = 0
        self.search_requests = []
        self.review_search_requests = []

    def open_point_in_time(self, *, index, keep_alive):
        self.pit_counter += 1
        return {"id": f"pit-{self.pit_counter}"}

    def search(
        self,
        *,
        index=None,
        query,
        from_=None,
        size=10,
        track_total_hits=True,
        sort=None,
        aggregations=None,
        scroll=None,
        pit=None,
        search_after=None,
    ):
        self.review_search_requests.append(
            {
                "query": query,
                "from_": from_,
                "size": size,
                "sort": sort,
            }
        )
        self.search_requests.append(
            {
                "index": index,
                "from_": from_,
                "pit": pit,
                "search_after": search_after,
                "sort": sort,
            }
        )
        self.search_queries.append(query)
        self.search_sorts.append(sort)
        if scroll is not None:
            item_ids = list(self.items)
            selected_ids = item_ids[:size]
            scroll_id = f"scroll-{self.next_scroll_id}"
            self.next_scroll_id += 1
            self.scroll_hits[scroll_id] = item_ids[size:]
            return {
                "_scroll_id": scroll_id,
                "hits": {
                    "total": {"value": len(item_ids), "relation": "eq"},
                    "hits": [
                        {"_id": item_id, "_source": self.items[item_id]}
                        for item_id in selected_ids
                    ],
                },
            }
        item_ids = list(self.items)
        if query.get("bool", {}).get("filter"):
            filter_query = query["bool"]["filter"][0]
            if "should" in filter_query.get("bool", {}) and any(
                "term" in clause
                and ("label" in clause["term"] or "label.keyword" in clause["term"])
                for clause in filter_query["bool"]["should"]
            ):
                clauses = filter_query["bool"]["should"]
                label_term = next(
                    clause["term"].get("label", clause["term"].get("label.keyword"))
                    for clause in clauses
                    if "term" in clause
                    and ("label" in clause["term"] or "label.keyword" in clause["term"])
                )
                item_ids = [
                    item_id
                    for item_id in item_ids
                    if self.items[item_id].get("label") == label_term
                ]
            elif "exists" in filter_query:
                item_ids = [
                    item_id
                    for item_id in item_ids
                    if self.items[item_id].get("label") is not None
                ]
            else:
                item_ids = [
                    item_id
                    for item_id in item_ids
                    if self.items[item_id].get("label") is None
                ]
        start = from_
        if search_after is not None:
            start = int(search_after[0]) + 1
        start = start or 0
        selected_ids = item_ids[start : start + size]
        selected_hits = [
            {
                "_id": item_id,
                "_source": self.items[item_id],
                **(
                    {"sort": [start + offset]}
                    if pit is not None
                    else {}
                ),
            }
            for offset, item_id in enumerate(selected_ids)
        ]
        response = {
            "hits": {
                "total": {"value": len(item_ids), "relation": "eq"},
                "hits": selected_hits,
            }
        }
        if pit is not None:
            response["pit_id"] = pit["id"]
        if aggregations is not None:
            response["aggregations"] = {
                name: {"buckets": []} for name in aggregations
            }
        return response

    def scroll(self, *, scroll_id, scroll):
        item_ids = self.scroll_hits.get(scroll_id, [])
        selected_ids = item_ids[:1000]
        self.scroll_hits[scroll_id] = item_ids[1000:]
        return {
            "_scroll_id": scroll_id,
            "hits": {
                "hits": [
                    {"_id": item_id, "_source": self.items[item_id]}
                    for item_id in selected_ids
                ],
            },
        }

    def clear_scroll(self, *, scroll_id):
        self.scroll_hits.pop(scroll_id, None)

    def close(self):
        return None

    def get(self, *, index, id):
        if id not in self.items:
            raise self.missing_document()
        return {"_id": id, "_source": self.items[id]}

    def update(self, *, index, id, script, doc_as_upsert, refresh):
        if id not in self.items:
            raise self.missing_document()
        params = script["params"]
        if "entry" in params:
            entry = params["entry"]
            if (
                not entry.get("annotation_present")
                or self.items[id].get("label") != entry["label"]
            ):
                self.items[id].setdefault("label_history", []).append(entry)
            if entry.get("annotation_present"):
                self.items[id].setdefault("annotation_history", []).append(
                    {
                        "annotation": entry["annotation"],
                        "changed_by": entry["labeled_by"],
                        "changed_at": entry["labeled_at"],
                    }
                )
                self.items[id]["annotation"] = entry["annotation"]
            if entry["label"] is None:
                self.items[id].pop("label", None)
                self.items[id].pop("labeled_by", None)
                self.items[id].pop("labeled_at", None)
            else:
                self.items[id].update(
                    {
                        "label": entry["label"],
                        "labeled_by": entry["labeled_by"],
                        "labeled_at": entry["labeled_at"],
                    }
                )
            self.items[id]["updated_at"] = entry["labeled_at"]
        elif "report" in params:
            self.items[id].setdefault("issue_reports", []).append(params["report"])
        elif "decision" in params:
            entry = {
                "decision": params["decision"],
                "reviewer": params["reviewer"],
                "note": params["note"],
                "reviewed_at": params["reviewed_at"],
            }
            self.items[id].setdefault("review_history", []).append(entry)
            self.items[id].update(
                {
                    "review_status": params["decision"],
                    "reviewed_by": params["reviewer"],
                    "review_note": params["note"],
                    "reviewed_at": params["reviewed_at"],
                }
            )

    def index(self, *, index, id, document, refresh):
        self.items[id] = document
        self.indexed_documents.append(id)

    def bulk(self, *, operations, refresh):
        self.bulk_requests.append((operations.copy(), refresh))
        results = []
        for action, document in zip(operations[::2], operations[1::2]):
            operation, metadata = next(iter(action.items()))
            item_id = metadata["_id"]
            if operation == "create" and item_id in self.items:
                results.append(
                    {"create": {"_id": item_id, "status": 409, "error": {}}}
                )
                continue
            self.items[item_id] = document
            self.indexed_documents.append(item_id)
            results.append({operation: {"_id": item_id, "status": 201}})
        return {"errors": False, "items": results}

    @staticmethod
    def missing_document():
        return NotFoundError(
            "document missing",
            ApiResponseMeta(
                status=404,
                http_version="1.1",
                headers=HttpHeaders(),
                duration=0,
                node=NodeConfig(scheme="http", host="localhost", port=9200),
            ),
            {"error": {"type": "document_missing_exception"}},
        )


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
            }
        )
        self.client = self.app.test_client()
        self.database = FakeDatabase()
        self.elastic = FakeElastic()
        self.db_patcher = patch("app.get_db", return_value=self.database)
        self.es_patcher = patch("app.get_es_client", return_value=self.elastic)
        self.es_factory_patcher = patch(
            "app.create_es_client", return_value=self.elastic
        )
        self.db_patcher.start()
        self.es_patcher.start()
        self.es_factory_patcher.start()

    def tearDown(self):
        self.db_patcher.stop()
        self.es_patcher.stop()
        self.es_factory_patcher.stop()

    def test_dataset_import_streams_supported_file_formats(self):
        examples = (
            ("records.csv", b"id,text\n1,first\n2,second\n", 2),
            ("records.json", b'[{"id":1},{"id":2}]', 2),
            ("records.json", b'\xef\xbb\xbf[{"id":1}]', 1),
            ("records.json", b'{"items":[{"id":1},{"id":2}]}', 2),
            ("record.json", b'{"id":1}', 1),
            ("records.jsonl", b'{"id":1}\n{"id":2}\n', 2),
        )
        for filename, contents, record_count in examples:
            with self.subTest(filename=filename, contents=contents):
                upload = type(
                    "Upload",
                    (),
                    {"stream": BytesIO(contents)},
                )()
                records = list(_iter_dataset_import_records(upload, filename))
                self.assertEqual(len(records), record_count)
                self.assertTrue(all(isinstance(record, dict) for record in records))

    def test_dataset_import_accepts_more_than_5000_records(self):
        contents = b"\n".join(b'{"id":1}' for _ in range(5001))
        upload = type("Upload", (), {"stream": BytesIO(contents)})()
        self.assertEqual(
            _validate_dataset_import_records(upload, "records.jsonl"),
            5001,
        )

    def test_dataset_import_rejects_file_over_configured_limit(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        with patch("routes.project_routes.MAX_IMPORT_FILE_BYTES", 10):
            response = self.client.post(
                "/api/datasets/2/import",
                data={"file": (BytesIO(b"01234567890"), "records.jsonl")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 413)
        self.assertIn("1 GB（1024 MB）", response.json["message"])

    def test_dataset_import_returns_json_when_request_body_exceeds_limit(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        with patch("routes.project_routes.MAX_IMPORT_FILE_BYTES", 10):
            response = self.client.post(
                "/api/datasets/2/import",
                data={"file": (BytesIO(b'{"id":1}'), "records.json")},
                content_type="multipart/form-data",
                environ_overrides={
                    "CONTENT_LENGTH": str(10 + 1024 * 1024 + 1),
                },
            )
        self.assertEqual(response.status_code, 413)
        self.assertIn("导入请求过大", response.json["message"])

    def test_dataset_import_streams_and_indexes_records(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        with self.client.session_transaction() as session:
            session["role"] = "超级管理员"
        response = self.client.post(
            "/api/datasets/2/import",
            data={
                "file": (
                    BytesIO(b'{"id":1}\n{"id":2}\n'),
                    "records.jsonl",
                )
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["imported_count"], 2)
        self.assertEqual(len(self.elastic.indexed_documents), 2)
        self.assertEqual(len(self.elastic.bulk_requests), 1)
        self.assertFalse(self.elastic.bulk_requests[0][1])
        self.assertEqual(self.elastic.indices.refresh_calls, ["data_items"])
        repeated = self.client.post(
            "/api/datasets/2/import",
            data={
                "file": (
                    BytesIO(b'{"id":1}\n{"id":2}\n'),
                    "records.jsonl",
                )
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json["data"]["imported_count"], 0)
        self.assertEqual(repeated.json["data"]["skipped_duplicate_count"], 2)
        self.assertEqual(len(self.elastic.indexed_documents), 2)

    def test_dataset_import_preflight_returns_schema_and_sample_without_indexing(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        response = self.client.post(
            "/api/datasets/2/import",
            data={
                "file": (
                    BytesIO(b'{"id":1,"text":"first"}\n{"id":2,"text":"second"}\n'),
                    "records.jsonl",
                ),
                "preview_only": "true",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["record_count"], 2)
        self.assertEqual(response.json["data"]["fields"], ["id", "text"])
        self.assertEqual(len(response.json["data"]["preview"]), 2)
        self.assertEqual(self.elastic.bulk_requests, [])
        self.assertEqual(self.elastic.indexed_documents, [])

    def test_dataset_import_retry_uses_stable_ids_for_rows_without_source_id(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        content = b"id,text\n1,first\n"
        first = self.client.post(
            "/api/datasets/2/import",
            data={"file": (BytesIO(content), "records.csv")},
            content_type="multipart/form-data",
        )
        second = self.client.post(
            "/api/datasets/2/import",
            data={"file": (BytesIO(content), "records.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["data"]["imported_count"], 1)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json["data"]["imported_count"], 0)
        self.assertEqual(second.json["data"]["skipped_duplicate_count"], 1)
        self.assertEqual(len(self.elastic.indexed_documents), 1)

    def test_dataset_import_endpoint_accepts_more_than_5000_records(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        with self.client.session_transaction() as session:
            session["role"] = "超级管理员"
        contents = b"\n".join(
            json.dumps({"source_id": f"record-{index}"}).encode()
            for index in range(5001)
        )
        response = self.client.post(
            "/api/datasets/2/import",
            data={"file": (BytesIO(contents), "records.jsonl")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["imported_count"], 5001)
        self.assertEqual(len(self.elastic.indexed_documents), 5001)
        self.assertEqual(len(self.elastic.bulk_requests), 51)
        self.assertTrue(
            all(len(operations) <= 200 for operations, _ in self.elastic.bulk_requests)
        )

    def test_task_creation_reports_invalid_configuration_field(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        response = self.client.post(
            "/api/tasks",
            json={
                "name": "test task",
                "dataset_id": "1",
                "label_schema_id": 1,
                "assignee": "tester",
                "priority": "中",
                "instructions": "",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json["message"], "请选择有效的数据集。")

    def test_tasks_can_be_assigned_in_a_validated_batch(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.database.tasks = [
            {"id": 31, "name": "任务 A", "dataset_id": 1, "assignee": "old"},
            {"id": 32, "name": "任务 B", "dataset_id": 1, "assignee": "old"},
        ]
        self.database.member_project_ids.add(1)
        invalid = self.client.post(
            "/api/tasks/batch-assign",
            json={"task_ids": [31, 31], "assignee": "tester"},
        )
        self.assertEqual(invalid.status_code, 400)

        result = self.client.post(
            "/api/tasks/batch-assign",
            json={"task_ids": [31, 32], "assignee": "tester"},
        )
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual([task["assignee"] for task in self.database.tasks], ["tester", "tester"])
        self.assertEqual(len(self.database.notifications), 2)

    def test_login_rejects_invalid_password(self):
        response = self.client.post(
            "/api/login",
            json={"username": "tester", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

    def test_change_current_password_requires_correct_current_password(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        rejected = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "wrong-password",
                "new_password": "new-password",
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.json["message"], "当前密码不正确。")

        updated = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "correct-password",
                "new_password": "new-password",
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/login",
                json={"username": "tester", "password": "new-password"},
            ).status_code,
            200,
        )

    def test_recovery_email_must_be_verified_before_password_reset(self):
        response = self.client.post(
            "/api/auth/forgot-password/send-code",
            json={"username": "tester"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.database.verification_codes, {})

    def test_recovery_email_send_fails_explicitly_without_smtp_configuration(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        response = self.client.post(
            "/api/auth/recovery-email/send-code",
            json={"email": "tester@example.test"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("邮件服务配置", response.json["message"])
        self.assertEqual(self.database.verification_codes, {})

    def test_email_verification_and_forgot_password_code_flow(self):
        self.app.config.update(
            SMTP_HOST="smtp.example.test",
            SMTP_SENDER="noreply@example.test",
        )
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        issued_codes = []
        with patch(
            "routes.auth_routes._send_verification_email",
            side_effect=lambda _recipient, code, purpose: issued_codes.append(
                (code, purpose)
            ),
        ):
            sent = self.client.post(
                "/api/auth/recovery-email/send-code",
                json={"email": "Tester@example.test"},
            )
            self.assertEqual(sent.status_code, 200)
            email_code, purpose = issued_codes.pop()
            self.assertEqual(purpose, "bind_email")
            verified = self.client.post(
                "/api/auth/recovery-email/verify",
                json={"email": "tester@example.test", "code": email_code},
            )
            self.assertEqual(verified.status_code, 200)
            self.assertEqual(
                self.client.get("/api/auth/recovery-email").json["data"],
                {"email": "t***@example.test", "verified": True},
            )

            previous_session = self.app.test_client()
            previous_session.post(
                "/api/login",
                json={"username": "tester", "password": "correct-password"},
            )
            self.client.post("/api/logout")
            self.assertEqual(
                self.client.post(
                    "/api/auth/forgot-password/send-code",
                    json={"username": "tester"},
                ).status_code,
                200,
            )
            reset_code, purpose = issued_codes.pop()
            self.assertEqual(purpose, "reset_password")
            invalid = self.client.post(
                "/api/auth/forgot-password/reset",
                json={
                    "username": "tester",
                    "code": "000000" if reset_code != "000000" else "000001",
                    "new_password": "forgotten-password",
                },
            )
            self.assertEqual(invalid.status_code, 400)
            reset = self.client.post(
                "/api/auth/forgot-password/reset",
                json={
                    "username": "tester",
                    "code": reset_code,
                    "new_password": "forgotten-password",
                },
            )
            self.assertEqual(reset.status_code, 200)
            reused_code = self.client.post(
                "/api/auth/forgot-password/reset",
                json={
                    "username": "tester",
                    "code": reset_code,
                    "new_password": "another-password",
                },
            )
            self.assertEqual(reused_code.status_code, 400)
            self.assertEqual(previous_session.get("/api/auth/me").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/login",
                json={"username": "tester", "password": "forgotten-password"},
            ).status_code,
            200,
        )

    def test_login_and_read_first_and_second_level_menus(self):
        response = self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["username"], "tester")

        first_level = self.client.get("/api/menus")
        self.assertEqual(first_level.status_code, 200)
        self.assertEqual(
            [menu["name"] for menu in first_level.json["data"]],
            [
                "首页",
                "数据标注",
                "项目与任务管理",
                "质量管理",
                "规范与帮助",
                "标签体系管理",
                "统计分析",
                "数据交付与导出",
                "人员与权限",
                "系统设置",
            ],
        )

        second_level = self.client.get("/api/menus/2/children")
        self.assertEqual(second_level.status_code, 200)
        self.assertEqual(
            [menu["name"] for menu in second_level.json["data"]],
            ["数据展示列表", "数据打标", "数据集管理"],
        )
        self.assertEqual(
            [menu["path"] for menu in second_level.json["data"]],
            ["/data/list", "/data/label", "/datasets"],
        )

    def test_role_menu_endpoints_only_return_permitted_menus(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        role_expectations = {
            "任务负责人": (
                ["首页", "数据标注", "项目与任务管理", "规范与帮助", "标签体系管理"],
                2,
                ["/data/list", "/data/label", "/datasets"],
            ),
            "标注员": (
                ["首页", "数据标注", "规范与帮助"],
                2,
                ["/data/label"],
            ),
            "审核员": (
                ["首页", "质量管理", "规范与帮助"],
                4,
                ["/operations/reports", "/operations/complaints"],
            ),
            "数据分析员": (
                ["首页", "数据标注", "规范与帮助", "统计分析", "数据交付与导出"],
                2,
                ["/data/list"],
            ),
        }
        for role, (expected_sections, parent_id, expected_paths) in role_expectations.items():
            with self.subTest(role=role):
                self.database.users[7]["role"] = role
                first_level = self.client.get("/api/menus")
                self.assertEqual(
                    [menu["name"] for menu in first_level.json["data"]],
                    expected_sections,
                )
                self.assertIn("EXISTS", self.database.last_query)
                self.assertNotIn("DISTINCT", self.database.last_query)
                children = self.client.get(f"/api/menus/{parent_id}/children")
                self.assertEqual(
                    [menu["path"] for menu in children.json["data"]],
                    expected_paths,
                )
                unauthorized = 4 if role == "标注员" else 24
                self.assertEqual(
                    self.client.get(f"/api/menus/{unauthorized}/children").json["data"],
                    [],
                )

    def test_menu_endpoints_require_login(self):
        response = self.client.get("/api/menus")
        self.assertEqual(response.status_code, 401)

    def test_platform_routes_validate_configuration_and_enforce_roles(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.assertEqual(
            self.client.post("/api/datasets", json={"name": "  "}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/label-schemas",
                json={
                    "name": "bad",
                    "labels": [{"code": "same", "name": "A"}, {"code": "same", "name": "B"}],
                },
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/tasks",
                json={"name": "invalid", "dataset_id": "not-an-id"},
            ).status_code,
            400,
        )
        with self.client.session_transaction() as session:
            self.database.users[7]["role"] = "标注员"
            session["role"] = "标注员"
        self.assertEqual(self.client.get("/api/stats").status_code, 403)
        self.assertEqual(
            self.client.patch("/api/users/7/role", json={"role": "审核员"}).status_code,
            403,
        )

    def test_multimodal_annotation_validates_and_persists(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        invalid = self.client.put(
            "/api/data-items/doc-1/label",
            json={
                "label": "正向",
                "annotation": {
                    "items": [
                        {
                            "kind": "keypoint",
                            "label": "目标",
                            "media_url": "/media/image.png",
                            "points": [{"x": 101, "y": 50}],
                        }
                    ]
                },
            },
        )
        self.assertEqual(invalid.status_code, 400)

        annotation = {
            "items": [
                {
                    "kind": "bbox",
                    "label": "目标",
                    "media_url": "/media/image.png",
                    "points": [{"x": 10, "y": 20}, {"x": 60, "y": 80}],
                },
                {
                    "kind": "segment",
                    "label": "语音",
                    "media_url": "/media/audio.mp3",
                    "start": 1.25,
                    "end": 2.5,
                },
            ]
        }
        response = self.client.put(
            "/api/data-items/doc-1/label",
            json={"label": "正向", "annotation": annotation},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["annotation"], annotation)
        self.assertEqual(self.elastic.items["doc-1"]["annotation"], annotation)

    def test_project_hierarchy_endpoints_return_default_scope(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        organizations = self.client.get("/api/organizations")
        projects = self.client.get("/api/projects")
        datasets = self.client.get("/api/datasets")
        self.assertEqual(organizations.status_code, 200)
        self.assertEqual(projects.json["data"][0]["organization_name"], "默认组织")
        self.assertEqual(datasets.json["data"][0]["project_name"], "默认项目")

    def test_statistics_support_project_scope_and_sla_count(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        response = self.client.get("/api/stats?project_id=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["overdue_tasks"], 0)

    def test_project_membership_limits_project_and_data_access(self):
        self.elastic.items["doc-3"] = {
            "dataset_id": 2,
            "content": "受限项目的机密数据",
        }
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        with self.client.session_transaction() as session:
            self.database.users[7]["role"] = "标注员"
            session["role"] = "标注员"
        self.assertEqual(self.client.get("/api/projects").json["data"], [])
        self.assertEqual(self.client.get("/api/datasets").json["data"], [])
        self.assertEqual(self.client.get("/api/organizations").json["data"], [])
        self.assertEqual(
            self.client.get("/api/data-items/doc-3").status_code,
            403,
        )

        self.database.member_project_ids.add(1)
        self.assertEqual(
            [project["id"] for project in self.client.get("/api/projects").json["data"]],
            [1],
        )
        self.assertEqual(
            [dataset["id"] for dataset in self.client.get("/api/datasets").json["data"]],
            [1],
        )
        self.assertEqual(
            [organization["id"] for organization in self.client.get("/api/organizations").json["data"]],
            [1],
        )
        self.assertEqual(self.client.get("/api/data-items/doc-1").status_code, 200)
        self.assertEqual(self.client.get("/api/data-items/doc-3").status_code, 403)
        with self.client.session_transaction() as session:
            self.database.users[7]["role"] = "数据分析员"
            session["role"] = "数据分析员"
        self.assertEqual(
            self.client.get("/api/stats?project_id=2").status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/data-items/export?dataset_id=2").status_code,
            403,
        )

    def test_project_members_can_be_added_and_removed(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )

        added = self.client.post(
            "/api/projects/1/members",
            json={"user_id": 7},
        )
        self.assertEqual(added.status_code, 201)
        self.assertIn(1, self.database.member_project_ids)

        removed = self.client.delete("/api/projects/1/members/7")
        self.assertEqual(removed.status_code, 200)
        self.assertNotIn(1, self.database.member_project_ids)

    def test_ai_preannotation_uses_configured_model_and_validates_output(self):
        provider_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "label": "正向",
                                "confidence": 0.94,
                                "reason": "表达积极态度",
                            }
                        )
                    }
                }
            ]
        }
        with self.app.app_context():
            self.app.config.update(
                AI_ENABLED=True,
                AI_API_KEY="test-key",
                AI_MODEL="deepseek-chat",
            )
            with patch("app.urlopen") as open_url:
                open_url.return_value.__enter__.return_value.read.return_value = (
                    json.dumps(provider_response).encode("utf-8")
                )
                result = request_ai_preannotation("经过脱敏的内容", ["正向", "负向"])
        self.assertEqual(result["label"], "正向")
        self.assertEqual(result["model"], "deepseek-chat")
        outbound_request = open_url.call_args.args[0]
        self.assertEqual(outbound_request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertIn("Bearer test-key", outbound_request.get_header("Authorization"))

    def test_ai_preannotation_masks_sensitive_text_before_external_request(self):
        self.database.member_project_ids.add(1)
        self.elastic.items["doc-1"].update(
            {
                "dataset_id": 1,
                "content": "Contact 13812345678 or person@example.com",
            }
        )
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        with self.client.session_transaction() as session:
            self.database.users[7]["role"] = "标注员"
            session["role"] = "标注员"
        self.app.config.update(
            AI_ENABLED=True,
            AI_API_KEY="test-key",
            AI_MODEL="deepseek-chat",
        )
        provider_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "label": "正向",
                                "confidence": 0.9,
                                "reason": "模型建议",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        with patch("app.urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = (
                json.dumps(provider_response, ensure_ascii=False).encode("utf-8")
            )
            response = self.client.post(
                "/api/data-items/doc-1/pre-annotate",
                json={"task_id": 9},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["label"], "正向")
        outbound_request = open_url.call_args.args[0]
        request_body = json.loads(outbound_request.data)
        user_message = json.loads(request_body["messages"][1]["content"])
        self.assertEqual(
            user_message["untrusted_content"],
            "Contact 138****5678 or p***@example.com",
        )
        self.assertNotIn("13812345678", outbound_request.data.decode("utf-8"))
        self.assertNotIn("person@example.com", outbound_request.data.decode("utf-8"))
        self.assertIsNone(self.elastic.items["doc-1"].get("label"))

    def test_quality_duplicate_search_is_limited_to_the_same_dataset(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.elastic.items["doc-1"].update(
            {"dataset_id": 1, "content": "需要检查的文本"}
        )

        response = self.client.get("/api/data-items/doc-1/quality-check")

        self.assertEqual(response.status_code, 200)
        duplicate_query = self.elastic.search_queries[-1]
        self.assertIn(
            {"term": {"dataset_id": 1}},
            duplicate_query["bool"]["filter"],
        )

    def test_data_responses_mask_common_sensitive_values(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.elastic.items["doc-1"]["content"] = (
            "联系电话 13812345678，邮箱 person@example.com"
        )
        response = self.client.get("/api/data-items/doc-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("138****5678", response.json["data"]["content"])
        self.assertIn("p***@example.com", response.json["data"]["content"])

    def test_current_user_and_logout_use_session(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        current_user = self.client.get("/api/auth/me")
        self.assertEqual(current_user.status_code, 200)
        self.assertEqual(current_user.json["data"]["username"], "tester")

        logout = self.client.post("/api/logout")
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/menus").status_code, 401)

    def test_online_presence_counts_distinct_recent_logged_in_accounts(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        another_session = self.app.test_client()
        another_session.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.assertEqual(
            self.client.post("/api/auth/presence").json["data"]["online_users"],
            1,
        )

        created = self.client.post(
            "/api/users",
            json={
                "username": "second-user",
                "password": "initial-password",
                "role": "标注员",
            },
        )
        second_user = self.app.test_client()
        second_user.post(
            "/api/login",
            json={
                "username": "second-user",
                "password": "initial-password",
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            self.client.post("/api/auth/presence").json["data"]["online_users"],
            2,
        )
        second_user.post("/api/logout")
        self.assertEqual(
            self.client.post("/api/auth/presence").json["data"]["online_users"],
            1,
        )

    def test_user_management_creates_edits_and_disables_accounts(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        created = self.client.post(
            "/api/users",
            json={
                "username": "new-annotator",
                "password": "initial-password",
                "role": "项目管理员",
            },
        )
        self.assertEqual(created.status_code, 201)
        user_id = created.json["data"]["id"]
        self.assertTrue(created.json["data"]["is_active"])

        user_client = self.app.test_client()
        login = user_client.post(
            "/api/login",
            json={"username": "new-annotator", "password": "initial-password"},
        )
        self.assertEqual(login.status_code, 200)

        updated = self.client.patch(
            f"/api/users/{user_id}",
            json={
                "username": "renamed-annotator",
                "role": "审核员",
                "password": "replacement-password",
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["data"]["username"], "renamed-annotator")
        self.assertEqual(updated.json["data"]["role"], "审核员")
        self.assertEqual(user_client.get("/api/auth/me").status_code, 401)
        refreshed_login = user_client.post(
            "/api/login",
            json={
                "username": "renamed-annotator",
                "password": "replacement-password",
            },
        )
        self.assertEqual(refreshed_login.status_code, 200)
        refreshed_user = user_client.get("/api/auth/me")
        self.assertEqual(refreshed_user.status_code, 200)
        self.assertEqual(refreshed_user.json["data"]["role"], "审核员")

        disabled = self.client.patch(
            f"/api/users/{user_id}",
            json={"is_active": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json["data"]["is_active"])
        self.assertEqual(user_client.get("/api/auth/me").status_code, 401)
        disabled_login = self.app.test_client().post(
            "/api/login",
            json={
                "username": "renamed-annotator",
                "password": "replacement-password",
            },
        )
        self.assertEqual(disabled_login.status_code, 403)

        enabled = self.client.patch(
            f"/api/users/{user_id}",
            json={"is_active": True},
        )
        self.assertEqual(enabled.status_code, 200)

    def test_user_management_validates_password_and_keeps_admin_enabled(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        invalid_password = self.client.post(
            "/api/users",
            json={"username": "short-pass", "password": "short", "role": "标注员"},
        )
        self.assertEqual(invalid_password.status_code, 400)

        disable_last_admin = self.client.patch(
            "/api/users/7",
            json={"is_active": False},
        )
        self.assertEqual(disable_last_admin.status_code, 409)

    def test_second_level_endpoint_rejects_unknown_top_level_menu(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        response = self.client.get("/api/menus/999/children")
        self.assertEqual(response.status_code, 404)

    def test_data_item_endpoints_require_login(self):
        self.assertEqual(self.client.get("/api/data-items").status_code, 401)
        self.assertEqual(
            self.client.get("/api/data-items/doc-1").status_code, 401
        )
        self.assertEqual(
            self.client.put(
                "/api/data-items/1/label", json={"label": "正向"}
            ).status_code,
            401,
        )

    def test_list_and_update_data_item_label(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        listing = self.client.get("/api/data-items")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json["data"]["total"], 2)
        self.assertEqual(
            listing.json["data"]["items"][0]["id"], "doc-1"
        )
        self.assertEqual(
            self.elastic.search_sorts[-1],
            [
                {
                    field: {
                        "order": "desc",
                        "missing": "_last",
                        "unmapped_type": "date",
                    }
                }
                for field in (
                    "inserted_at",
                    "created_at",
                    "@timestamp",
                    "timestamp",
                    "order_date",
                )
            ] + ["_shard_doc"],
        )
        self.assertIn("示例商品", listing.json["data"]["items"][0]["content"])
        self.assertIsNone(listing.json["data"]["items"][0]["label"])

        detail = self.client.get("/api/data-items/doc-1")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            detail.json["data"]["content"],
            "订单号：55 · 客户：测试用户 · 商品：示例商品",
        )
        self.assertEqual(
            detail.json["data"]["fields"]["products"][0]["product_name"],
            "示例商品",
        )
        self.assertEqual(
            detail.json["data"]["inserted_at"], "2026-10-28T08:30:00Z"
        )
        self.assertIsNone(detail.json["data"]["labeled_at"])

        updated = self.client.put("/api/data-items/doc-1/label", json={"label": "正向"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["data"]["label"], "正向")
        self.assertEqual(updated.json["data"]["labeled_by"], "tester")
        self.assertTrue(updated.json["data"]["labeled_at"])

        listing_after_update = self.client.get("/api/data-items")
        self.assertEqual(
            listing_after_update.json["data"]["items"][0]["label"], "正向"
        )
        self.assertEqual(
            listing_after_update.json["data"]["items"][0]["labeled_by"], "tester"
        )
        self.assertEqual(
            listing_after_update.json["data"]["items"][0]["labeled_at"],
            updated.json["data"]["labeled_at"],
        )
        detail_after_update = self.client.get("/api/data-items/doc-1")
        self.assertEqual(detail_after_update.json["data"]["label"], "正向")
        self.assertTrue(detail_after_update.json["data"]["labeled_at"])
        self.assertEqual(
            detail_after_update.json["data"]["fields"]["label_history"][0]["label"],
            "正向",
        )

        cleared = self.client.put(
            "/api/data-items/doc-1/label", json={"label": None}
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json["data"]["label"])
        detail_after_clear = self.client.get("/api/data-items/doc-1")
        self.assertIsNone(detail_after_clear.json["data"]["label"])
        self.assertEqual(
            detail_after_clear.json["data"]["fields"]["label_history"][-1]["label"],
            None,
        )

    def test_issue_reports_are_validated_and_persisted(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        invalid_type = self.client.post(
            "/api/data-items/doc-1/issues",
            json={"type": "未知类型", "description": "需要核对"},
        )
        self.assertEqual(invalid_type.status_code, 400)

        missing_description = self.client.post(
            "/api/data-items/doc-1/issues",
            json={"type": "数据异常", "description": "  "},
        )
        self.assertEqual(missing_description.status_code, 400)

        report = self.client.post(
            "/api/data-items/doc-1/issues",
            json={"type": "数据异常", "description": "原文内容不完整"},
        )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json["data"]["reported_by"], "tester")
        self.assertEqual(
            self.elastic.items["doc-1"]["issue_reports"][0]["description"],
            "原文内容不完整",
        )
        self.assertEqual(len(self.database.issues), 1)

    def test_issue_feedback_can_be_triaged_and_resolved(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.database.issues.append(
            {
                "id": 1,
                "item_id": "doc-1",
                "dataset_id": 1,
                "project_id": 1,
                "issue_type": "数据异常",
                "description": "内容需要复核",
                "reported_by": "tester",
                "status": "待处理",
                "assignee": None,
                "resolution": "",
                "created_at": "2026-10-30",
                "updated_at": "2026-10-30",
            }
        )
        issue_list = self.client.get("/api/issues?page=1&page_size=20")
        self.assertEqual(issue_list.status_code, 200)
        self.assertEqual(issue_list.json["data"]["total"], 1)

        invalid_resolution = self.client.patch(
            "/api/issues/1",
            json={"status": "已解决"},
        )
        self.assertEqual(invalid_resolution.status_code, 400)
        resolved = self.client.patch(
            "/api/issues/1",
            json={"status": "已解决", "resolution": "已修复并复核"},
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(self.database.issues[0]["status"], "已解决")
        self.assertEqual(self.database.issues[0]["resolution"], "已修复并复核")
        self.assertEqual(self.database.notifications[0]["recipient"], "tester")

    def test_quality_rules_can_be_configured_and_validated(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        current = self.client.get("/api/quality-rules")
        self.assertEqual(current.status_code, 200)
        rules = current.json["data"]
        for rule in rules:
            if rule["key"] == "min_length":
                rule["threshold"] = 8
            if rule["key"] == "duplicate_content":
                rule["enabled"] = False
            if rule["key"] == "missing_label":
                rule["enabled"] = False
        updated = self.client.put("/api/quality-rules", json={"rules": rules})
        self.assertEqual(updated.status_code, 200)
        configured = self.client.get("/api/quality-rules")
        self.assertEqual(
            next(rule for rule in configured.json["data"] if rule["key"] == "min_length")["threshold"],
            8,
        )
        quality_check = self.client.get("/api/data-items/doc-1/quality-check")
        self.assertEqual(quality_check.status_code, 200)
        self.assertNotIn("尚未设置标注结果。", quality_check.json["data"]["warnings"])
        invalid_rules = [dict(rule) for rule in rules]
        next(rule for rule in invalid_rules if rule["key"] == "min_length")["threshold"] = 0
        self.assertEqual(
            self.client.put("/api/quality-rules", json={"rules": invalid_rules}).status_code,
            400,
        )

    def test_notifications_are_private_and_can_be_marked_read(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.database.notifications.extend(
            [
                {
                    "id": 1,
                    "recipient": "tester",
                    "title": "新任务",
                    "body": "任务已分配",
                    "link": "/data/label/1",
                    "is_read": 0,
                    "created_at": "2026-10-30",
                },
                {
                    "id": 2,
                    "recipient": "other-user",
                    "title": "私有通知",
                    "body": "不可见",
                    "link": "",
                    "is_read": 0,
                    "created_at": "2026-10-30",
                },
            ]
        )
        notifications = self.client.get("/api/notifications")
        self.assertEqual(notifications.status_code, 200)
        self.assertEqual([item["id"] for item in notifications.json["data"]["items"]], [1])
        self.assertEqual(self.client.patch("/api/notifications/1/read").status_code, 200)
        self.assertEqual(self.database.notifications[0]["is_read"], 1)
        self.assertEqual(self.client.patch("/api/notifications/2/read").status_code, 404)

    def test_data_list_paginates_and_validates_parameters(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        page = self.client.get("/api/data-items?page=2&page_size=1")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json["data"]["page"], 2)
        self.assertEqual(page.json["data"]["items"][0]["id"], "doc-2")

        invalid_page = self.client.get("/api/data-items?page=0")
        self.assertEqual(invalid_page.status_code, 400)

    def test_data_list_uses_point_in_time_search_after_for_next_page(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        first_page = self.client.get("/api/data-items?page=1&page_size=1")
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.json["data"]["items"][0]["id"], "doc-1")
        cursor = first_page.json["data"]["next_cursor"]
        pit_id = first_page.json["data"]["pit_id"]
        self.assertTrue(cursor)
        self.assertTrue(pit_id)

        second_page = self.client.get(
            "/api/data-items?page=2&page_size=1"
            f"&after={cursor}&pit_id={pit_id}"
        )
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(second_page.json["data"]["items"][0]["id"], "doc-2")
        request = self.elastic.search_requests[-1]
        self.assertIsNone(request["index"])
        self.assertIsNone(request["from_"])
        self.assertEqual(request["pit"]["id"], pit_id)
        self.assertEqual(request["search_after"], [0])

        invalid_cursor = self.client.get(
            "/api/data-items?page=2&after=not-a-valid-cursor"
        )
        self.assertEqual(invalid_cursor.status_code, 400)

    def test_task_list_supports_pagination_and_validates_parameters(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.database.tasks = [
            {"id": 1, "name": "first"},
            {"id": 2, "name": "second"},
        ]
        page = self.client.get("/api/tasks?page=2&page_size=1")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json["data"]["total"], 2)
        self.assertEqual(page.json["data"]["page"], 2)
        self.assertEqual(page.json["data"]["items"], [{"id": 2, "name": "second"}])
        self.assertIn("LIMIT %s OFFSET %s", self.database.last_query)

        invalid_page = self.client.get("/api/tasks?page=0")
        self.assertEqual(invalid_page.status_code, 400)

    def test_task_status_transitions_are_guarded_by_workflow(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.database.tasks = [
            {"id": 8, "status": "待审核", "project_id": 1},
            {"id": 9, "status": "待标注", "project_id": 1},
        ]
        blocked = self.client.patch("/api/tasks/8", json={"status": "已完成"})
        self.assertEqual(blocked.status_code, 409)

        paused = self.client.patch("/api/tasks/9", json={"status": "已暂停"})
        self.assertEqual(paused.status_code, 200)
        self.assertEqual(self.database.tasks[1]["status"], "已暂停")

    def test_review_approval_completes_the_task_when_all_items_are_reviewed(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.database.tasks = [{"id": 3, "status": "待审核", "project_id": 1}]
        self.database.task_items = [
            {"task_id": 3, "item_id": "doc-2", "status": "已标注"}
        ]
        response = self.client.put(
            "/api/data-items/doc-2/review",
            json={"decision": "approved"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.database.task_items[0]["status"], "已审核")
        self.assertEqual(self.database.tasks[0]["status"], "已完成")

    def test_review_list_filters_and_paginates(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        response = self.client.get(
            "/api/reviews?status=approved&page=2&page_size=5"
            "&dataset_id=1&annotator=tester&date_from=2026-10-01"
            "&date_to=2026-10-31"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["page"], 2)
        self.assertEqual(response.json["data"]["page_size"], 5)
        search = self.elastic.review_search_requests[-1]
        self.assertEqual(search["from_"], 5)
        self.assertEqual(search["size"], 5)
        filters = search["query"]["bool"]["filter"]
        self.assertIn({"term": {"labeled_by.keyword": "tester"}}, filters)
        self.assertIn(
            {
                "range": {
                    "labeled_at": {
                        "gte": "2026-10-01T00:00:00",
                        "lte": "2026-10-31T23:59:59",
                    }
                }
            },
            filters,
        )

    def test_data_list_filters_by_label_status(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        labeled = self.client.get("/api/data-items?label_status=labeled")
        self.assertEqual(labeled.status_code, 200)
        self.assertEqual(labeled.json["data"]["total"], 1)
        self.assertEqual(labeled.json["data"]["items"][0]["id"], "doc-2")

        unlabeled = self.client.get("/api/data-items?label_status=unlabeled")
        self.assertEqual(unlabeled.status_code, 200)
        self.assertEqual(unlabeled.json["data"]["total"], 1)
        self.assertEqual(unlabeled.json["data"]["items"][0]["id"], "doc-1")

        invalid_filter = self.client.get("/api/data-items?label_status=unknown")
        self.assertEqual(invalid_filter.status_code, 400)

        neutral = self.client.get("/api/data-items?label_status=中性")
        self.assertEqual(neutral.status_code, 200)
        self.assertEqual(neutral.json["data"]["items"][0]["label"], "中性")
        self.assertEqual(
            neutral.json["data"]["items"][0]["labeled_at"],
            "2026-10-29T10:00:00Z",
        )

        positive = self.client.get("/api/data-items?label_status=正向")
        self.assertEqual(positive.status_code, 200)
        self.assertEqual(positive.json["data"]["total"], 0)

        self.elastic.items["doc-1"]["label"] = "正向"
        positive = self.client.get("/api/data-items?label_status=正向")
        self.assertEqual(positive.json["data"]["total"], 1)
        self.assertEqual(positive.json["data"]["items"][0]["id"], "doc-1")

        self.elastic.items["doc-1"]["label"] = "负向"
        negative = self.client.get("/api/data-items?label_status=负向")
        self.assertEqual(negative.json["data"]["total"], 1)
        self.assertEqual(negative.json["data"]["items"][0]["label"], "负向")

    def test_elastic_connection_failure_returns_retryable_service_error(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        with patch(
            "app.get_es_client", side_effect=RuntimeError("connection refused")
        ):
            response = self.client.get("/api/data-items")
        self.assertEqual(response.status_code, 503)
        self.assertIn("Elastic 服务暂不可用", response.json["message"])

    def test_elastic_initialization_creates_index_and_sample_documents_once(self):
        with patch("app.get_es_client", return_value=self.elastic):
            runner = self.app.test_cli_runner()
            first_run = runner.invoke(args=["init-elastic"])
            second_run = runner.invoke(args=["init-elastic"])

        self.assertEqual(first_run.exit_code, 0, first_run.output)
        self.assertEqual(second_run.exit_code, 0, second_run.output)
        self.assertEqual(len(self.elastic.indexed_documents), 6)
        self.assertEqual(
            self.elastic.indices.mapping["properties"]["label"]["type"],
            "keyword",
        )
        self.assertEqual(
            self.elastic.indices.settings["index.max_result_window"], 50000
        )
        self.assertEqual(
            self.elastic.indices.put_mapping_properties["inserted_at"]["type"],
            "date",
        )

    def test_export_streams_more_than_ten_thousand_records(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        self.elastic.items = {
            str(item_id): {"content": f"record {item_id}"}
            for item_id in range(10001)
        }

        response = self.client.get("/api/data-items/export?format=jsonl")

        self.assertEqual(response.status_code, 200)
        exported_items = response.get_data(as_text=True).splitlines()
        self.assertEqual(len(exported_items), 10001)
        self.assertEqual(json.loads(exported_items[0])["id"], "0")
        self.assertEqual(json.loads(exported_items[-1])["id"], "10000")
        self.assertNotIn("scroll-1", self.elastic.scroll_hits)

    def test_label_endpoint_rejects_invalid_label_and_unknown_item(self):
        self.client.post(
            "/api/login",
            json={"username": "tester", "password": "correct-password"},
        )
        invalid_label = self.client.put(
            "/api/data-items/doc-1/label", json={"label": ["正向"]}
        )
        self.assertEqual(invalid_label.status_code, 400)

        missing_item = self.client.put(
            "/api/data-items/missing/label", json={"label": "正向"}
        )
        self.assertEqual(missing_item.status_code, 404)
        missing_detail = self.client.get("/api/data-items/missing")
        self.assertEqual(missing_detail.status_code, 404)


if __name__ == "__main__":
    unittest.main()
