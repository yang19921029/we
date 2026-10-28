import os
import secrets
from functools import wraps

import click
import pymysql
from flask import Flask, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash


DATABASE_NAME = "we"


def get_db():
    if "db" not in g:
        g.db = pymysql.connect(
            host=current_app.config["MYSQL_HOST"],
            port=current_app.config["MYSQL_PORT"],
            user=current_app.config["MYSQL_USER"],
            password=current_app.config["MYSQL_PASSWORD"],
            database=DATABASE_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
    return g.db


def init_db() -> None:
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
                    (2, "算法备案", "/filing", None, 2),
                    (3, "变更与注销", "/changes", None, 3),
                    (4, "运行管理", "/operations", None, 4),
                    (5, "政策法规", "/policies", None, 5),
                    (6, "工作台", "/dashboard", 1, 1),
                    (7, "算法信息服务备案", "/filing/create", 2, 1),
                    (8, "算法备案信息查询", "/filing/search", 2, 2),
                    (9, "备案材料管理", "/filing/materials", 2, 3),
                    (10, "备案信息变更", "/changes/update", 3, 1),
                    (11, "备案注销", "/changes/cancel", 3, 2),
                    (12, "运行情况报送", "/operations/reports", 4, 1),
                    (13, "安全评估材料", "/operations/security", 4, 2),
                    (14, "投诉举报处理", "/operations/complaints", 4, 3),
                    (15, "政策文件", "/policies/documents", 5, 1),
                    (16, "办事指南", "/policies/guides", 5, 2),
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


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return jsonify(code=401, message="请先登录", data=None), 401
        return view(*args, **kwargs)

    return wrapped


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        MYSQL_HOST=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        MYSQL_PORT=int(os.environ.get("MYSQL_PORT", "3306")),
        MYSQL_USER=os.environ.get("MYSQL_USER", "root"),
        MYSQL_PASSWORD=os.environ.get("MYSQL_PASSWORD", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.cli.command("init-db")
    def initialize_database() -> None:
        """Create the we database, tables, and initial menu data."""
        create_database()
        with app.app_context():
            init_db()
        click.echo(f"MySQL 数据库 {DATABASE_NAME} 已初始化。")

    @app.cli.command("init-admin")
    @click.option("--username", prompt=True)
    @click.password_option()
    def init_admin(username: str, password: str) -> None:
        """Create or update an administrator account."""
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (username, password_hash)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE password_hash = VALUES(password_hash)
                """,
                (username, generate_password_hash(password)),
            )
        db.commit()
        click.echo(f"管理员账号 {username} 已创建或更新。")

    @app.post("/api/login")
    def login():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400

        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not username.strip():
            return jsonify(code=400, message="username 不能为空", data=None), 400
        if not isinstance(password, str) or not password:
            return jsonify(code=400, message="password 不能为空", data=None), 400

        with get_db().cursor() as cursor:
            cursor.execute(
                "SELECT id, username, password_hash FROM users WHERE username = %s",
                (username.strip(),),
            )
            user = cursor.fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            return jsonify(code=401, message="用户名或密码错误", data=None), 401

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return jsonify(
            code=0,
            message="登录成功",
            data={"user_id": user["id"], "username": user["username"]},
        )

    @app.get("/api/auth/me")
    @login_required
    def current_user():
        with get_db().cursor() as cursor:
            cursor.execute(
                "SELECT id, username FROM users WHERE id = %s",
                (session["user_id"],),
            )
            user = cursor.fetchone()
        if user is None:
            session.clear()
            return jsonify(code=401, message="登录状态已失效", data=None), 401
        return jsonify(
            code=0,
            message="ok",
            data={"user_id": user["id"], "username": user["username"]},
        )

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(code=0, message="退出登录成功", data=None)

    @app.get("/api/menus")
    @login_required
    def list_menus():
        with get_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, path
                FROM menus
                WHERE parent_id IS NULL
                ORDER BY sort_order, id
                """
            )
            rows = cursor.fetchall()
        return jsonify(code=0, message="ok", data=[dict(row) for row in rows])

    @app.get("/api/menus/<int:menu_id>/children")
    @login_required
    def list_menu_children(menu_id: int):
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM menus WHERE id = %s AND parent_id IS NULL",
                (menu_id,),
            )
            parent = cursor.fetchone()
        if parent is None:
            return jsonify(code=404, message="一级菜单不存在", data=None), 404

        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, path, parent_id
                FROM menus
                WHERE parent_id = %s
                ORDER BY sort_order, id
                """,
                (menu_id,),
            )
            rows = cursor.fetchall()
        return jsonify(code=0, message="ok", data=[dict(row) for row in rows])

    return app


app = create_app()
