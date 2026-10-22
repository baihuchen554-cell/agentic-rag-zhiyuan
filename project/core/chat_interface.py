"""整理模型流、保存对话，并支持随时停止当前回答。"""

import json
from threading import RLock
import uuid

from langchain_core.messages import (
    AIMessage, AIMessageChunk, HumanMessage, messages_from_dict, messages_to_dict,
)
from core.conversation_store import ConversationStore, normalize_history, conversation_messages
from core.generation_control import CancellationCallback, Generation, graph_events
from core.execution_logger import log_chat_end, log_chat_start, log_error


def _memory(values):
    result = {key: values[key] for key in (
        "conversation_summary", "pendingQuery", "pendingClarifications", "questionIsClear"
    ) if key in values}
    result["messages"] = messages_to_dict([
        message for message in values.get("messages", [])
        if isinstance(message, (HumanMessage, AIMessage))
        and (not message.name or message.name in {"clarification", "clarification_response"})
        and not getattr(message, "tool_calls", None)
    ])
    return result


class ChatInterface:
    def __init__(self, rag_system, store=None):
        self.rag_system = rag_system
        self.store = store or ConversationStore()
        self._lock = RLock()
        self._active = {}
        self._workflow_ids = {}

    def begin_generation(self, message, history, conversation_id):
        with self._lock:
            if conversation_id in self._active:
                raise ValueError("当前对话正在生成，请先停止。")
            if self.store.is_deleted(conversation_id):
                raise ValueError("此对话已删除，请新建对话。")
            workflow_id = self._workflow_ids.get(conversation_id, conversation_id)
            config = self.rag_system.get_config(workflow_id)
            saved = self.store.get(conversation_id)
            previous = saved["messages"] or normalize_history(history)
            turn = [*previous, {"role": "user", "content": message.strip()}]
            generation = Generation(conversation_id, workflow_id, config,
                                    self.rag_system.agent_graph.get_state(config), saved, turn)
            config["callbacks"] = [*(config.get("callbacks") or []), CancellationCallback(generation.cancelled)]
            self.store.save(conversation_id, turn, saved["memory"])
            self._active[conversation_id] = generation
            return generation

    def _release(self, generation):
        with self._lock:
            if self._active.get(generation.conversation_id) is generation:
                self._active.pop(generation.conversation_id)

    def _clear_checkpoint(self, workflow_id):
        checkpointer = getattr(self.rag_system.agent_graph, "checkpointer", None)
        if checkpointer:
            checkpointer.delete_thread(workflow_id)

    def stop(self, conversation_id):
        with self._lock:
            generation = self._active.get(conversation_id)
        if generation is None:
            return False
        with generation.lock:
            if generation.completed or generation.cancelled.is_set():
                return False
            generation.cancelled.set()
            for event in generation.progress.steps.values():
                if event["status"] == "running":
                    event.update(status="stopped", detail="已停止")
            generation.progress.update({"step": "stop", "title": "已停止生成", "status": "done"})
            partial = generation.answer.strip()
            answer = partial + "\n\n*已停止生成*" if partial else "已停止生成。"
            generation.response = [generation.progress.message(finished=True), {"role": "assistant", "content": answer}]
            memory = dict(generation.saved["memory"])
            restored = messages_from_dict(memory.get("messages", []))
            if not restored:
                restored = [(HumanMessage if item["role"] == "user" else AIMessage)(content=item["content"])
                            for item in conversation_messages(generation.turn[:-1])]
            restored += [HumanMessage(content=generation.turn[-1]["content"]), AIMessage(content=answer)]
            memory.update(messages=messages_to_dict(restored), pendingQuery="", pendingClarifications=[], questionIsClear=True)
            self.store.save(conversation_id, [*generation.turn, *generation.response], memory)
            # 停止中的旧网络调用使用旧检查点；新问题从已保存的记忆开始，互不覆盖。
            with self._lock:
                self._workflow_ids[conversation_id] = conversation_id + ":" + uuid.uuid4().hex
            self._release(generation)
            if generation.worker is None:
                self._clear_checkpoint(generation.workflow_id)
            return True

    def chat(self, message, history, conversation_id=None, generation=None):
        if not self.rag_system.agent_graph:
            yield [{"role": "assistant", "content": "系统尚未初始化，请稍后重试。"}]
            return
        conversation_id = conversation_id or self.rag_system.thread_id
        if self.store.is_deleted(conversation_id):
            yield [{"role": "assistant", "content": "此对话已删除，请新建对话后再发送。"}]
            return
        run = generation or self.begin_generation(message, history, conversation_id)
        graph = self.rag_system.agent_graph
        awaiting_clarification = "request_clarification" in run.state.next
        log_chat_start(message.strip(), conversation_id, awaiting_clarification)

        def response(finished=False):
            return [run.progress.message(finished), *([{"role": "assistant", "content": run.answer}] if run.answer else [])]

        try:
            if run.cancelled.is_set():
                yield run.response
                return
            yield response()
            if run.cancelled.is_set():
                yield run.response
                return
            if awaiting_clarification:
                graph.update_state(run.config, {"messages": [HumanMessage(content=message.strip())]})
                stream_input = None
            else:
                stream_input = {"messages": [HumanMessage(content=message.strip())]}
                if not getattr(run.state, "values", {}):
                    memory = dict(run.saved["memory"])
                    restored = messages_from_dict(memory.pop("messages", []))
                    if not restored:
                        restored = [(HumanMessage if item["role"] == "user" else AIMessage)(content=item["content"])
                                    for item in conversation_messages(run.turn[:-1])]
                    stream_input = {**memory, "messages": [*restored, HumanMessage(content=message.strip())]}

            rewrite_buffer = ""
            for _, mode, payload in graph_events(graph, stream_input, run, self._clear_checkpoint):
                with run.lock:
                    if run.cancelled.is_set():
                        break
                    if mode == "custom":
                        if isinstance(payload, dict) and payload.get("type") == "process":
                            run.progress.update(payload)
                        else:
                            continue
                    else:
                        chunk, metadata = payload
                        node = metadata.get("langgraph_node", "")
                        if not isinstance(chunk, AIMessageChunk):
                            continue
                        if node in {"aggregate_answers", "conversation_answer"} and isinstance(chunk.content, str):
                            run.answer += chunk.content
                        elif node == "rewrite_query" and chunk.tool_call_chunks:
                            rewrite_buffer += "".join(call.get("args", "") or "" for call in chunk.tool_call_chunks)
                            try:
                                analysis = json.loads(rewrite_buffer)
                            except (ValueError, TypeError):
                                continue
                            if not analysis.get("is_clear") and analysis.get("clarification_needed"):
                                run.answer = analysis["clarification_needed"]
                        else:
                            continue
                    update = response()
                yield update

            with run.lock:
                if run.cancelled.is_set():
                    final = run.response
                else:
                    values = graph.get_state(run.config).values
                    log_chat_end(values)
                    if values.get("messages"):
                        final_message = values["messages"][-1]
                        if isinstance(final_message, AIMessage) and final_message.content:
                            run.answer = str(final_message.content)
                    run.answer = run.answer or "暂时没有生成回答，请重试。"
                    final = response(finished=True)
                    self.store.save(conversation_id, [*run.turn, *final], _memory(values))
                    run.completed = True
            yield final
        except Exception as exc:
            with run.lock:
                if run.cancelled.is_set():
                    final = run.response
                else:
                    log_error("chat", exc)
                    error = str(exc) if str(exc).startswith("知识库检索失败") else "请求失败，请检查模型 API、网络连接后重试。"
                    run.progress.update({"step": "request_error", "title": "请求未完成", "status": "error", "detail": error})
                    run.answer = error
                    final = response(finished=True)
                    self.store.save(conversation_id, [*run.turn, *final], run.saved["memory"])
                    run.completed = True
            yield final
        finally:
            if not run.completed and not run.cancelled.is_set():
                self.stop(conversation_id)
            self._release(run)

    def delete_conversation(self, conversation_id):
        if not conversation_id or not self.store.exists(conversation_id):
            return False
        self.stop(conversation_id)
        with self._lock:
            workflow_id = self._workflow_ids.get(conversation_id, conversation_id)
        self._clear_checkpoint(workflow_id)
        if workflow_id != conversation_id:
            self._clear_checkpoint(conversation_id)
        deleted = self.store.delete(conversation_id)
        with self._lock:
            self._workflow_ids.pop(conversation_id, None)
        return deleted
