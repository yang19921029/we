"""Authentication and menu API routes."""

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
import hashlib
import hmac
import re
import secrets
import smtplib
import ssl

import app as app_module

from flask import current_app, jsonify
from flask import request
from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

from app import (
    login_required,
    write_audit_log,
)

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 256
CODE_PATTERN = re.compile(r"^[0-9]{6}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE_EXPIRY_MINUTES = 10
CODE_RESEND_SECONDS = 60
MAX_CODE_ATTEMPTS = 5
ROLE_MENU_PATHS = {
    "任务负责人": {
        "/dashboard",
        "/data/list",
        "/data/label",
        "/datasets",
        "/projects",
        "/tasks/list",
        "/tasks/assign",
        "/labels",
        "/labels/versions",
        "/policies/documents",
        "/policies/guides",
    },
    "标注员": {
        "/dashboard",
        "/data/label",
        "/policies/documents",
        "/policies/guides",
    },
    "审核员": {
        "/dashboard",
        "/operations/reports",
        "/operations/complaints",
        "/policies/documents",
        "/policies/guides",
    },
    "数据分析员": {
        "/dashboard",
        "/data/list",
        "/analytics",
        "/data/export",
        "/policies/documents",
        "/policies/guides",
    },
}
GLOBAL_MENU_ROLES = {"超级管理员", "项目管理员"}


def _validate_password(password):
    return (
        isinstance(password, str)
        and PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH
    )


def _normalize_email(value):
    if not isinstance(value, str) or len(value) > 254:
        return None
    email = value.strip().lower()
    display_name, parsed_email = parseaddr(email)
    if (
        not email
        or display_name
        or parsed_email != email
        or not EMAIL_PATTERN.fullmatch(email)
    ):
        return None
    return email


def _code_digest(user_id, purpose, email, code):
    message = f"{user_id}:{purpose}:{email}:{code}".encode()
    return hmac.new(
        str(current_app.secret_key).encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def _send_verification_email(recipient, code, purpose):
    host = current_app.config["SMTP_HOST"]
    sender = current_app.config["SMTP_SENDER"]
    if not host or not sender:
        raise RuntimeError("尚未配置 SMTP_HOST 和 SMTP_SENDER，无法发送验证码。")

    subject = "数据标注管理平台邮箱验证码"
    action = "绑定邮箱" if purpose == "bind_email" else "重置密码"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"您好，您正在进行{action}操作。验证码为：{code}，"
        f"{CODE_EXPIRY_MINUTES} 分钟内有效。若非本人操作，请忽略此邮件。"
    )

    timeout = current_app.config["SMTP_TIMEOUT"]
    if current_app.config["SMTP_USE_SSL"]:
        with smtplib.SMTP_SSL(
            host,
            current_app.config["SMTP_PORT"],
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as server:
            _send_smtp_message(server, message)
    else:
        with smtplib.SMTP(
            host,
            current_app.config["SMTP_PORT"],
            timeout=timeout,
        ) as server:
            if current_app.config["SMTP_STARTTLS"]:
                server.starttls(context=ssl.create_default_context())
            _send_smtp_message(server, message)


def _send_smtp_message(server, message):
    username = current_app.config["SMTP_USERNAME"]
    if username:
        server.login(username, current_app.config["SMTP_PASSWORD"])
    server.send_message(message)


def _issue_code(user_id, email, purpose):
    db = app_module.get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT created_at FROM account_verification_codes
            WHERE user_id = %s AND purpose = %s
            """,
            (user_id, purpose),
        )
        existing = cursor.fetchone()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if existing and existing["created_at"] > now - timedelta(
            seconds=CODE_RESEND_SECONDS
        ):
            return False

    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = _code_digest(user_id, purpose, email, code)
    with db.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO account_verification_codes
                (user_id, purpose, email, code_hash, expires_at, attempts, created_at)
            VALUES (%s, %s, %s, %s, DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s MINUTE), 0,
                    UTC_TIMESTAMP())
            ON DUPLICATE KEY UPDATE
                email = VALUES(email),
                code_hash = VALUES(code_hash),
                expires_at = VALUES(expires_at),
                attempts = 0,
                created_at = UTC_TIMESTAMP()
            """,
            (user_id, purpose, email, digest, CODE_EXPIRY_MINUTES),
        )
    db.commit()
    try:
        _send_verification_email(email, code, purpose)
    except (OSError, RuntimeError, smtplib.SMTPException) as error:
        current_app.logger.exception("Unable to send account verification email")
        with db.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM account_verification_codes
                WHERE user_id = %s AND purpose = %s AND code_hash = %s
                """,
                (user_id, purpose, digest),
            )
        db.commit()
        raise RuntimeError("验证码邮件发送失败，请管理员检查邮件服务配置后重试。") from error
    return True


def _check_code(user_id, purpose, email, code):
    if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
        return False
    db = app_module.get_db()
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT email, code_hash, expires_at, attempts
            FROM account_verification_codes
            WHERE user_id = %s AND purpose = %s
            """,
            (user_id, purpose),
        )
        verification = cursor.fetchone()
    if (
        verification is None
        or verification["email"] != email
        or verification["attempts"] >= MAX_CODE_ATTEMPTS
        or verification["expires_at"]
        <= datetime.now(timezone.utc).replace(tzinfo=None)
    ):
        return False

    matches = hmac.compare_digest(
        verification["code_hash"],
        _code_digest(user_id, purpose, email, code),
    )
    with db.cursor() as cursor:
        if matches:
            cursor.execute(
                """
                DELETE FROM account_verification_codes
                WHERE user_id = %s AND purpose = %s
                """,
                (user_id, purpose),
            )
        else:
            cursor.execute(
                """
                UPDATE account_verification_codes
                SET attempts = attempts + 1
                WHERE user_id = %s AND purpose = %s AND attempts < %s
                """,
                (user_id, purpose, MAX_CODE_ATTEMPTS),
            )
    db.commit()
    return matches


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
                "SELECT id, username, password_hash, role, is_active, auth_version FROM users WHERE username = %s",
                (username.strip(),),
            )
            user = cursor.fetchone()
        if user is not None and not user.get("is_active", 1):
            return jsonify(code=403, message="账号已禁用，请联系管理员。", data=None), 403
        if user is None or not check_password_hash(user["password_hash"], password):
            return jsonify(code=401, message="用户名或密码错误", data=None), 401

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user.get("role", "项目管理员")
        session["auth_version"] = user.get("auth_version", 0)
        session["session_id"] = secrets.token_urlsafe(32)
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO active_sessions
                    (session_id, user_id, auth_version, last_seen_at)
                VALUES (%s, %s, %s, UTC_TIMESTAMP())
                """,
                (
                    session["session_id"],
                    user["id"],
                    session["auth_version"],
                ),
            )
        db.commit()
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
                "SELECT id, username, role, is_active FROM users WHERE id = %s",
                (session["user_id"],),
            )
            user = cursor.fetchone()
        if user is None or not user.get("is_active", 1):
            session.clear()
            return jsonify(code=401, message="登录状态已失效或账号已禁用", data=None), 401
        return jsonify(
            code=0,
            message="ok",
            data={
                "user_id": user["id"],
                "username": user["username"],
                "role": user.get("role", "项目管理员"),
            },
        )

    @app.post("/api/auth/change-password")
    @login_required
    def change_password():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        current_password = payload.get("current_password")
        new_password = payload.get("new_password")
        if not isinstance(current_password, str) or not current_password:
            return jsonify(code=400, message="请输入当前密码。", data=None), 400
        if not _validate_password(new_password):
            return jsonify(
                code=400,
                message=f"新密码长度必须为 {PASSWORD_MIN_LENGTH} 至 {PASSWORD_MAX_LENGTH} 个字符。",
                data=None,
            ), 400
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT password_hash, auth_version FROM users WHERE id = %s",
                (session["user_id"],),
            )
            user = cursor.fetchone()
        if user is None or not check_password_hash(
            user["password_hash"], current_password
        ):
            return jsonify(code=400, message="当前密码不正确。", data=None), 400
        if check_password_hash(user["password_hash"], new_password):
            return jsonify(code=400, message="新密码不能与当前密码相同。", data=None), 400
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = %s, auth_version = auth_version + 1 WHERE id = %s",
                (generate_password_hash(new_password), session["user_id"]),
            )
        session["auth_version"] = user.get("auth_version", 0) + 1
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "UPDATE active_sessions SET auth_version = %s WHERE session_id = %s AND user_id = %s",
                (
                    session["auth_version"],
                    session["session_id"],
                    session["user_id"],
                ),
            )
        app_module.get_db().commit()
        write_audit_log(
            "change_password",
            "user",
            str(session["user_id"]),
        )
        app_module.get_db().commit()
        return jsonify(code=0, message="密码修改成功。", data=None)

    @app.post("/api/auth/presence")
    @login_required
    def update_presence():
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                UPDATE active_sessions SET last_seen_at = UTC_TIMESTAMP()
                WHERE session_id = %s AND user_id = %s
                """,
                (session["session_id"], session["user_id"]),
            )
            cursor.execute(
                """
                DELETE FROM active_sessions
                WHERE last_seen_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)
                """
            )
            cursor.execute(
                """
                SELECT COUNT(DISTINCT s.user_id) AS total
                FROM active_sessions s
                JOIN users u ON u.id = s.user_id
                    AND u.auth_version = s.auth_version
                WHERE u.is_active = 1
                    AND s.last_seen_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 5 MINUTE)
                """
            )
            total = cursor.fetchone()["total"]
        db.commit()
        return jsonify(
            code=0,
            message="ok",
            data={"online_users": total, "window_minutes": 5},
        )

    @app.get("/api/auth/recovery-email")
    @login_required
    def get_recovery_email():
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                "SELECT email, email_verified_at FROM users WHERE id = %s",
                (session["user_id"],),
            )
            user = cursor.fetchone()
        email = user.get("email") if user else None
        verified = bool(user and user.get("email_verified_at"))
        masked_email = None
        if verified and isinstance(email, str):
            name, domain = email.split("@", 1)
            masked_email = f"{name[:1]}***@{domain}"
        return jsonify(
            code=0,
            message="ok",
            data={"email": masked_email, "verified": verified},
        )

    @app.post("/api/auth/recovery-email/send-code")
    @login_required
    def send_recovery_email_code():
        payload = request.get_json(silent=True)
        email = _normalize_email(payload.get("email")) if isinstance(payload, dict) else None
        if email is None:
            return jsonify(code=400, message="请输入有效的邮箱地址。", data=None), 400
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM users WHERE email = %s AND id != %s",
                (email, session["user_id"]),
            )
            if cursor.fetchone():
                return jsonify(code=409, message="该邮箱已绑定其他账号。", data=None), 409
        try:
            sent = _issue_code(session["user_id"], email, "bind_email")
        except RuntimeError as error:
            return jsonify(code=503, message=str(error), data=None), 503
        if not sent:
            return jsonify(
                code=429,
                message="验证码发送过于频繁，请 60 秒后再试。",
                data=None,
            ), 429
        return jsonify(code=0, message="验证码已发送，请查收邮件。", data=None)

    @app.post("/api/auth/recovery-email/verify")
    @login_required
    def verify_recovery_email():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        email = _normalize_email(payload.get("email"))
        code = payload.get("code")
        if email is None or not _check_code(
            session["user_id"], "bind_email", email, code
        ):
            return jsonify(code=400, message="验证码无效或已过期，请重新获取。", data=None), 400
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET email = %s, email_verified_at = UTC_TIMESTAMP() WHERE id = %s",
                (email, session["user_id"]),
            )
        db.commit()
        write_audit_log(
            "bind_recovery_email",
            "user",
            str(session["user_id"]),
        )
        return jsonify(code=0, message="恢复邮箱验证并绑定成功。", data=None)

    @app.post("/api/auth/forgot-password/send-code")
    def send_forgot_password_code():
        payload = request.get_json(silent=True)
        username = payload.get("username") if isinstance(payload, dict) else None
        if not isinstance(username, str) or not username.strip():
            return jsonify(code=400, message="请输入登录账号。", data=None), 400
        generic_response = {
            "code": 0,
            "message": "如果账号已绑定验证邮箱，验证码将发送至该邮箱；否则请联系管理员重置密码。",
            "data": None,
        }
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT id, email FROM users
                WHERE username = %s AND is_active = 1 AND email_verified_at IS NOT NULL
                """,
                (username.strip(),),
            )
            user = cursor.fetchone()
        if not user or not user.get("email"):
            return jsonify(**generic_response)
        try:
            _issue_code(user["id"], user["email"], "reset_password")
        except RuntimeError as error:
            current_app.logger.error("Password recovery email delivery failed: %s", error)
            return jsonify(
                code=503,
                message="邮件服务暂不可用，请稍后重试或联系管理员。",
                data=None,
            ), 503
        return jsonify(**generic_response)

    @app.post("/api/auth/forgot-password/reset")
    def reset_forgotten_password():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        username = payload.get("username")
        code = payload.get("code")
        new_password = payload.get("new_password")
        if not isinstance(username, str) or not username.strip():
            return jsonify(code=400, message="请输入登录账号。", data=None), 400
        if not _validate_password(new_password):
            return jsonify(
                code=400,
                message=f"新密码长度必须为 {PASSWORD_MIN_LENGTH} 至 {PASSWORD_MAX_LENGTH} 个字符。",
                data=None,
            ), 400
        db = app_module.get_db()
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, email FROM users
                WHERE username = %s AND is_active = 1 AND email_verified_at IS NOT NULL
                """,
                (username.strip(),),
            )
            user = cursor.fetchone()
        if not user or not user.get("email") or not _check_code(
            user["id"], "reset_password", user["email"], code
        ):
            return jsonify(code=400, message="验证码无效或已过期，请重新获取。", data=None), 400
        with db.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = %s, auth_version = auth_version + 1 WHERE id = %s",
                (generate_password_hash(new_password), user["id"]),
            )
        db.commit()
        return jsonify(code=0, message="密码重置成功，请使用新密码登录。", data=None)

    @app.post("/api/logout")
    def logout():
        session_id = session.get("session_id")
        if session_id:
            db = app_module.get_db()
            with db.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM active_sessions WHERE session_id = %s",
                    (session_id,),
                )
            db.commit()
        session.clear()
        return jsonify(code=0, message="退出登录成功", data=None)

    @app.get("/api/menus")
    @login_required
    def list_menus():
        role = session.get("role")
        allowed_paths = ROLE_MENU_PATHS.get(role)
        with app_module.get_db().cursor() as cursor:
            if role in GLOBAL_MENU_ROLES:
                cursor.execute(
                    """
                    SELECT id, name, path
                    FROM menus
                    WHERE parent_id IS NULL
                    ORDER BY sort_order, id
                    """
                )
            elif allowed_paths:
                placeholders = ", ".join(["%s"] * len(allowed_paths))
                cursor.execute(
                    f"""
                    SELECT parent.id, parent.name, parent.path
                    FROM menus AS parent
                    WHERE parent.parent_id IS NULL
                        AND EXISTS (
                            SELECT 1
                            FROM menus AS child
                            WHERE child.parent_id = parent.id
                                AND child.path IN ({placeholders})
                        )
                    ORDER BY parent.sort_order, parent.id
                    """,
                    tuple(sorted(allowed_paths)),
                )
            else:
                return jsonify(code=0, message="ok", data=[])
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

        role = session.get("role")
        allowed_paths = ROLE_MENU_PATHS.get(role)
        with db.cursor() as cursor:
            if role in GLOBAL_MENU_ROLES:
                cursor.execute(
                    """
                    SELECT id, name, path, parent_id
                    FROM menus
                    WHERE parent_id = %s
                    ORDER BY sort_order, id
                    """,
                    (menu_id,),
                )
            elif allowed_paths:
                placeholders = ", ".join(["%s"] * len(allowed_paths))
                cursor.execute(
                    f"""
                    SELECT id, name, path, parent_id
                    FROM menus
                    WHERE parent_id = %s AND path IN ({placeholders})
                    ORDER BY sort_order, id
                    """,
                    (menu_id, *sorted(allowed_paths)),
                )
            else:
                return jsonify(code=0, message="ok", data=[])
            rows = cursor.fetchall()
        return jsonify(code=0, message="ok", data=[dict(row) for row in rows])
