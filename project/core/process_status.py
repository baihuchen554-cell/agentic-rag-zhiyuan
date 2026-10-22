"""展示工作流的真实进度摘要，不向聊天区输出内部推理或原始工具数据。"""

import re
from time import perf_counter
import uuid

from langgraph.config import get_stream_writer
from config import CHILD_CHUNK_SEPARATOR

STEPS = {
    "summarize_history": "整理对话记忆", "rewrite_query": "理解与改写问题",
    "retrieve_documents": "检索知识库", "search_child_chunks": "检索知识库",
    "retrieve_parent_chunks": "读取完整文档", "orchestrator": "核对文档依据",
    "compress_context": "整理文档上下文", "fallback_response": "整理文档答案",
    "web_fallback": "联网补充", "aggregate_answers": "整合回答",
    "conversation_answer": "根据对话记忆回答",
}


def retrieval_summary(content):
    content = str(content)
    if content.startswith(("RETRIEVAL_ERROR:", "PARENT_RETRIEVAL_ERROR:")):
        return "检索失败，请检查模型 API 或网络连接。"
    if content.startswith(("NO_RELEVANT_CHUNKS", "NO_PARENT_DOCUMENT")):
        return "未找到可用的相关文档内容。"
    count = len([part for part in content.split(CHILD_CHUNK_SEPARATOR) if part.strip()])
    sources = list(dict.fromkeys(re.findall(r"^文件名：(.+)$", content, re.MULTILINE)))
    return f"找到 {count} 段文档内容" + ("，来源：" + "、".join(sources[:3]) if sources else "")


def emit_process(name, status, detail=""):
    step = name.rsplit(".", 1)[-1]
    if step not in STEPS:
        return
    # 单元测试或命令行单独调用工具时，没有工作流流式上下文。
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer({"type": "process", "step": step, "title": STEPS[step], "status": status,
            "detail": str(detail)[:500]})


def node_summary(name, result):
    step = name.rsplit(".", 1)[-1]
    if not isinstance(result, dict):
        return ""
    if step == "rewrite_query":
        if result.get("conversation_only"):
            return "使用当前会话记忆回复。"
        questions = result.get("rewrittenQuestions", [])
        return "检索问题：" + "；".join(questions) if questions else "等待你补充问题信息。"
    if step == "retrieve_documents":
        return retrieval_summary(result["messages"][-1].content)
    if step == "web_fallback":
        count = len(result.get("web_sources", []))
        return f"获得 {count} 个网站来源。" if count else "未获得可用网页，回答将注明未联网核实。"
    return ""


class ProcessStatus:
    def __init__(self):
        self.started = perf_counter()
        self.id = "process-" + uuid.uuid4().hex
        self.steps = {}

    def update(self, event):
        key = event["step"]
        # 多次本地搜索合并为一行，保留最新状态和结果。
        if key == "search_child_chunks":
            key = "retrieve_documents"
        self.steps[key] = dict(event)

    def message(self, finished=False):
        lines = []
        for event in self.steps.values():
            symbol = {"done": "✓", "error": "!", "stopped": "■"}.get(event["status"], "◌")
            detail = (" — " + event["detail"].replace("\n", " ")) if event.get("detail") else ""
            lines.append(f"{symbol} {event['title']}{detail}")
        return {"role": "assistant", "content": "\n\n".join(lines) or "正在准备请求…",
                "metadata": {"title": "处理过程", "id": self.id,
                             "status": "done" if finished else "pending",
                             "duration": round(perf_counter() - self.started, 1)}}
