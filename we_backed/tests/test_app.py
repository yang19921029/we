import json
import unittest
from unittest.mock import patch

from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch.exceptions import NotFoundError
from werkzeug.security import generate_password_hash

from app import create_app, request_ai_preannotation


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.result = None
        self.rowcount = 0

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
    def __init__(self):
        self.member_project_ids = set()
        self.member_relations = set()
        self.dataset_projects = {1: 1, 2: 2}

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        return None


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
        self.search_queries = []

    def search(
        self,
        *,
        index,
        query,
        from_=0,
        size=10,
        track_total_hits=True,
        sort=None,
        aggregations=None,
    ):
        self.search_queries.append(query)
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
        selected_ids = item_ids[from_ : from_ + size]
        response = {
            "hits": {
                "total": {"value": len(item_ids), "relation": "eq"},
                "hits": [
                    {"_id": item_id, "_source": self.items[item_id]}
                    for item_id in selected_ids
                ],
            }
        }
        if aggregations is not None:
            response["aggregations"] = {
                name: {"buckets": []} for name in aggregations
            }
        return response

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
