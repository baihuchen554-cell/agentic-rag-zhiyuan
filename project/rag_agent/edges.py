from typing import Literal
from langgraph.types import Send
from .graph_state import State, AgentState
from config import MAX_ITERATIONS, MAX_TOOL_CALLS
from core.execution_logger import log_route
from core.web_search import NEED_WEB_SEARCH


def route_after_local_answer(state: AgentState) -> Literal["web_fallback", "collect_answer"]:
    if state.get("web_search_attempted"):
        return "collect_answer"
    answer = str(state["messages"][-1].content)
    has_evidence = bool(state.get("retrieved_contexts") or state.get("context_summary", "").strip())
    return "web_fallback" if NEED_WEB_SEARCH in answer or not has_evidence else "collect_answer"


def route_after_rewrite(state: State) -> Literal["request_clarification", "agent", "conversation_answer"]:
    # 根据问题是否清晰，决定请求用户补充信息还是启动智能体
    if not state.get("questionIsClear", False):
        decision = "request_clarification"
    elif state.get("conversation_only", False):
        decision = "conversation_answer"
    else:
        # 将改写后的每个问题分别发送给 agent 节点，进行并行处理
        decision = [
            Send("agent", {"question": query, "question_index": idx, "messages": [],
                           "original_question": state.get("originalQuery", query),
                           "conversation_context": state.get("conversation_summary", "") + "\n" + "\n".join(
                               f"{message.type}：{message.content}" for message in state.get("messages", [])
                               if not getattr(message, "name", None) and not getattr(message, "tool_calls", None))})
            for idx, query in enumerate(state["rewrittenQuestions"])
        ]

    # 记录路由决策及当前工作流状态
    log_route("after_rewrite", decision, state)
    return decision


def route_after_orchestrator_call(state: AgentState) -> Literal["tools", "fallback_response", "web_fallback", "collect_answer"]:
    # 获取当前迭代次数和工具调用次数
    iteration = state.get("iteration_count", 0)
    tool_count = state.get("tool_call_count", 0)

    # 获取最近一条消息，以及模型请求调用的工具
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []

    # 模型结束本地检索时，判断直接收集答案还是交给联网分支。
    if not tool_calls:
        decision = route_after_local_answer(state)
        log_route("after_orchestrator_call", decision, state)
        return decision

    # 计数器已经包含当前模型响应产生的次数。
    # 如果达到迭代上限或工具调用预算超限，则停止继续调用工具并生成备用回答。
    if iteration >= MAX_ITERATIONS or tool_count > MAX_TOOL_CALLS:
        decision = "fallback_response"
        log_route("after_orchestrator_call", decision, state)
        return decision

    # 未超过执行限制，继续执行工具调用
    decision = "tools"
    log_route("after_orchestrator_call", decision, state)
    return decision
