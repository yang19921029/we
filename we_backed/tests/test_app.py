import unittest
from unittest.mock import patch

from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch.exceptions import NotFoundError
from werkzeug.security import generate_password_hash

from app import create_app


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=()):
        if "FROM users" in query:
            if "WHERE username" in query and params[0] == "tester":
                self.result = {
                    "id": 7,
                    "username": "tester",
                    "password_hash": generate_password_hash("correct-password"),
                }
            elif "WHERE id" in query and params[0] == 7:
                self.result = {"id": 7, "username": "tester"}
            else:
                self.result = None
        elif "FROM menus" in query and "WHERE id =" in query:
            self.result = {"id": params[0]} if params[0] == 2 else None
        elif "WHERE parent_id IS NULL" in query:
            self.result = [
                {"id": 1, "name": "首页", "path": "/dashboard"},
                {"id": 2, "name": "数据标注", "path": "/data/list"},
                {"id": 4, "name": "质量管理", "path": "/operations"},
                {"id": 5, "name": "规范与帮助", "path": "/policies"},
            ]
        elif "WHERE parent_id =" in query:
            self.result = [
                {
                    "id": 7,
                    "name": "数据展示列表",
                    "path": "/data/list",
                    "parent_id": 2,
                },
                {
                    "id": 8,
                    "name": "数据打标",
                    "path": "/data/label",
                    "parent_id": 2,
                },
            ]
        else:
            raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class FakeDatabase:
    def cursor(self):
        return FakeCursor(self)


class FakeIndices:
    def __init__(self):
        self.created = False
        self.mapping = None
        self.settings = None

    def exists(self, *, index):
        return self.created

    def create(self, *, index, mappings, settings):
        self.created = True
        self.mapping = mappings
        self.settings = settings

    def put_settings(self, *, index, settings):
        self.settings = settings


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

    def search(self, *, index, query, from_, size, track_total_hits):
        item_ids = list(self.items)
        if query.get("bool", {}).get("filter"):
            filter_query = query["bool"]["filter"][0]
            if "should" in filter_query.get("bool", {}):
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
        selected_ids = item_ids[from_ : from_ + size]
        return {
            "hits": {
                "total": {"value": len(item_ids), "relation": "eq"},
                "hits": [
                    {"_id": item_id, "_source": self.items[item_id]}
                    for item_id in selected_ids
                ],
            }
        }

    def get(self, *, index, id):
        if id not in self.items:
            raise self.missing_document()
        return {"_id": id, "_source": self.items[id]}

    def update(self, *, index, id, doc, doc_as_upsert, refresh):
        if id not in self.items:
            raise self.missing_document()
        self.items[id].update(doc)

    def index(self, *, index, id, document, refresh):
        self.items[id] = document
        self.indexed_documents.append(id)

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
        self.db_patcher.start()
        self.es_patcher.start()

    def tearDown(self):
        self.db_patcher.stop()
        self.es_patcher.stop()

    def test_login_rejects_invalid_password(self):
        response = self.client.post(
            "/api/login",
            json={"username": "tester", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

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
            ["首页", "数据标注", "质量管理", "规范与帮助"],
        )

        second_level = self.client.get("/api/menus/2/children")
        self.assertEqual(second_level.status_code, 200)
        self.assertEqual(
            [menu["name"] for menu in second_level.json["data"]],
            ["数据展示列表", "数据打标"],
        )
        self.assertEqual(
            [menu["path"] for menu in second_level.json["data"]],
            ["/data/list", "/data/label"],
        )

    def test_menu_endpoints_require_login(self):
        response = self.client.get("/api/menus")
        self.assertEqual(response.status_code, 401)

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
