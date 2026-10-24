"""可中止的模型流：界面不必等待当前网络请求返回才能停止。"""

from asyncio import CancelledError
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from core.process_status import ProcessStatus


class GenerationStopped(CancelledError):
    """用户主动停止，不作为模型或应用错误展示。"""


class CancellationCallback(BaseCallbackHandler):
    raise_error = True
    run_inline = True

    def __init__(self, event):
        self.event = event

    def check(self, *args, **kwargs):
        if self.event.is_set():
            raise GenerationStopped("用户已停止生成")

    on_chain_start = check
    on_chain_end = check
    on_chat_model_start = check
    on_llm_start = check
    on_llm_new_token = check
    on_llm_end = check
    on_tool_start = check
    on_tool_end = check
    on_retriever_start = check


@dataclass
class Generation:
    conversation_id: str
    workflow_id: str
    config: dict
    state: Any
    saved: dict
    turn: list
    progress: ProcessStatus = field(default_factory=ProcessStatus)
    cancelled: Event = field(default_factory=Event)
    lock: Any = field(default_factory=RLock)
    answer: str = ""
    response: list = field(default_factory=list)
    completed: bool = False
    worker: Any = None
    release_resources: Any = None

    def release_capacity(self):
        if self.release_resources:
            self.release_resources()


def graph_events(graph, stream_input, generation, on_cancelled_exit):
    """后台读取模型；前台轮询取消标记，停止后不再转发旧事件。"""
    events = Queue(maxsize=128)

    def offer(kind, payload):
        while not generation.cancelled.is_set():
            try:
                events.put((kind, payload), timeout=0.05)
                return
            except Full:
                continue

    def produce():
        iterator = None
        try:
            if generation.cancelled.is_set():
                return
            iterator = iter(graph.stream(stream_input, config=generation.config,
                                         stream_mode=["messages", "custom"], subgraphs=True))
            for event in iterator:
                if generation.cancelled.is_set():
                    break
                offer("event", event)
        except GenerationStopped:
            pass
        except Exception as exc:
            offer("error", exc)
        finally:
            if iterator is not None and hasattr(iterator, "close"):
                try:
                    iterator.close()
                except GenerationStopped:
                    pass
                except Exception as exc:
                    offer("error", exc)
            try:
                if generation.cancelled.is_set():
                    on_cancelled_exit(generation.workflow_id)
            finally:
                generation.release_capacity()
                offer("end", None)

    generation.worker = Thread(target=produce, name="rag-generation", daemon=True)
    generation.worker.start()
    while not generation.cancelled.is_set():
        try:
            kind, payload = events.get(timeout=0.05)
        except Empty:
            continue
        if generation.cancelled.is_set() or kind == "end":
            return
        if kind == "error":
            raise payload
        yield payload
