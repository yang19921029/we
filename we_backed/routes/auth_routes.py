"""Authentication and menu API routes."""

import app as app_module

from flask import jsonify
from flask import request
from flask import session
from werkzeug.security import check_password_hash

from app import (
    login_required,
)


def register_auth_routes(app):
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

        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT id, username, password_hash, role FROM users WHERE username = %s",
                (username.strip(),),
            )
            user = cursor.fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            return jsonify(code=401, message="用户名或密码错误", data=None), 401

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user.get("role", "项目管理员")
        return jsonify(
            code=0,
            message="登录成功",
            data={
                "user_id": user["id"],
                "username": user["username"],
                "role": session["role"],
            },
        )

    @app.get("/api/auth/me")
    @login_required
    def current_user():
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT id, username, role FROM users WHERE id = %s",
                (session["user_id"],),
            )
            user = cursor.fetchone()
        if user is None:
            session.clear()
            return jsonify(code=401, message="登录状态已失效", data=None), 401
        return jsonify(
            code=0,
            message="ok",
            data={
                "user_id": user["id"],
                "username": user["username"],
                "role": user.get("role", "项目管理员"),
            },
        )

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(code=0, message="退出登录成功", data=None)

    @app.get("/api/menus")
    @login_required
    def list_menus():
        with app_module.get_db().cursor() as cursor:
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
        db = app_module.get_db()
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
