"""验证助手身份与 SVG 图标在真实 HTTP 路由中的行为。"""

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
import config
from rag_agent.nodes import conversation_answer


class BrandingTests(unittest.TestCase):
    def test_assistant_identity_follows_brand_and_preserves_memory(self):
        messages = []
        def invoke(value):
            messages.extend(value)
            return SimpleNamespace(content="你好")
        with patch.object(config, "APP_NAME", "test-brand"):
            result = conversation_answer({"messages": [], "conversation_summary": "用户喜欢简短回答"},
                                         SimpleNamespace(invoke=invoke))
        self.assertIn("你是 test-brand 助手", messages[0].content)
        self.assertIn("用户喜欢简短回答", messages[0].content)
        self.assertEqual(result["messages"][0].content, "你好")

    def test_svg_is_served_as_image_and_used_in_manifest(self):
        import gradio as gr
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        svg = Path(config.APP_LOGO_PATH)
        self.assertEqual(ET.parse(svg).getroot().tag, "{http://www.w3.org/2000/svg}svg")
        with gr.Blocks(title=config.APP_TITLE, analytics_enabled=False) as demo:
            gr.Markdown(config.APP_NAME)
        app = gr.mount_gradio_app(FastAPI(), demo, path="/", favicon_path=str(svg))
        with TestClient(app) as client:
            response = client.get("/favicon.ico")
            self.assertEqual(response.status_code, 200)
            self.assertIn("image/svg+xml", response.headers["content-type"])
            self.assertEqual(response.content, svg.read_bytes())
            self.assertEqual(client.get("/manifest.json").json()["icons"][0]["type"], "image/svg+xml")


if __name__ == "__main__":
    unittest.main()
