from datetime import datetime, timezone
from functools import wraps
import json
import os
import secrets

import click
import pymysql
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ApiError, NotFoundError, TransportError
from flask import Flask, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash


DATABASE_NAME = "we"
DATA_LABELS = {"正向", "中性", "负向"}
SAMPLE_DATA_ITEMS = [
    ("1", "这款产品操作简单，整体体验很好。"),
    ("2", "物流速度一般，包装没有明显问题。"),
    ("3", "页面经常无法打开，使用体验很差。"),
    ("4", "功能符合预期，客服响应也很及时。"),
    ("5", "收到的商品与描述不太一致。"),
    ("6", "这次更新增加了几个实用功能。"),
]


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


def get_es_client() -> Elasticsearch:
    if "es_client" not in g:
        username = current_app.config["ELASTICSEARCH_USERNAME"]
        password = current_app.config["ELASTICSEARCH_PASSWORD"]
        if bool(username) != bool(password):
            raise RuntimeError(
                "Elastic 用户名和密码必须同时配置或同时留空。"
            )
        options = {
            "request_timeout": current_app.config["ELASTICSEARCH_TIMEOUT"],
        }
        if username and password:
            options["basic_auth"] = (username, password)
        g.es_client = Elasticsearch(
            current_app.config["ELASTICSEARCH_URL"],
            **options,
        )
    return g.es_client


def get_data_item(hit: dict) -> dict:
    source = hit.get("_source") or {}
    content = next(
        (
            source[key]
            for key in ("content", "text", "message", "description")
            if isinstance(source.get(key), str) and source[key].strip()
        ),
        None,
    )
    if content is None:
        summary_fields = (
            ("订单号", "order_id"),
            ("客户", "customer_full_name"),
            ("商品", "products"),
            ("分类", "category"),
            ("标题", "title"),
            ("名称", "name"),
            ("用户", "user"),
            ("SKU", "sku"),
        )
        summary_parts = []
        for label, key in summary_fields:
            if key not in source:
                continue
            value = source[key]
            if key == "products" and isinstance(value, list):
                value = [
                    product.get("product_name", product.get("name", ""))
                    if isinstance(product, dict)
                    else product
                    for product in value
                ]
            if isinstance(value, list):
                value = "、".join(
                    str(item)
                    for item in value
                    if isinstance(item, (str, int, float))
                )
            elif isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            if value not in (None, ""):
                summary_parts.append(f"{label}：{value}")
        if not summary_parts:
            for key, value in source.items():
                if key in {
                    "label",
                    "labeled_by",
                    "inserted_at",
                    "created_at",
                    "@timestamp",
                    "timestamp",
                    "order_date",
                    "labeled_at",
                    "updated_at",
                }:
                    continue
                if isinstance(value, (str, int, float)) and value != "":
                    summary_parts.append(f"{key}：{value}")
                    if len(summary_parts) == 4:
                        break
                elif isinstance(value, list) and value:
                    summary_parts.append(
                        f"{key}：{', '.join(str(item) for item in value[:3])}"
                    )
                    if len(summary_parts) == 4:
                        break
        content = " · ".join(summary_parts) or json.dumps(
            source, ensure_ascii=False
        )
    return {
        "id": str(hit["_id"]),
        "content": content if isinstance(content, str) else str(content),
        "fields": source,
        "label": source.get("label")
        if isinstance(source.get("label"), str)
        else None,
        "labeled_by": source.get("labeled_by")
        if isinstance(source.get("labeled_by"), str)
        else None,
        "inserted_at": source.get(
            "inserted_at",
            source.get(
                "created_at",
                source.get("@timestamp", source.get("timestamp", source.get("order_date"))),
            ),
        ),
        "labeled_at": (
            source.get("labeled_at", source.get("updated_at"))
            if isinstance(source.get("label"), str)
            else None
        ),
    }


def elastic_error_response(
    error: ApiError | TransportError | RuntimeError | ValueError,
):
    if isinstance(error, NotFoundError):
        error_body = error.body if isinstance(error.body, dict) else {}
        error_info = error_body.get("error")
        error_type = error_info.get("type") if isinstance(error_info, dict) else None
        if error_type == "document_missing_exception" or error_body.get("found") is False:
            current_app.logger.warning("Elastic document not found: %s", error)
            return jsonify(code=404, message="数据不存在", data=None), 404
        if error_type == "index_not_found_exception":
            current_app.logger.warning("Elastic index not found: %s", error)
            return (
                jsonify(
                    code=503,
                    message="Elastic 数据索引不存在，请先运行 init-elastic 初始化索引。",
                    data=None,
                ),
                503,
            )
    current_app.logger.exception("Elastic request failed", exc_info=error)
    return (
        jsonify(code=503, message="Elastic 服务暂不可用，请稍后重试。", data=None),
        503,
    )


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
                    (2, "数据标注", "/data/list", None, 2),
                    (4, "质量管理", "/operations", None, 4),
                    (5, "规范与帮助", "/policies", None, 5),
                    (6, "标注工作台", "/dashboard", 1, 1),
                    (7, "数据展示列表", "/data/list", 2, 1),
                    (8, "数据打标", "/data/label", 2, 2),
                    (12, "质检任务", "/operations/reports", 4, 1),
                    (13, "质检规则", "/operations/security", 4, 2),
                    (14, "质检报告", "/operations/complaints", 4, 3),
                    (15, "标注规范", "/policies/documents", 5, 1),
                    (16, "操作指南", "/policies/guides", 5, 2),
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
                    (4, "质量管理", "/operations", None, 4),
                    (5, "规范与帮助", "/policies", None, 5),
                    (6, "标注工作台", "/dashboard", 1, 1),
                    (7, "数据展示列表", "/data/list", 2, 1),
                    (8, "数据打标", "/data/label", 2, 2),
                    (12, "质检任务", "/operations/reports", 4, 1),
                    (13, "质检规则", "/operations/security", 4, 2),
                    (14, "质检报告", "/operations/complaints", 4, 3),
                    (15, "标注规范", "/policies/documents", 5, 1),
                    (16, "操作指南", "/policies/guides", 5, 2),
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
        ELASTICSEARCH_URL=os.environ.get(
            "ELASTICSEARCH_URL", "http://127.0.0.1:9200"
        ),
        ELASTICSEARCH_INDEX=os.environ.get(
            "ELASTICSEARCH_INDEX", "data_items"
        ),
        ELASTICSEARCH_USERNAME=os.environ.get("ELASTICSEARCH_USERNAME", ""),
        ELASTICSEARCH_PASSWORD=os.environ.get("ELASTICSEARCH_PASSWORD", ""),
        ELASTICSEARCH_TIMEOUT=float(
            os.environ.get("ELASTICSEARCH_TIMEOUT", "5")
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    if bool(app.config["ELASTICSEARCH_USERNAME"]) != bool(
        app.config["ELASTICSEARCH_PASSWORD"]
    ):
        raise ValueError(
            "Elastic 用户名和密码必须同时配置或同时留空。"
        )

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()
        es_client = g.pop("es_client", None)
        if es_client is not None:
            es_client.close()

    @app.cli.command("init-db")
    def initialize_database() -> None:
        """Create the we database, tables, and initial menu data."""
        create_database()
        with app.app_context():
            init_db()
        click.echo(f"MySQL 数据库 {DATABASE_NAME} 已初始化。")

    @app.cli.command("init-elastic")
    def initialize_elastic() -> None:
        """Create the configured Elastic index and initial sample documents."""
        client = get_es_client()
        index_name = app.config["ELASTICSEARCH_INDEX"]
        if client.indices.exists(index=index_name):
            client.indices.put_settings(
                index=index_name,
                settings={"index.max_result_window": 50000},
            )
            click.echo(
                f"Elastic 索引 {index_name} 已存在，分页窗口已更新，数据未修改。"
            )
            return
        client.indices.create(
            index=index_name,
            settings={"index": {"max_result_window": 50000}},
            mappings={
                "properties": {
                    "content": {"type": "text"},
                    "label": {"type": "keyword"},
                    "labeled_by": {"type": "keyword"},
                    "inserted_at": {"type": "date"},
                    "labeled_at": {"type": "date"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            },
        )
        for item_id, content in SAMPLE_DATA_ITEMS:
            client.index(
                index=index_name,
                id=item_id,
                document={
                    "content": content,
                    "inserted_at": datetime.now(timezone.utc).isoformat(),
                    "label": None,
                    "labeled_by": None,
                },
                refresh="wait_for",
            )
        click.echo(
            f"Elastic 索引 {index_name} 已创建并写入示例数据。"
        )

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

    @app.get("/api/data-items")
    @login_required
    def list_data_items():
        page_raw = request.args.get("page", "1")
        page_size_raw = request.args.get("page_size", "20")
        try:
            page = int(page_raw)
            page_size = int(page_size_raw)
        except ValueError:
            return jsonify(
                code=400,
                message="page 和 page_size 必须是整数。",
                data=None,
            ), 400
        if page < 1 or page_size < 1 or page_size > 100:
            return jsonify(
                code=400,
                message="page 必须大于 0，page_size 必须在 1 到 100 之间。",
                data=None,
            ), 400
        label_status = request.args.get("label_status", "all")
        if label_status not in {"all", "labeled", "unlabeled", *DATA_LABELS}:
            return jsonify(
                code=400,
                message=(
                    "label_status 必须是 all、labeled、unlabeled、正向、"
                    "负向或中性。"
                ),
                data=None,
            ), 400
        filters = []
        if label_status == "labeled":
            filters.append({"exists": {"field": "label"}})
        elif label_status == "unlabeled":
            filters.append({"bool": {"must_not": [{"exists": {"field": "label"}}]}})
        elif label_status in DATA_LABELS:
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"label": label_status}},
                            {"term": {"label.keyword": label_status}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        query = {"bool": {"filter": filters}} if filters else {"match_all": {}}
        try:
            response = get_es_client().search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query=query,
                from_=(page - 1) * page_size,
                size=page_size,
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
                "page": page,
                "page_size": page_size,
            },
        )

    @app.get("/api/data-items/<path:item_id>")
    @login_required
    def get_data_item_detail(item_id: str):
        try:
            response = get_es_client().get(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
            )
        except NotFoundError as error:
            return elastic_error_response(error)
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        return jsonify(code=0, message="ok", data=get_data_item(response))

    @app.put("/api/data-items/<path:item_id>/label")
    @login_required
    def label_data_item(item_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        label = payload.get("label")
        if not isinstance(label, str) or label not in DATA_LABELS:
            return jsonify(
                code=400,
                message=f"label 必须是以下值之一：{', '.join(sorted(DATA_LABELS))}",
                data=None,
            ), 400

        labeled_at = datetime.now(timezone.utc).isoformat()
        try:
            get_es_client().update(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
                doc={
                    "label": label,
                    "labeled_by": session["username"],
                    "labeled_at": labeled_at,
                    "updated_at": labeled_at,
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
            message="标注已保存",
            data={
                "id": str(item_id),
                "label": label,
                "labeled_by": session["username"],
                "labeled_at": labeled_at,
            },
        )

    return app


app = create_app()
