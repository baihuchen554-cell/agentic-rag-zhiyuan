from __future__ import annotations

from datetime import datetime
from pprint import pformat
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.types import Send
from core.display_text import display_log_value, display_name, display_tool_result

import config
from core.process_status import emit_process, node_summary, retrieval_summary


# 终端日志的颜色配置，用于区分不同类型的输出
COLORS = {
    "blue": "\033[94m",
    "cyan": "\033[96m",
    "green": "\033[92m",
    "magenta": "\033[95m",
    "red": "\033[91m",
    "yellow": "\033[93m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _enabled() -> bool:
    # 根据配置判断是否启用执行日志
    return bool(getattr(config, "EXECUTION_LOGGING_ENABLED", True))


def _color(text: str, color: str) -> str:
    # 根据配置决定是否为日志添加颜色
    if not getattr(config, "EXECUTION_LOG_USE_COLOR", True):
        return text
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def _truncate(value: Any, max_chars: int | None = None) -> str:
    # 将内容转换为字符串，并限制日志输出长度
    text = "" if value is None else str(value)
    limit = max_chars or getattr(config, "EXECUTION_LOG_MAX_CHARS", 1200)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [已截断 {len(text) - limit} 个字符]"


def _message_role(message: Any) -> str:
    # 根据 LangChain 消息对象的类型，返回对应的中文名称
    if isinstance(message, HumanMessage):
        return "用户"
    if isinstance(message, AIMessage):
        return "助手"
    if isinstance(message, ToolMessage):
        return "工具"
    if isinstance(message, SystemMessage):
        return "系统"
    if isinstance(message, RemoveMessage):
        return "删除消息"
    return message.__class__.__name__


def _message_preview(message: Any) -> dict[str, Any]:
    # 提取单条消息的关键信息，生成便于查看的日志摘要
    preview = {
        "type": _message_role(message),
        "id": getattr(message, "id", None),
    }

    # 删除消息只记录类型和 ID，不需要提取其他内容
    if isinstance(message, RemoveMessage):
        return preview

    content = getattr(message, "content", "")
    if content:
        if isinstance(message, ToolMessage):
            content = display_tool_result(str(content))
        preview["content"] = _truncate(content)

    # 如果消息包含工具调用，则记录工具名称、参数和调用 ID
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        preview["tool_calls"] = [
            {
                "name": call.get("name"),
                "args": call.get("args"),
                "id": call.get("id"),
            }
            for call in tool_calls
        ]

    # 记录工具名称和对应的工具调用 ID
    tool_name = getattr(message, "name", None)
    if tool_name:
        preview["name"] = tool_name

    tool_call_id = getattr(message, "tool_call_id", None)
    if tool_call_id:
        preview["tool_call_id"] = tool_call_id

    return preview


def _messages_preview(messages: list[Any]) -> dict[str, Any]:
    # 统计消息总数，并只展示最近 4 条消息的摘要
    return {
        "count": len(messages),
        "last_messages": [_message_preview(message) for message in messages[-4:]],
    }


def state_preview(state: Any) -> dict[str, Any]:
    # 将工作流状态整理成适合打印的摘要
    if not isinstance(state, dict):
        return {"value": _truncate(state)}

    preview: dict[str, Any] = {}

    for key, value in state.items():
        if key == "messages":
            # 消息列表单独处理，减少日志输出量
            preview[key] = _messages_preview(value or [])

        elif key in {"conversation_summary", "context_summary", "final_answer"}:
            # 对摘要和最终回答限制输出长度
            preview[key] = _truncate(value)

        elif key == "agent_answers":
            # 统计智能体回答数量，并最多展示前 3 条
            preview[key] = {
                "count": len(value or []),
                "items": [
                    {
                        "index": item.get("index"),
                        "question": _truncate(item.get("question", ""), 240),
                        "answer": _truncate(item.get("answer", ""), 500),
                    }
                    for item in (value or [])[:3]
                    if isinstance(item, dict)
                ],
            }

        elif isinstance(value, set):
            # 将集合转换成排序后的列表，便于阅读
            preview[key] = sorted(value)

        else:
            preview[key] = value

    return preview


def update_preview(update: Any) -> Any:
    # 整理工作流节点返回的状态更新内容
    if not isinstance(update, dict):
        return _truncate(update)

    preview: dict[str, Any] = {}

    for key, value in update.items():
        if key == "messages":
            # 提取每条消息的关键信息
            preview[key] = [_message_preview(message) for message in value]

        elif key in {"conversation_summary", "context_summary", "final_answer"}:
            preview[key] = _truncate(value)

        elif key == "agent_answers":
            # 复用状态摘要逻辑处理智能体回答列表
            preview[key] = state_preview({"agent_answers": value})["agent_answers"]

        elif isinstance(value, set):
            preview[key] = sorted(value)

        else:
            preview[key] = value

    return preview


def _print_block(title: str, payload: Any, color: str) -> None:
    # 统一打印日志，包含时间、标题和具体内容
    if not _enabled():
        return

    timestamp = datetime.now().strftime("%H:%M:%S")
    print(_color(f"\n[{timestamp}] {title}", color))
    print(_color("-" * 80, "dim"))
    print(pformat(display_log_value(payload), width=120, sort_dicts=False))


def log_chat_start(message: str, thread_id: str, has_pending_interrupt: bool) -> None:
    # 记录用户提问、会话 ID，以及工作流是否处于等待状态
    _print_block(
        "用户提问",
        {
            "thread_id": thread_id,
            "pending_interrupt": has_pending_interrupt,
            "message": _truncate(message),
        },
        "blue",
    )


def log_chat_end(state: Any) -> None:
    # 记录本轮聊天结束时的最终工作流状态
    _print_block("最终工作流状态", state_preview(state), "blue")


def log_node_start(name: str, state: Any) -> None:
    # 记录某个工作流节点开始执行时的状态
    _print_block(f"节点开始执行：{display_name(name)}", state_preview(state), "cyan")


def log_node_end(name: str, update: Any) -> None:
    # 记录工作流节点执行完成后返回的内容
    _print_block(f"节点输出：{display_name(name)}", update_preview(update), "green")


def log_route(name: str, decision: Any, state: Any | None = None) -> None:
    # 记录条件路由节点的判断结果，以及可选的当前状态
    # 只转换日志预览，保留路由器实际返回的 Send 对象和节点名称。
    route_preview = [
        {"node": item.node, "args": state_preview(item.arg)}
        if isinstance(item, Send) else item
        for item in decision
    ] if isinstance(decision, list) else decision
    payload = {"decision": _truncate(display_log_value(route_preview, "decision"))}
    if state is not None:
        payload["state"] = state_preview(state)
    _print_block(f"路由决策：{display_name(name)}", payload, "yellow")


def log_tool_start(name: str, args: dict[str, Any]) -> None:
    emit_process(name, "running")
    # 记录工具开始执行时的名称和参数
    _print_block(f"工具开始执行：{display_name(name)}", args, "magenta")


def log_tool_end(name: str, output: Any) -> None:
    emit_process(name, "done", retrieval_summary(output))
    # 记录工具执行完成后的输出
    _print_block(
        f"工具执行结果：{display_name(name)}",
        {"output": _truncate(output)},
        "magenta",
    )


def log_error(scope: str, error: Exception) -> None:
    # 记录异常发生的位置、异常类型和具体错误信息
    _print_block(
        f"发生错误：{display_name(scope)}",
        {
            "type": error.__class__.__name__,
            "message": str(error),
        },
        "red",
    )


def logged_node(name: str, fn):
    # 使用装饰器统一记录节点的开始、输出和异常
    def _wrapped(state, *args, **kwargs):
        emit_process(name, "running")
        log_node_start(name, state)
        try:
            result = fn(state, *args, **kwargs)
        except Exception as exc:
            emit_process(name, "error", "本步骤执行失败。")
            # 记录异常后继续抛出，避免吞掉原始错误
            log_error(name, exc)
            raise

        log_node_end(name, result)
        emit_process(name, "done", node_summary(name, result))
        return result

    return _wrapped
