"""删除会话必须同时移除磁盘记录和模型记忆，并保留其他会话。"""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "project")]
from core.chat_interface import ChatInterface
from core.conversation_store import ConversationStore
from rag_agent.graph import create_agent_graph
from test_conversation_memory import MemoryLlm, rag_for, search_child_chunks


class ConversationDeletionTest(unittest.TestCase):
    def test_delete_selected_conversation_and_memory_preserves_other_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            store = ConversationStore(path)
            graph = create_agent_graph(MemoryLlm(), [search_child_chunks])
            rag = rag_for(graph)
            service = ChatInterface(rag, store)
            list(service.chat("我叫小林。", [], "delete-me"))
            list(service.chat("记住这些。", [], "keep-me"))
            self.assertTrue(graph.get_state(rag.get_config("delete-me")).values)
            self.assertTrue(service.delete_conversation("delete-me"))
            self.assertFalse(graph.get_state(rag.get_config("delete-me")).values)
            self.assertTrue(graph.get_state(rag.get_config("keep-me")).values)
            reopened = ConversationStore(path)
            self.assertFalse(reopened.exists("delete-me"))
            self.assertEqual([cid for _, cid in reopened.list_conversations()], ["keep-me"])
            self.assertFalse(service.delete_conversation("delete-me"))
            # 另一个旧页面再次发送，也不能从浏览器中的旧消息复活已删除的记忆。
            reply = list(service.chat("我的名字是什么？", [{"role": "user", "content": "我叫小林。"}], "delete-me"))[-1]
            self.assertIn("此对话已删除", reply[-1]["content"])
            with self.assertRaisesRegex(ValueError, "已删除"):
                reopened.save("delete-me", [{"role": "user", "content": "重建"}], {})

    def test_checkpoint_failure_keeps_history_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(Path(directory) / "history.sqlite3")
            graph = create_agent_graph(MemoryLlm(), [search_child_chunks])
            service = ChatInterface(rag_for(graph), store)
            list(service.chat("我叫小林。", [], "retry"))
            with patch.object(graph.checkpointer, "delete_thread", side_effect=RuntimeError("checkpoint error")):
                with self.assertRaises(RuntimeError):
                    service.delete_conversation("retry")
            self.assertTrue(store.exists("retry"))
            self.assertFalse(store.is_deleted("retry"))
