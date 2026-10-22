"""停止必须迅速返回、保存部分答案，且旧网络响应不能覆盖新一轮。"""

from pathlib import Path
import sys
import tempfile
from threading import Event
from time import perf_counter
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
from langchain_core.messages import AIMessage, AIMessageChunk
from core.chat_interface import ChatInterface
from core.conversation_store import ConversationStore
from core.generation_control import CancellationCallback, GenerationStopped


class ControlledGraph:
    def __init__(self):
        self.release_old = Event()
        self.waiting = Event()
        self.states = {}
        self.calls = []
        self.checkpointer = SimpleNamespace(delete_thread=lambda thread: self.states.pop(thread, None))

    def get_state(self, config):
        return SimpleNamespace(next=(), values=self.states.get(config["configurable"]["thread_id"], {}))

    def stream(self, stream_input, config, **kwargs):
        thread = config["configurable"]["thread_id"]
        self.calls.append(thread)
        question = stream_input["messages"][-1].content
        if question == "慢问题":
            yield ((), "messages", (AIMessageChunk(content="已经生成的部分"), {"langgraph_node": "aggregate_answers"}))
            self.waiting.set()
            self.release_old.wait(5)
            # 模拟底层网络在用户停止后才返回内容。
            yield ((), "messages", (AIMessageChunk(content="不应出现的旧回答"), {"langgraph_node": "aggregate_answers"}))
        else:
            self.states[thread] = {"messages": [*stream_input["messages"], AIMessage(content="新回答")]}
            yield ((), "messages", (AIMessageChunk(content="新回答"), {"langgraph_node": "aggregate_answers"}))


class GenerationStopTest(unittest.TestCase):
    def service(self, directory, graph):
        rag = SimpleNamespace(agent_graph=graph, thread_id="default",
                              get_config=lambda thread: {"configurable": {"thread_id": thread}})
        return ChatInterface(rag, ConversationStore(Path(directory) / "history.sqlite3"))

    def test_stop_preserves_partial_answer_and_allows_next_request_before_old_response(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = ControlledGraph()
            service = self.service(directory, graph)
            iterator = service.chat("慢问题", [], "chat")
            next(iterator)
            partial = next(iterator)
            self.assertIn("已经生成的部分", partial[-1]["content"])
            self.assertTrue(graph.waiting.wait(1))
            run = service._active["chat"]
            start = perf_counter()
            self.assertTrue(service.stop("chat"))
            stopped = list(iterator)[-1]
            self.assertLess(perf_counter() - start, 1)
            self.assertIn("已经生成的部分", stopped[-1]["content"])
            self.assertIn("已停止生成", stopped[-1]["content"])
            self.assertEqual(stopped[0]["metadata"]["status"], "done")
            # 旧请求尚未返回，新请求已能使用独立检查点完成。
            answer = list(service.chat("新问题", [], "chat"))[-1]
            self.assertEqual(answer[-1]["content"], "新回答")
            self.assertNotEqual(graph.calls[0], graph.calls[1])
            graph.release_old.set()
            run.worker.join(2)
            self.assertFalse(run.worker.is_alive())
            saved = service.store.get("chat")["messages"]
            self.assertEqual(saved[-1]["content"], "新回答")
            self.assertNotIn("不应出现", str(saved))
            self.assertFalse(service.stop("chat"))

    def test_stop_before_model_starts_does_not_call_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = ControlledGraph()
            service = self.service(directory, graph)
            generation = service.begin_generation("慢问题", [], "chat")
            self.assertTrue(service.stop("chat"))
            reply = list(service.chat("慢问题", [], "chat", generation=generation))[-1]
            self.assertIn("已停止生成", reply[-1]["content"])
            self.assertEqual(graph.calls, [])

    def test_cancelled_model_and_tool_callbacks_abort_further_work(self):
        event = Event()
        callback = CancellationCallback(event)
        callback.on_llm_new_token("正常片段")
        event.set()
        with self.assertRaises(GenerationStopped):
            callback.on_llm_new_token("迟到片段")
        with self.assertRaises(GenerationStopped):
            callback.on_tool_start({}, "query")
