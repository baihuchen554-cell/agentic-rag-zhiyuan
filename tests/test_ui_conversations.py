"""验证真实界面回调的会话选择、删除确认和删除最后一条后的状态。"""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
import config
from core.conversation_store import ConversationStore
from db.parent_store_manager import ParentStoreManager
from rag_agent.graph import create_agent_graph
from test_conversation_memory import MemoryLlm, rag_for, search_child_chunks
from ui.gradio_app import create_gradio_ui


class UiConversationTest(unittest.TestCase):
    def test_selection_stale_confirmation_delete_and_empty_state(self):
        class PreviewRag:
            def __init__(self):
                self.__dict__.update(rag_for(create_agent_graph(MemoryLlm(), [search_child_chunks])).__dict__)
                self.parent_store = ParentStoreManager()

            def initialize(self):
                pass

        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            config, CHAT_HISTORY_PATH=str(Path(directory) / "history.sqlite3"),
            MARKDOWN_DIR=str(Path(directory) / "markdown"), PARENT_STORE_PATH=str(Path(directory) / "parents"),
        ), patch("ui.gradio_app.RAGSystem", PreviewRag):
            demo = create_gradio_ui()
            self.addCleanup(demo.close)
            callbacks = {function.fn.__name__: function.fn for function in demo.fns.values() if function.fn}
            send = callbacks["send_message"]
            stop = callbacks["stop_generation"]
            delete = callbacks["delete_conversation_handler"]
            prepare = callbacks["prepare_conversation_delete"]
            first = list(send("我叫小林。", [], None))[-1]
            first_id = first[2]
            second = list(send("记住这些。", [], None))[-1]
            second_id = second[2]
            store = ConversationStore()
            self.assertEqual(len(first), 11)
            self.assertTrue(first[6]["interactive"])
            confirmation = prepare(first_id)
            self.assertIn("我叫小林", confirmation[1])
            self.assertEqual(confirmation[2], first_id)
            # 在确认框出现后切换会话，旧确认不能删除其他会话。
            delete(first_id, second_id)
            self.assertTrue(store.exists(first_id))
            self.assertTrue(store.exists(second_id))
            after_first = delete(first_id, first_id)
            self.assertEqual(after_first[2], second_id)
            self.assertFalse(store.exists(first_id))
            empty = delete(second_id, second_id)
            self.assertEqual(empty[0], [])
            self.assertFalse(empty[6]["interactive"])
            self.assertFalse(empty[9]["visible"])
            self.assertEqual(store.list_conversations(), [])
            self.assertNotIn(empty[2], {first_id, second_id})
            # 初次响应就切到停止状态，模型未开始时也能立即停止并恢复发送。
            pending = send("我叫小林。", [], None)
            busy = next(pending)
            self.assertFalse(busy[1]["submit_btn"])
            self.assertTrue(busy[1]["stop_btn"])
            stopped = stop(busy[2])
            self.assertTrue(stopped[1]["submit_btn"])
            self.assertFalse(stopped[1]["stop_btn"])
            self.assertIn("已停止生成", stopped[0][-1]["content"])
            tail = list(pending)
            self.assertTrue(tail)
            self.assertTrue(all(packet[1]["submit_btn"] and not packet[1]["stop_btn"] for packet in tail),
                            "停止后的迟到回调不能把按钮改回生成状态")
