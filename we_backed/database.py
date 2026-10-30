"""Database creation and schema initialization."""

import re
import json

import pymysql
from flask import current_app

DATABASE_NAME = "we"


def init_db(get_db) -> None:
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(191) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute("SHOW COLUMNS FROM users LIKE 'role'")
        if cursor.fetchone() is None:
            cursor.execute(
                """
                ALTER TABLE users
                ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT '标注员'
                """
            )
        else:
            cursor.execute(
                "ALTER TABLE users ALTER COLUMN role SET DEFAULT '标注员'"
            )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS menus (
                id INT NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                path VARCHAR(255) NOT NULL,
                parent_id INT NULL,
                sort_order INT NOT NULL DEFAULT 0,
                INDEX idx_menus_parent_sort (parent_id, sort_order),
                CONSTRAINT fk_menus_parent
                    FOREIGN KEY (parent_id) REFERENCES menus(id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(191) NOT NULL UNIQUE,
                description TEXT NOT NULL,
                created_by VARCHAR(191) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                organization_id INT NOT NULL,
                name VARCHAR(191) NOT NULL,
                description TEXT NOT NULL,
                created_by VARCHAR(191) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_projects_organization_name (organization_id, name),
                CONSTRAINT fk_projects_organization FOREIGN KEY (organization_id)
                    REFERENCES organizations(id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS project_members (
                project_id INT NOT NULL,
                user_id INT NOT NULL,
                added_by INT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (project_id, user_id),
                INDEX idx_project_members_user (user_id, project_id),
                CONSTRAINT fk_project_members_project FOREIGN KEY (project_id)
                    REFERENCES projects(id) ON DELETE CASCADE,
                CONSTRAINT fk_project_members_user FOREIGN KEY (user_id)
                    REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_project_members_added_by FOREIGN KEY (added_by)
                    REFERENCES users(id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            INSERT IGNORE INTO organizations (id, name, description, created_by)
            VALUES (1, '默认组织', '平台默认组织。', 'system')
            """
        )
        cursor.execute(
            """
            INSERT IGNORE INTO projects
                (id, organization_id, name, description, created_by)
            VALUES (1, 1, '默认项目', '兼容已有数据集和标注任务。', 'system')
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(191) NOT NULL,
                description TEXT NOT NULL,
                created_by VARCHAR(191) NOT NULL,
                record_count INT NOT NULL DEFAULT 0,
                project_id INT NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_datasets_project_name (project_id, name)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute("SHOW COLUMNS FROM datasets LIKE 'project_id'")
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE datasets ADD COLUMN project_id INT NOT NULL DEFAULT 1"
            )
        cursor.execute("SHOW INDEX FROM datasets")
        dataset_indexes = {}
        for index in cursor.fetchall():
            dataset_indexes.setdefault(index["Key_name"], []).append(index)
        for index_name, rows in dataset_indexes.items():
            if (
                index_name != "PRIMARY"
                and all(row["Non_unique"] == 0 for row in rows)
                and [row["Column_name"] for row in rows] == ["name"]
            ):
                if not re.fullmatch(r"[A-Za-z0-9_]+", index_name):
                    raise RuntimeError("Unexpected dataset index name.")
                cursor.execute(f"ALTER TABLE datasets DROP INDEX `{index_name}`")
        if "uq_datasets_project_name" not in dataset_indexes:
            cursor.execute(
                """
                ALTER TABLE datasets
                ADD UNIQUE KEY uq_datasets_project_name (project_id, name)
                """
            )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS label_schemas (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(191) NOT NULL UNIQUE,
                description TEXT NOT NULL,
                labels_json TEXT NOT NULL,
                version INT NOT NULL DEFAULT 1,
                updated_by VARCHAR(191) NOT NULL,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS label_schema_versions (
                schema_id INT NOT NULL,
                version INT NOT NULL,
                labels_json TEXT NOT NULL,
                changed_by VARCHAR(191) NOT NULL,
                changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (schema_id, version),
                CONSTRAINT fk_label_schema_versions_schema
                    FOREIGN KEY (schema_id) REFERENCES label_schemas(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS annotation_tasks (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(191) NOT NULL,
                dataset_id INT NOT NULL,
                label_schema_id INT NOT NULL,
                assignee VARCHAR(191) NOT NULL,
                priority VARCHAR(16) NOT NULL DEFAULT '中',
                status VARCHAR(32) NOT NULL DEFAULT '待分配',
                deadline DATETIME NULL,
                instructions TEXT NOT NULL,
                created_by VARCHAR(191) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_tasks_status_assignee (status, assignee),
                CONSTRAINT fk_tasks_dataset FOREIGN KEY (dataset_id)
                    REFERENCES datasets(id),
                CONSTRAINT fk_tasks_label_schema FOREIGN KEY (label_schema_id)
                    REFERENCES label_schemas(id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS task_items (
                task_id INT NOT NULL,
                item_id VARCHAR(512) NOT NULL,
                assignee VARCHAR(191) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT '待标注',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (task_id, item_id),
                INDEX idx_task_items_assignee_status (assignee, status),
                CONSTRAINT fk_task_items_task FOREIGN KEY (task_id)
                    REFERENCES annotation_tasks(id) ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                actor VARCHAR(191) NOT NULL,
                action VARCHAR(64) NOT NULL,
                entity_type VARCHAR(64) NOT NULL,
                entity_id VARCHAR(191) NOT NULL,
                details_json TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_audit_logs_created (created_at),
                INDEX idx_audit_logs_entity (entity_type, entity_id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            INSERT IGNORE INTO datasets
                (id, name, description, created_by, project_id)
            VALUES
                (1, '默认数据集', '兼容已有 Elastic 数据记录。', 'system', 1)
            """
        )
        cursor.execute(
            """
            INSERT IGNORE INTO label_schemas
                (id, name, description, labels_json, updated_by)
            VALUES
                (1, '情感分类', '将文本按整体情感倾向标注。', %s, 'system')
            """,
            (
                json.dumps(
                    [
                        {"code": "positive", "name": "正向", "color": "#2d9b6f"},
                        {"code": "neutral", "name": "中性", "color": "#d99b37"},
                        {"code": "negative", "name": "负向", "color": "#d65b57"},
                    ],
                    ensure_ascii=False,
                ),
            ),
        )
        cursor.execute(
            """
            INSERT IGNORE INTO label_schema_versions
                (schema_id, version, labels_json, changed_by)
            SELECT id, version, labels_json, updated_by
            FROM label_schemas WHERE id = 1
            """
        )
        cursor.execute("SELECT COUNT(*) AS total FROM menus")
        menu_count = cursor.fetchone()["total"]
        if menu_count == 0:
            cursor.executemany(
                """
                INSERT INTO menus (id, name, path, parent_id, sort_order)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (1, "首页", "/dashboard", None, 1),
                    (2, "数据标注", "/data/list", None, 2),
                    (3, "项目与任务管理", "/tasks/list", None, 3),
                    (4, "质量管理", "/operations", None, 4),
                    (5, "规范与帮助", "/policies", None, 5),
                    (17, "标签体系管理", "/labels", None, 6),
                    (22, "统计分析", "/analytics", None, 7),
                    (23, "数据交付与导出", "/data/export", None, 8),
                    (24, "人员与权限", "/users", None, 9),
                    (28, "系统设置", "/settings", None, 10),
                    (6, "标注工作台", "/dashboard", 1, 1),
                    (7, "数据展示列表", "/data/list", 2, 1),
                    (8, "数据打标", "/data/label", 2, 2),
                    (9, "数据集管理", "/datasets", 2, 3),
                    (31, "组织与项目", "/projects", 3, 1),
                    (20, "任务列表", "/tasks/list", 3, 2),
                    (21, "任务分配", "/tasks/assign", 3, 3),
                    (12, "质检任务", "/operations/reports", 4, 1),
                    (13, "质检规则", "/operations/security", 4, 2),
                    (14, "质检报告", "/operations/complaints", 4, 3),
                    (15, "标注规范", "/policies/documents", 5, 1),
                    (16, "操作指南", "/policies/guides", 5, 2),
                    (18, "标签体系", "/labels", 17, 1),
                    (19, "版本历史", "/labels/versions", 17, 2),
                    (25, "统计看板", "/analytics", 22, 1),
                    (26, "数据导出", "/data/export", 23, 1),
                    (27, "用户与角色", "/users", 24, 1),
                    (29, "平台设置", "/settings", 28, 1),
                    (30, "操作日志", "/audit-logs", 28, 2),
                ],
            )
        else:
            cursor.execute(
                "DELETE FROM menus WHERE parent_id IN (2, 3)",
            )
            cursor.execute(
                "DELETE FROM menus WHERE id = 3 AND parent_id IS NULL"
            )
            cursor.executemany(
                """
                INSERT INTO menus (id, name, path, parent_id, sort_order)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    path = VALUES(path),
                    parent_id = VALUES(parent_id),
                    sort_order = VALUES(sort_order)
                """,
                [
                    (2, "数据标注", "/data/list", None, 2),
                    (3, "项目与任务管理", "/tasks/list", None, 3),
                    (4, "质量管理", "/operations", None, 4),
                    (5, "规范与帮助", "/policies", None, 5),
                    (17, "标签体系管理", "/labels", None, 6),
                    (22, "统计分析", "/analytics", None, 7),
                    (23, "数据交付与导出", "/data/export", None, 8),
                    (24, "人员与权限", "/users", None, 9),
                    (28, "系统设置", "/settings", None, 10),
                    (6, "标注工作台", "/dashboard", 1, 1),
                    (7, "数据展示列表", "/data/list", 2, 1),
                    (8, "数据打标", "/data/label", 2, 2),
                    (9, "数据集管理", "/datasets", 2, 3),
                    (31, "组织与项目", "/projects", 3, 1),
                    (20, "任务列表", "/tasks/list", 3, 2),
                    (21, "任务分配", "/tasks/assign", 3, 3),
                    (12, "质检任务", "/operations/reports", 4, 1),
                    (13, "质检规则", "/operations/security", 4, 2),
                    (14, "质检报告", "/operations/complaints", 4, 3),
                    (15, "标注规范", "/policies/documents", 5, 1),
                    (16, "操作指南", "/policies/guides", 5, 2),
                    (18, "标签体系", "/labels", 17, 1),
                    (19, "版本历史", "/labels/versions", 17, 2),
                    (25, "统计看板", "/analytics", 22, 1),
                    (26, "数据导出", "/data/export", 23, 1),
                    (27, "用户与角色", "/users", 24, 1),
                    (29, "平台设置", "/settings", 28, 1),
                    (30, "操作日志", "/audit-logs", 28, 2),
                ],
            )
    db.commit()


def create_database() -> None:
    connection = pymysql.connect(
        host=current_app.config["MYSQL_HOST"],
        port=current_app.config["MYSQL_PORT"],
        user=current_app.config["MYSQL_USER"],
        password=current_app.config["MYSQL_PASSWORD"],
        charset="utf8mb4",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DATABASE_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        connection.close()
