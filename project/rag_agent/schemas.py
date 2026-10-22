from typing import List
from pydantic import BaseModel, Field


# 定义问题分析结果的数据结构，用于约束大语言模型的结构化输出
class QueryAnalysis(BaseModel):
    conversation_only: bool = Field(default=False, description="仅问候、记录用户自己的信息或回顾本次聊天时为真；涉及文档或外部事实必须为假。")

    # 判断用户的问题是否清晰且能够回答
    is_clear: bool = Field(
        description="判断用户的问题是否清晰且可以回答。"
    )

    # 保存改写后完整、独立的问题列表
    questions: List[str] = Field(
        description="经过改写后，表达清晰且可以独立理解的问题列表。"
    )

    # 当问题不清晰时，说明需要用户补充哪些信息
    clarification_needed: str = Field(
        description="当用户的问题不清晰时，说明需要进一步澄清或补充的信息。"
    )
