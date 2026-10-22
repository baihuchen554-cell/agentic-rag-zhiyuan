"""验证结构化函数参数分片在聊天界面中的中文显示。"""

import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from core.chat_interface import ChatInterface
from core.conversation_store import ConversationStore
from langchain_core.messages import AIMessageChunk


class RewriteDisplayTest(unittest.TestCase):
    def test_streamed_clarification_is_displayed_as_analysis(self):
        clarification = "请说明你想查询哪一份文档的借阅期限。"
        payload = json.dumps({"is_clear": False, "questions": [],
                              "clarification_needed": clarification}, ensure_ascii=False)
        events = []
        for offset in range(0, len(payload), 8):
            chunk = AIMessageChunk(content="", tool_call_chunks=[{
                "index": 0, "id": "rewrite" if offset == 0 else None,
                "name": "QueryAnalysis" if offset == 0 else None,
                "args": payload[offset:offset + 8],
            }])
            events.append(((), "messages", (chunk, {"langgraph_node": "rewrite_query"})))
        graph = SimpleNamespace(
            get_state=lambda _: SimpleNamespace(next=(), values={}),
            stream=lambda *args, **kwargs: iter(events),
        )
        rag = SimpleNamespace(agent_graph=graph, get_config=lambda _: {}, thread_id="test")
        with tempfile.TemporaryDirectory() as directory:
            updates = list(ChatInterface(rag, ConversationStore(Path(directory) / "chat.sqlite3")).chat("它的借阅期限呢？", []))
        messages = updates[-1]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["metadata"]["title"], "处理过程")
        self.assertEqual(messages[0]["metadata"]["status"], "done")
        self.assertEqual(messages[-1]["content"], clarification)
        self.assertNotIn("QueryAnalysis", str(messages))


if __name__ == "__main__":
    unittest.main()
