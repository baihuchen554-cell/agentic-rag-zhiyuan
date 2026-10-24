"""登录配置与真实 Gradio HTTP 鉴权测试，不加载模型或调用外部 API。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from core.web_auth import get_web_auth


class WebAuthConfigTests(unittest.TestCase):
    def test_local_default_stays_optional(self):
        self.assertIsNone(get_web_auth({}))

    def test_required_or_partial_configuration_fails_closed(self):
        for env in (
            {"WEB_AUTH_REQUIRED": "true"},
            {"WEB_AUTH_USERNAME": "owner"},
            {"WEB_AUTH_PASSWORD": "test-password-only"},
            {"WEB_AUTH_REQUIRED": "treu"},
            {"WEB_AUTH_USERNAME": "owner", "WEB_AUTH_PASSWORD": "short"},
            {"WEB_AUTH_USERNAME": "owner", "WEB_AUTH_PASSWORD": " " * 15},
        ):
            with self.subTest(fields=list(env)):
                with self.assertRaises(ValueError):
                    get_web_auth(env)

    def test_credentials_enable_login_and_preserve_password(self):
        self.assertEqual(get_web_auth({
            "WEB_AUTH_USERNAME": " owner ",
            "WEB_AUTH_PASSWORD": "  test-password-only  ",
        }), ("owner", "  test-password-only  "))

    def test_error_does_not_disclose_password(self):
        with self.assertRaises(ValueError) as error:
            get_web_auth({"WEB_AUTH_PASSWORD": "test-private-value"})
        self.assertNotIn("test-private-value", str(error.exception))


class WebAuthHttpTests(unittest.TestCase):
    def test_login_protects_api_and_logout_revokes_access(self):
        import gradio as gr
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        auth = get_web_auth({
            "WEB_AUTH_REQUIRED": "true",
            "WEB_AUTH_USERNAME": "owner",
            "WEB_AUTH_PASSWORD": "test-password-only",
        })
        with gr.Blocks(analytics_enabled=False) as demo:
            text = gr.Textbox()
            button = gr.Button("Echo")
            button.click(lambda value: value, text, text, api_name="echo")
        app = gr.mount_gradio_app(FastAPI(), demo, path="/", auth=auth)
        with TestClient(app) as client:
            self.assertEqual(client.get("/gradio_api/login_check").status_code, 401)
            self.assertEqual(client.post("/gradio_api/upload").status_code, 401)
            self.assertEqual(client.post("/gradio_api/api/echo", json={"data": ["hello"]}).status_code, 401)
            self.assertEqual(client.post("/login", data={
                "username": "owner", "password": "wrong-password",
            }).status_code, 400)
            self.assertEqual(client.get("/gradio_api/login_check").status_code, 401)
            self.assertEqual(client.post("/login", data={
                "username": "owner", "password": "test-password-only",
            }).status_code, 200)
            self.assertEqual(client.get("/gradio_api/login_check").status_code, 200)
            response = client.post("/gradio_api/api/echo", json={"data": ["hello"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"], ["hello"])
            client.get("/logout")
            self.assertEqual(client.get("/gradio_api/login_check").status_code, 401)


if __name__ == "__main__":
    unittest.main()
