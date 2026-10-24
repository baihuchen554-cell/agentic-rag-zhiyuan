from typing import Literal, Set
import config
import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage, RemoveMessage, AIMessage, ToolMessage
from langgraph.types import Command
from .graph_state import State, AgentState
from .schemas import QueryAnalysis
from .prompts import (
    get_aggregation_prompt, get_context_compression_prompt,
    get_conversation_summary_prompt, get_fallback_response_prompt,
    get_orchestrator_prompt, get_rewrite_query_prompt, get_web_answer_prompt,
)
from utils import estimate_context_tokens
from config import BASE_TOKEN_THRESHOLD, CHILD_CHUNK_SEPARATOR, MAIN_HISTORY_MESSAGES_TO_KEEP, TOKEN_GROWTH_FACTOR
from core.web_search import WebSearchClient, UNVERIFIED_NOTICE, add_verified_sources, mark_unverified


# 校验历史消息保留数量，至少保留 2 条普通对话消息
if MAIN_HISTORY_MESSAGES_TO_KEEP < 2:
    raise ValueError("历史消息保留数量 MAIN_HISTORY_MESSAGES_TO_KEEP 必须至少为 2。")

# 回答前保留的历史消息数量
PRE_ANSWER_HISTORY_MESSAGES_TO_KEEP = max(MAIN_HISTORY_MESSAGES_TO_KEEP - 1, 0)


def _procedure_evidence(question: str, answers: list[dict]) -> str:
    """办理类问题整合时保留原文，避免多次摘要丢失入口和中间步骤。"""
    queries = "\n".join([question, *(answer.get("question", "") for answer in answers)]).lower()
    if not any(word in queries for word in (
        "申请", "办理", "预约", "报销", "审批", "报名", "注册", "借用", "借阅",
        "流程", "操作", "入口", "路径", "步骤", "手续", "怎么", "如何", "怎样",
        "how to", "procedure", "apply for",
    )):
        return ""

    candidates = []
    for answer in answers:
        for source in answer.get("web_sources", []):
            # 已引用网页优先，其次本地原文，最后才是其他网页；正文优先于搜索摘要。
            priority = 0 if source["url"] in answer["answer"] else 2
            block = json.dumps({
                "检索问题": answer.get("question", ""),
                "网页标题": source["title"], "URL": source["url"],
                "日期": source.get("date"), "正文": source.get("content", ""),
                "搜索摘要": source.get("summary", ""),
            }, ensure_ascii=False)
            candidates.append((priority, source["url"], block))
        for context in answer.get("contexts", []):
            block = json.dumps({"检索问题": answer.get("question", ""),
                                "文档原文": context}, ensure_ascii=False)
            candidates.append((1, context, block))

    # 控制附加输入；整块保留或跳过，不在菜单路径中间截断原文。
    remaining = 12000
    blocks, seen = [], set()
    for _, key, block in sorted(candidates, key=lambda item: item[0]):
        if key in seen or len(block) + 2 > remaining:
            continue
        blocks.append(block)
        seen.add(key)
        remaining -= len(block) + 2
    return "\n\n".join(blocks)


def _is_plain_conversation_message(msg) -> bool:
    # 判断消息是否为普通的用户或助手对话，排除工具调用和内部消息
    return (
        isinstance(msg, (HumanMessage, AIMessage))
        and not getattr(msg, "tool_calls", None)
        and not getattr(msg, "name", None)
    )


def _name_internal_message(message, name):
    """为子工作流内部消息添加标记，避免将其误认为普通聊天历史。"""
    return message.model_copy(update={"name": name})


def _retrieval_contexts(messages) -> list[str]:
    # 从工具返回的消息中提取有效的检索上下文
    contexts = []

    # 以下内容属于检索状态标识或错误提示，不作为有效检索上下文
    ignored_prefixes = (
        "NO_RELEVANT_CHUNKS",
        "NO_PARENT_DOCUMENT",
        "RETRIEVAL_ERROR:",
        "PARENT_RETRIEVAL_ERROR:",
    )

    for message in messages:
        # 只处理工具返回的消息
        if not isinstance(message, ToolMessage):
            continue

        content = str(message.content).strip()

        # 跳过空内容和无效检索结果
        if content and not content.startswith(ignored_prefixes):
            # 子块搜索结果可能包含多个片段，需要使用指定分隔符拆分
            parts = content.split(CHILD_CHUNK_SEPARATOR) if message.name == "search_child_chunks" else [content]
            contexts.extend(part for part in parts if part)

    # 去除重复上下文，并保留首次出现的顺序
    return list(dict.fromkeys(contexts))


def _format_conversation(messages) -> str:
    # 将历史消息转换成便于模型阅读的对话文本
    lines = []
    for msg in messages:
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        lines.append(f"{role}：{msg.content}")
    return "\n".join(lines)


def _remove_messages_not_in(messages, keep_ids):
    # 生成需要从工作流状态中删除的消息
    removals = []

    for msg in messages:
        msg_id = getattr(msg, "id", None)

        # 保留系统消息，以及没有消息 ID、无法通过 ID 删除的消息
        if isinstance(msg, SystemMessage) or not msg_id:
            continue

        # 删除不在保留列表中的消息
        if msg_id not in keep_ids:
            removals.append(RemoveMessage(id=msg_id))

    return removals


def _recent_conversation(messages, pending_query="") -> list:
    """获取当前用户消息之前的近期对话内容。

    在等待用户澄清时，排除尚未解决的问题和助手的澄清请求，
    因为这些内容会单独提供。
    """
    # 只保留普通对话消息
    plain_messages = [msg for msg in messages if _is_plain_conversation_message(msg)]

    # 排除最后一条消息，因为它通常是当前用户刚提交的问题
    recent_messages = plain_messages[:-1]

    if pending_query:
        # 从后向前查找尚未解决的问题，避免重复拼接
        for index in range(len(recent_messages) - 1, -1, -1):
            msg = recent_messages[index]
            if isinstance(msg, HumanMessage) and str(msg.content).strip() == pending_query:
                return recent_messages[:index]

    return recent_messages


def summarize_history(state: State, llm):
    # 获取当前工作流中的消息，并重置本轮子智能体答案列表
    messages = state.get("messages", [])
    updates = {"agent_answers": [{"__reset__": True}]}

    if not messages:
        return updates

    # 筛选普通对话消息，并确定需要保留的历史消息数量
    plain_messages = [msg for msg in messages if _is_plain_conversation_message(msg)]
    keep_count = PRE_ANSWER_HISTORY_MESSAGES_TO_KEEP

    # 超出保留数量的旧消息需要参与摘要
    messages_to_summarize = plain_messages[:-keep_count] if len(plain_messages) > keep_count else []

    # 获取需要保留的消息 ID
    keep_ids = {getattr(msg, "id", None) for msg in plain_messages[-keep_count:]}
    keep_ids.discard(None)

    # 从工作流状态中移除不需要继续保留的消息
    removals = _remove_messages_not_in(messages, keep_ids)
    if removals:
        updates["messages"] = removals

    # 如果没有需要摘要的旧消息，则直接返回
    if not messages_to_summarize:
        return updates

    # 将已有摘要与新增的历史消息合并，交给模型生成更新后的摘要
    existing_summary = state.get("conversation_summary", "").strip()
    conversation = "已有对话摘要：\n"
    conversation += f"{existing_summary or '（暂无）'}\n\n"
    conversation += "需要合并到摘要中的新消息：\n"
    conversation += _format_conversation(messages_to_summarize)

    # 调用大语言模型压缩历史对话
    summary_response = llm.invoke([
        SystemMessage(content=get_conversation_summary_prompt()),
        HumanMessage(content=conversation),
    ])

    updates["conversation_summary"] = summary_response.content.strip()
    return updates


def rewrite_query(state: State, llm):
    # 获取用户当前的问题及历史上下文
    last_message = state["messages"][-1]
    current_query = str(last_message.content).strip()
    conversation_summary = state.get("conversation_summary", "").strip()
    pending_query = state.get("pendingQuery", "").strip()
    pending_clarifications = state.get("pendingClarifications", [])

    # 获取当前问题之前的近期对话
    recent_messages = _recent_conversation(state["messages"], pending_query)

    context_parts = []

    # 将历史摘要和近期对话加入问题分析上下文
    if conversation_summary:
        context_parts.append(f"对话摘要：\n{conversation_summary}")

    if recent_messages:
        context_parts.append(f"近期对话：\n{_format_conversation(recent_messages)}")

    if pending_query:
        # 如果之前的问题需要澄清，则合并之前的问题和用户补充的信息
        clarifications = [*pending_clarifications, current_query]
        clarification_text = "\n".join(
            f"{index}. {value}" for index, value in enumerate(clarifications, start=1)
        )

        context_parts.append(
            f"尚未解决的用户问题：\n{pending_query}\n\n"
            f"用户补充的信息：\n{clarification_text}"
        )

        original_query = f"{pending_query}\n补充信息：\n{clarification_text}"

    else:
        # 如果没有待澄清的问题，则直接分析当前问题
        clarifications = []
        context_parts.append(f"用户问题：\n{current_query}")
        original_query = current_query

    # 组合全部上下文，并要求模型按照 QueryAnalysis 结构返回结果
    context_section = "\n\n".join(context_parts)
    llm_with_structure = llm.with_structured_output(QueryAnalysis)

    response = llm_with_structure.invoke([
        SystemMessage(content=get_rewrite_query_prompt()),
        HumanMessage(content=context_section)
    ])

    # 如果用户正在补充信息，为该消息添加内部标记
    clarification_message_update = (
        [_name_internal_message(last_message, "clarification_response")]
        if pending_query else []
    )

    # 问题清晰且成功生成改写结果时，更新状态并进入后续检索流程
    if response.questions and response.is_clear:
        return {
            "questionIsClear": True,
            "originalQuery": original_query,
            "pendingQuery": "",
            "pendingClarifications": [],
            "rewrittenQuestions": response.questions,
            "conversation_only": getattr(response, "conversation_only", False),
            "messages": clarification_message_update,
        }

    # 问题仍不明确时，使用模型提供的澄清提示；没有有效提示时使用默认中文提示
    clarification = (
        response.clarification_needed
        if response.clarification_needed
        and len(response.clarification_needed.strip()) > 10
        else "为了准确理解你的问题，请提供更多信息。"
    )

    return {
        "questionIsClear": False,
        "originalQuery": "",
        "pendingQuery": pending_query or current_query,
        "pendingClarifications": clarifications,
        "rewrittenQuestions": [],
        "messages": clarification_message_update + [
            AIMessage(content=clarification, name="clarification")
        ],
    }


def request_clarification(state: State):
    # 该节点用于暂停工作流，等待用户补充信息
    # 具体暂停行为由主工作流的 interrupt_before 配置控制
    return {}


def conversation_answer(state: State, llm):
    response = llm.invoke([
        SystemMessage(content=f"你是 {config.APP_NAME} 助手。结合下方历史摘要和近期聊天，用中文简洁自然地回答。记住用户已经提供的姓名、偏好和事项；不知道的个人信息不要猜测。这是聊天回复，不要联网或编造文档来源。\n历史摘要：\n" + state.get("conversation_summary", "")),
        *[message for message in state.get("messages", []) if _is_plain_conversation_message(message)],
    ])
    return {"messages": [AIMessage(content=response.content)]}


def retrieve_documents(state: AgentState, search_tool):
    """程序强制执行本地检索，不能由模型跳过或用联网掩盖检索错误。"""
    query = state["question"]
    result = str(search_tool.invoke({"query": query}))
    if result.startswith("RETRIEVAL_ERROR:"):
        raise RuntimeError("知识库检索失败，请检查向量 API 配置或网络后重试。")
    original = state.get("original_question", "").strip()
    if result == "NO_RELEVANT_CHUNKS" and original and original != query:
        result = str(search_tool.invoke({"query": original}))
        if result.startswith("RETRIEVAL_ERROR:"):
            raise RuntimeError("知识库检索失败，请检查向量 API 配置或网络后重试。")
    call_id = "initial-local-search"
    messages = [
        HumanMessage(content=query, name="agent_question"),
        AIMessage(content="", name="agent_response", tool_calls=[{
            "name": "search_child_chunks", "args": {"query": query}, "id": call_id,
        }]),
        ToolMessage(content=result, name="search_child_chunks", tool_call_id=call_id),
    ]
    return {"messages": messages, "tool_call_count": 1}


# --- 子智能体节点 ---


def orchestrator(state: AgentState, llm_with_tools):
    # 获取此前压缩保存的检索上下文
    context_summary = state.get("context_summary", "").strip()

    # 构建调度器系统提示
    sys_msg = SystemMessage(content=get_orchestrator_prompt())
    if state.get("conversation_context"):
        sys_msg.content += "\n\n对话记忆（仅帮助理解问题）：\n" + state["conversation_context"]

    # 如果存在压缩摘要，将其作为额外上下文提供给模型
    summary_injection = (
        [HumanMessage(content=f"[前序检索的压缩上下文]\n\n{context_summary}")]
        if context_summary else []
    )

    # 程序已完成首次本地检索，携带检索结果和已有消息调用模型。
    response = llm_with_tools.invoke(
        [sys_msg] + summary_injection + state["messages"]
    )

    response = _name_internal_message(response, "agent_response")
    tool_calls = response.tool_calls if hasattr(response, "tool_calls") else []

    return {
        "messages": [response],
        "tool_call_count": len(tool_calls) if tool_calls else 0,
        "iteration_count": 1
    }


def fallback_response(state: AgentState, llm):
    # 收集工具返回的数据，并去除重复内容
    seen = set()
    unique_contents = []

    for m in state["messages"]:
        if isinstance(m, ToolMessage) and m.content not in seen:
            unique_contents.append(m.content)
            seen.add(m.content)

    # 获取此前压缩保存的检索上下文
    context_summary = state.get("context_summary", "").strip()

    context_parts = []

    if context_summary:
        context_parts.append(
            f"## 前序检索的压缩上下文\n\n{context_summary}"
        )

    if unique_contents:
        # 将本轮检索结果整理为独立的数据来源
        context_parts.append(
            "## 当前轮次检索到的数据\n\n" +
            "\n\n".join(
                f"--- 数据来源 {i} ---\n{content}"
                for i, content in enumerate(unique_contents, 1)
            )
        )

    # 如果没有获取到有效数据，明确告知模型
    context_text = (
        "\n\n".join(context_parts)
        if context_parts
        else "未能从文档中检索到数据。"
    )

    # 生成备用回答，要求模型仅依据已有数据作答
    prompt_content = (
        f"用户问题：{state.get('question')}\n\n"
        f"{context_text}\n\n"
        f"要求：\n请仅使用以上数据，尽可能准确地回答问题。"
    )

    response = llm.invoke([
        SystemMessage(content=get_fallback_response_prompt()),
        HumanMessage(content=prompt_content)
    ])

    response = _name_internal_message(response, "agent_response")
    return {"messages": [response]}


def should_compress_context(state: AgentState) -> Command[Literal["compress_context", "orchestrator", "web_fallback"]]:
    # 获取当前子智能体的全部消息
    messages = state["messages"]

    # 记录新检索的父块 ID 和搜索查询，防止重复检索
    new_ids: Set[str] = set()

    # 从最近的工具调用开始，提取本次检索使用的标识
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:

                # 记录父文档块的检索 ID
                if tc["name"] == "retrieve_parent_chunks":
                    raw = (
                        tc["args"].get("parent_id")
                        or tc["args"].get("id")
                        or tc["args"].get("ids")
                        or []
                    )

                    if isinstance(raw, str):
                        new_ids.add(f"parent::{raw}")
                    else:
                        new_ids.update(f"parent::{r}" for r in raw)

                # 记录子块搜索所用的查询
                elif tc["name"] == "search_child_chunks":
                    query = tc["args"].get("query", "")
                    if query:
                        new_ids.add(f"search::{query}")

            # 仅处理最近一组工具调用
            break

    # 合并已有检索标识和新产生的检索标识
    updated_ids = state.get("retrieval_keys", set()) | new_ids
    contexts = _retrieval_contexts(messages)

    # 本地完全没有检索证据时直接联网，省去重复改写检索和额外模型判断。
    if not contexts and not state.get("context_summary", "").strip():
        return Command(update={"retrieval_keys": updated_ids, "retrieved_contexts": []},
                       goto="web_fallback")

    # 估算消息和摘要占用的 Token 数量
    current_token_messages = estimate_context_tokens(messages)
    current_token_summary = estimate_context_tokens([
        HumanMessage(content=state.get("context_summary", ""))
    ])
    current_tokens = current_token_messages + current_token_summary

    # 根据基础阈值和摘要大小计算允许使用的 Token 上限
    max_allowed = BASE_TOKEN_THRESHOLD + int(
        current_token_summary * TOKEN_GROWTH_FACTOR
    )

    # 超出限制时执行上下文压缩，否则继续调用调度器
    goto = "compress_context" if current_tokens > max_allowed else "orchestrator"

    return Command(
        update={
            "retrieval_keys": updated_ids,
            "retrieved_contexts": contexts,
        },
        goto=goto,
    )


def compress_context(state: AgentState, llm):
    # 获取当前消息和已有的上下文摘要
    messages = state["messages"]
    existing_summary = state.get("context_summary", "").strip()

    if not messages:
        return {}

    # 构建供模型压缩的对话文本
    conversation_text = (
        f"用户问题：\n{state.get('question')}\n\n"
        f"需要压缩的对话内容：\n\n"
    )

    if existing_summary:
        conversation_text += f"[此前压缩的上下文]\n{existing_summary}\n\n"

    # 将模型回复中的工具调用和工具执行结果整理到上下文中
    for msg in messages[1:]:
        if isinstance(msg, AIMessage):
            tool_calls_info = ""

            if getattr(msg, "tool_calls", None):
                calls = ", ".join(
                    f"{tc['name']}({tc['args']})"
                    for tc in msg.tool_calls
                )
                tool_calls_info = f" | 工具调用：{calls}"

            conversation_text += (
                f"[助手{tool_calls_info}]\n"
                f"{msg.content or '（仅调用工具，没有文本内容）'}\n\n"
            )

        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "工具")
            conversation_text += (
                f"[工具执行结果 — {tool_name}]\n"
                f"{msg.content}\n\n"
            )

    # 调用模型压缩对话，提取后续研究仍然需要的信息
    summary_response = llm.invoke([
        SystemMessage(content=get_context_compression_prompt()),
        HumanMessage(content=conversation_text)
    ])

    new_summary = summary_response.content

    # 在摘要末尾记录已执行过的检索操作，避免重复检索
    retrieved_ids: Set[str] = state.get("retrieval_keys", set())

    if retrieved_ids:
        parent_ids = sorted(
            r for r in retrieved_ids if r.startswith("parent::")
        )
        search_queries = sorted(
            r.replace("search::", "")
            for r in retrieved_ids
            if r.startswith("search::")
        )

        block = "\n\n---\n**已执行的检索操作（请勿重复）：**\n"

        if parent_ids:
            block += (
                "已检索的父文档块：\n"
                + "\n".join(
                    f"- {p.replace('parent::', '')}"
                    for p in parent_ids
                )
                + "\n"
            )

        if search_queries:
            block += (
                "已执行的搜索查询：\n"
                + "\n".join(f"- {q}" for q in search_queries)
                + "\n"
            )

        new_summary += block

    # 更新压缩后的上下文，并删除本轮已处理的旧消息
    return {
        "context_summary": new_summary,
        "messages": [
            RemoveMessage(id=m.id)
            for m in messages[1:]
        ]
    }


def web_fallback(state: AgentState, llm):
    """资料不足时先查网页；搜索不可用时由同一个 DeepSeek 模型谨慎补充。"""
    sources = []
    try:
        sources = WebSearchClient().search(state["question"])
    except Exception as exc:
        # 不记录响应正文或请求头，避免把服务端回显中的凭据输出到日志。
        logging.getLogger(__name__).warning("联网搜索暂不可用（%s），改用模型知识。", type(exc).__name__)

    evidence = json.dumps(sources, ensure_ascii=False) if sources else "未获得可用的联网搜索结果。"
    response = llm.invoke([
        SystemMessage(content=get_web_answer_prompt(bool(sources))),
        HumanMessage(content=f"用户问题：{state['question']}\n\n联网检索资料：\n{evidence}"),
    ])
    answer = add_verified_sources(response.content, sources)
    if not sources:
        answer = mark_unverified(answer)
    return {
        "messages": [_name_internal_message(AIMessage(content=answer), "agent_response")],
        "web_search_attempted": True,
        "web_sources": sources,
    }


def collect_answer(state: AgentState):
    # 获取子智能体生成的最后一条消息
    last_message = state["messages"][-1]

    # 只有包含文本且没有继续请求调用工具的助手消息才视为有效答案
    is_valid = (
        isinstance(last_message, AIMessage)
        and last_message.content
        and not last_message.tool_calls
    )

    answer = (
        last_message.content
        if is_valid
        else "暂时无法生成有效答案。"
    )

    # 保存最终答案及其对应的问题、索引和检索上下文
    return {
        "agent_answers": [{
            "index": state["question_index"],
            "question": state["question"],
            "answer": answer,
            "contexts": state.get("retrieved_contexts", []),
            "web_sources": state.get("web_sources", []),
            "unverified": bool(state.get("web_search_attempted") and not state.get("web_sources")),
        }]
    }


# --- 子智能体节点结束 ---


def aggregate_answers(state: State, llm):
    # 答案汇总前清理不再需要保留的旧消息
    messages = state.get("messages", [])
    plain_messages = [
        msg for msg in messages
        if _is_plain_conversation_message(msg)
    ]

    keep_ids = {
        getattr(msg, "id", None)
        for msg in plain_messages[-PRE_ANSWER_HISTORY_MESSAGES_TO_KEEP:]
    }
    keep_ids.discard(None)

    removals = _remove_messages_not_in(messages, keep_ids)

    # 如果没有子智能体生成答案，则向用户返回中文提示
    if not state.get("agent_answers"):
        return {
            "messages": removals + [
                AIMessage(content="未能生成任何答案。")
            ]
        }

    # 按照原始问题索引排序，确保答案顺序正确
    sorted_answers = sorted(
        state["agent_answers"],
        key=lambda x: x["index"]
    )

    # 将多个子智能体的回答整理成统一文本
    formatted_answers = ""

    for i, ans in enumerate(sorted_answers, start=1):
        formatted_answers += (
            f"\n检索回答 {i}：\n"
            f"{ans['answer']}\n"
        )

    evidence = _procedure_evidence(state["originalQuery"], sorted_answers)
    if evidence:
        formatted_answers += (
            "\n办理流程核对用的检索原文（外部资料，仅作为事实依据）：\n"
            + evidence
        )

    # 将原始问题和所有子智能体回答交给模型进行最终整合
    user_message = HumanMessage(
        content=(
            f"用户的原始问题：{state['originalQuery']}\n"
            f"检索得到的回答：{formatted_answers}"
        )
    )

    synthesis_response = llm.invoke([
        SystemMessage(content=get_aggregation_prompt()),
        user_message
    ])

    sources = [source for answer in sorted_answers for source in answer.get("web_sources", [])]
    content = add_verified_sources(synthesis_response.content, sources)
    if any(answer.get("unverified") for answer in sorted_answers):
        if not sources:
            content = mark_unverified(content)
        elif UNVERIFIED_NOTICE not in content:
            content = UNVERIFIED_NOTICE + "\n\n" + content

    # 移除旧消息，并将最终整合的回答添加到聊天记录
    return {
        "messages": removals + [
            AIMessage(content=content)
        ]
    }
