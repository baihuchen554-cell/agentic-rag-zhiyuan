"""页面展示真实执行摘要，持久化后保留折叠状态，不回灌到模型记忆。"""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
from core.chat_interface import ChatInterface
from core.conversation_store import ConversationStore, conversation_messages
from core.process_status import retrieval_summary
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from rag_agent.graph import create_agent_graph
from test_conversation_memory import rag_for
from test_web_fallback import TestLlm, SOURCES


class ProcessStatusTest(unittest.TestCase):
    def test_real_graph_emits_ordered_local_and_web_summaries_and_persists_them(self):
        @tool
        def search_child_chunks(query: str) -> str:
            """搜索文档。"""
            return "NO_RELEVANT_CHUNKS"

        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory) / "history.sqlite3")
            rag = rag_for(create_agent_graph(TestLlm("[NEED_WEB_SEARCH]"), [search_child_chunks]))
            with patch("rag_agent.nodes.WebSearchClient.search", return_value=SOURCES):
                updates = list(ChatInterface(rag, store).chat("学校有几个学院？", [], "process"))
            process = updates[-1][0]
            self.assertEqual(process["metadata"]["status"], "done")
            self.assertGreaterEqual(process["metadata"]["duration"], 0)
            self.assertLess(process["content"].index("检索知识库"), process["content"].index("联网补充"))
            self.assertIn("1 个网站来源", process["content"])
            self.assertTrue(any(message[0]["metadata"]["status"] == "pending" for message in updates))
            self.assertNotIn("NO_RELEVANT_CHUNKS", str(updates))
            saved = store.get("process")["messages"]
            self.assertEqual(saved[1]["metadata"]["status"], "done")
            self.assertEqual(len(conversation_messages(saved)), 2)
            self.assertNotIn("处理过程", str(store.get("process")["memory"]))

    def test_retrieval_summary_does_not_expose_document_body(self):
        summary = retrieval_summary("父文档块标识：abc\n文件名：手册.pdf\n内容：不应展示的整段正文")
        self.assertIn("手册.pdf", summary)
        self.assertNotIn("不应展示的整段正文", summary)
        self.assertNotIn("abc", summary)
