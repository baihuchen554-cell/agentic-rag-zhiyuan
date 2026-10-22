"""仅用于界面和日志的中文显示，不改写工作流状态、工具协议或原始资料。"""

DISPLAY_NAMES = {
    "chat": "聊天",
    "summarize_history": "聊天历史摘要",
    "rewrite_query": "问题分析与改写",
    "request_clarification": "请求补充信息",
    "agent": "检索智能体",
    "orchestrator": "检索编排",
    "tools": "执行检索工具",
    "should_compress_context": "检查上下文压缩条件",
    "compress_context": "压缩上下文",
    "fallback_response": "生成备用回答",
    "collect_answer": "收集回答",
    "web_fallback": "联网搜索补充",
    "aggregate_answers": "整合最终回答",
    "after_rewrite": "问题改写后的路由",
    "after_orchestrator_call": "检索编排后的路由",
    "search_child_chunks": "搜索文档片段",
    "retrieve_parent_chunks": "获取完整父文档块",
    "agent_question": "智能体问题",
    "agent_response": "智能体回答",
    "clarification": "待补充信息",
    "clarification_response": "用户补充信息",
    "__start__": "开始",
    "__end__": "结束",
}

FIELD_LABELS = {
    "type": "类型", "id": "标识", "name": "名称", "content": "内容",
    "args": "参数", "tool_calls": "工具调用", "tool_call_id": "工具调用标识",
    "count": "数量", "last_messages": "最近消息", "value": "值",
    "messages": "消息", "message": "消息", "items": "条目", "index": "序号",
    "question": "问题", "question_index": "问题序号", "answer": "回答",
    "conversation_summary": "对话摘要", "context_summary": "上下文摘要",
    "final_answer": "最终回答", "agent_answers": "智能体回答",
    "thread_id": "会话标识", "pending_interrupt": "等待用户补充",
    "decision": "路由结果", "state": "状态", "output": "输出",
    "questionIsClear": "问题是否清晰", "originalQuery": "原始问题",
    "pendingQuery": "待补充问题", "pendingClarifications": "用户补充信息",
    "rewrittenQuestions": "改写后的问题", "retrieval_keys": "已执行检索",
    "retrieved_contexts": "已检索上下文", "contexts": "上下文",
    "tool_call_count": "工具调用次数", "iteration_count": "迭代次数",
    "query": "检索问题", "limit": "返回数量上限", "parent_id": "父文档块标识",
    "node": "目标节点", "is_clear": "问题是否清晰", "questions": "问题列表",
    "clarification_needed": "需要补充的信息", "__reset__": "重置",
}


def display_name(name: str) -> str:
    if name.startswith(("main.", "agent.")):
        group, node = name.split(".", 1)
        if node in DISPLAY_NAMES:
            return ("主工作流" if group == "main" else "检索智能体") + "·" + DISPLAY_NAMES[node]
    return DISPLAY_NAMES.get(name, name)


def display_tool_result(content: str) -> str:
    """翻译工具预览中的状态码；检索原文、文件名和内部工具消息保持原样。"""
    statuses = {
        "NO_RELEVANT_CHUNKS": "未找到相关文档片段",
        "NO_PARENT_DOCUMENT": "未找到对应的父文档块",
    }
    if content in statuses:
        return statuses[content]
    for prefix, label in (
        ("RETRIEVAL_ERROR:", "文档片段检索失败："),
        ("PARENT_RETRIEVAL_ERROR:", "父文档块检索失败："),
    ):
        if content.startswith(prefix):
            return label + content[len(prefix):].lstrip()
    return content.replace("\n\n<CHILD_CHUNK_BOUNDARY>\n\n", "\n\n—— 下一段文档片段 ——\n\n")


def display_log_value(value, field=None):
    """创建中文日志副本，不修改传入的状态或用户内容。"""
    if isinstance(value, dict):
        return {
            FIELD_LABELS.get(key, key): display_log_value(item, key)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [display_log_value(item, field) for item in value]
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return "无"
    if isinstance(value, str):
        if field in {"name", "node", "decision"}:
            return display_name(value)
        if field == "output":
            return display_tool_result(value)
        if field == "retrieval_keys":
            if value.startswith("parent::"):
                return "父文档块：" + value[len("parent::"):]
            if value.startswith("search::"):
                return "检索问题：" + value[len("search::"):]
    return value
