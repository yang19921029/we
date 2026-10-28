import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import create_app


class FakeCursor:
    def __init__(self):
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
        elif "WHERE id =" in query:
            self.result = {"id": params[0]} if params[0] == 2 else None
        elif "WHERE parent_id IS NULL" in query:
            self.result = [
                {"id": 1, "name": "工作台", "path": "/dashboard"},
                {"id": 2, "name": "系统管理", "path": "/system"},
                {"id": 5, "name": "报表中心", "path": "/reports"},
            ]
        elif "WHERE parent_id =" in query:
            self.result = [
                {
                    "id": 3,
                    "name": "用户管理",
                    "path": "/system/users",
                    "parent_id": 2,
                },
                {
                    "id": 4,
                    "name": "角色管理",
                    "path": "/system/roles",
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
        return FakeCursor()


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
            }
        )
        self.client = self.app.test_client()
        self.db_patcher = patch("app.get_db", return_value=FakeDatabase())
        self.db_patcher.start()

    def tearDown(self):
        self.db_patcher.stop()

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
            ["工作台", "系统管理", "报表中心"],
        )

        second_level = self.client.get("/api/menus/2/children")
        self.assertEqual(second_level.status_code, 200)
        self.assertEqual(
            [menu["name"] for menu in second_level.json["data"]],
            ["用户管理", "角色管理"],
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


if __name__ == "__main__":
    unittest.main()
