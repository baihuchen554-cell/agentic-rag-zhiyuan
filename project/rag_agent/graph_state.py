from typing import List, Annotated, Set
from langgraph.graph import MessagesState
import operator


# 根据重置信号决定清空列表，或将新数据追加到已有列表
def accumulate_or_reset(existing: List[dict], new: List[dict]) -> List[dict]:
    # 如果新数据中包含重置标记，则清空已有数据
    if new and any(item.get('__reset__') for item in new):
        return []
    return existing + new


# 合并两个集合，自动去除重复元素
def set_union(a: Set[str], b: Set[str]) -> Set[str]:
    return a | b


# 合并两个列表，同时保留元素首次出现的顺序并去除重复项
def append_unique(existing: List[str], new: List[str]) -> List[str]:
    return list(dict.fromkeys(existing + new))


class State(MessagesState):
    """主智能体工作流的状态定义"""

    # 标记用户问题是否清晰
    questionIsClear: bool = False

    # 当前对话的历史摘要
    conversation_summary: str = ""

    # 用户最初提出的问题
    originalQuery: str = ""

    # 当前等待处理或补充的问题
    pendingQuery: str = ""

    # 尚待用户回答的澄清问题列表
    pendingClarifications: List[str] = []

    # 经过分析和改写后得到的问题列表
    rewrittenQuestions: List[str] = []
    conversation_only: bool = False

    # 各个子智能体生成的答案，支持追加数据或重置
    agent_answers: Annotated[List[dict], accumulate_or_reset] = []


class AgentState(MessagesState):
    """单个子智能体工作流的状态定义"""

    # 当前子智能体负责处理的问题
    question: str = ""

    # 当前问题在问题列表中的索引
    question_index: int = 0
    conversation_context: str = ""
    original_question: str = ""

    # 当前子智能体使用的上下文摘要
    context_summary: str = ""

    # 联网分支只执行一次，来源随子问题答案传递给最终整合节点。
    web_search_attempted: bool = False
    web_sources: List[dict] = []

    # 已检索内容的标识集合，合并时自动去重
    retrieval_keys: Annotated[Set[str], set_union] = set()

    # 已检索到的上下文内容，追加时自动去重
    retrieved_contexts: Annotated[List[str], append_unique] = []

    # 收集各个子智能体生成的答案
    agent_answers: List[dict] = []

    # 工具调用次数，状态更新时通过加法累积
    tool_call_count: Annotated[int, operator.add] = 0

    # 工作流迭代次数，状态更新时通过加法累积
    iteration_count: Annotated[int, operator.add] = 0
