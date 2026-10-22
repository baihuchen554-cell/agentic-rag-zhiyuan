"""记忆需跨轮次、跨重启保存，同时在不同会话之间隔离。"""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from core.chat_interface import ChatInterface
from core.conversation_store import ConversationStore, conversation_messages
from rag_agent.graph import create_agent_graph
from rag_agent.schemas import QueryAnalysis


class MemoryLlm:
    def bind_tools(self, _):
        return self

    def with_structured_output(self, _):
        def analyze(messages):
            query = messages[-1].content.rsplit("用户问题：\n", 1)[-1]
            return QueryAnalysis(is_clear=True, questions=[query], clarification_needed="", conversation_only=True)
        return SimpleNamespace(invoke=analyze)

    def invoke(self, messages):
        context = "\n".join(message.content for message in messages)
        if "精简记忆管理器" in messages[0].content:
            return AIMessage(content="用户叫小林，喜欢简短回答。" if "小林" in context else "无个人信息。")
        if "名字" in messages[-1].content:
            return AIMessage(content="你叫小林。" if "小林" in context else "你还没有告诉我名字。")
        return AIMessage(content="好的，记住了。")


@tool
def search_child_chunks(query: str) -> str:
    """纯聊天不应触发此工具。"""
    raise AssertionError("个人信息回顾不应联网或查文档")


def rag_for(graph):
    return SimpleNamespace(agent_graph=graph, thread_id="default", get_config=lambda thread: {
        "configurable": {"thread_id": thread}, "recursion_limit": 50,
    })


class ConversationMemoryTest(unittest.TestCase):
    def test_memory_survives_summary_restart_and_conversation_switch(self):
        with tempfile.TemporaryDirectory() as directory, patch("rag_agent.nodes.PRE_ANSWER_HISTORY_MESSAGES_TO_KEEP", 3):
            path = Path(directory) / "conversations.sqlite3"
            store = ConversationStore(path)
            service = ChatInterface(rag_for(create_agent_graph(MemoryLlm(), [search_child_chunks])), store)
            list(service.chat("我叫小林，回答尽量简短。", [], "first"))
            for question in ("记住这些。", "之后也一样。", "你知道我的名字吗？"):
                reply = list(service.chat(question, [], "first"))[-1]
            self.assertIn("小林", reply[-1]["content"])
            saved = store.get("first")
            self.assertTrue(saved["memory"]["conversation_summary"])
            self.assertEqual(len(conversation_messages(saved["messages"])), 8)
            self.assertEqual(len(saved["messages"]), 12)

            # 新进程的图没有任何内存检查点，只能从本地记录恢复记忆。
            restarted = ChatInterface(rag_for(create_agent_graph(MemoryLlm(), [search_child_chunks])), ConversationStore(path))
            reply = list(restarted.chat("我的名字是什么？", [], "first"))[-1]
            self.assertIn("小林", reply[-1]["content"])
            isolated = list(restarted.chat("我的名字是什么？", [], "second"))[-1]
            self.assertIn("还没有", isolated[-1]["content"])
            again = list(restarted.chat("我的名字是什么？", [], "first"))[-1]
            self.assertIn("小林", again[-1]["content"])
            self.assertEqual(len(store.list_conversations()), 2)

    def test_history_argument_is_used_when_no_checkpoint_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ChatInterface(rag_for(create_agent_graph(MemoryLlm(), [search_child_chunks])),
                                    ConversationStore(Path(directory) / "chat.sqlite3"))
            reply = list(service.chat("我的名字是什么？", [
                {"role": "user", "content": "我叫小林。"},
                {"role": "assistant", "content": "你好。"},
            ], "restored"))[-1]
            self.assertIn("小林", reply[-1]["content"])

    def test_gradio_content_blocks_are_normalized_before_memory_and_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory) / "chat.sqlite3")
            service = ChatInterface(rag_for(create_agent_graph(MemoryLlm(), [search_child_chunks])), store)
            reply = list(service.chat("我的名字是什么？", [
                {"role": "user", "content": [{"type": "text", "text": "我叫小林。"}]},
                {"role": "assistant", "content": [{"type": "text", "text": "你好。"}], "metadata": None},
            ], "gradio-six"))[-1]
            self.assertIn("小林", reply[-1]["content"])
            self.assertEqual(store.get("gradio-six")["messages"][0]["content"], "我叫小林。")
