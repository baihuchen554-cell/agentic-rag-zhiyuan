"""办理流程在联网摘要、上下文压缩和最终整合后仍保留完整入口与菜单。"""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from rag_agent.graph import create_agent_graph
from rag_agent.nodes import _procedure_evidence
from rag_agent.schemas import QueryAnalysis


QUESTION = "河源校区的会议室应该如何申请？"
FULL_PATH = "登录学校信息门户——自动办公化系统——会议管理——会议室——申请会议室——选择需申请的会议室——填写提交"
ORIGINAL = f"使用部门提前一天向党政工作部提出申请（{FULL_PATH}）。"
SHORT_ANSWER = "提前一天申请，路径为：会议管理——会议室——选择会议室——填写提交。"
SOURCE = {
    "title": "关于河源校区场所使用的申请指引",
    "url": "https://hyxqgwh.gpnu.edu.cn/info/1046/3689.htm",
    "summary": SHORT_ANSWER,
    "content": ORIGINAL,
}


class LossySummaryLlm:
    """故意让中间摘要丢步骤，验证原文能独立到达最终整合节点。"""

    def __init__(self):
        self.calls = []
        self.aggregation_input = ""

    def with_structured_output(self, _):
        return SimpleNamespace(invoke=lambda messages: QueryAnalysis(
            is_clear=True, questions=[QUESTION], clarification_needed=""))

    def bind_tools(self, _):
        def invoke(messages):
            self.calls.append("local_answer")
            return AIMessage(content=SHORT_ANSWER)
        return SimpleNamespace(invoke=invoke)

    def invoke(self, messages):
        system = messages[0].content
        if "研究上下文压缩器" in system:
            self.calls.append("compression")
            return AIMessage(content=SHORT_ANSWER)
        if "补充文档信息缺口" in system:
            self.calls.append("web_answer")
            return AIMessage(content=f"{SHORT_ANSWER}\n来源：[{SOURCE['title']}]({SOURCE['url']})")
        if "最终答案整合器" in system:
            self.calls.append("aggregation")
            self.aggregation_input = messages[-1].content
            answer = ORIGINAL if FULL_PATH in self.aggregation_input else SHORT_ANSWER
            return AIMessage(content=answer)
        raise AssertionError("意外的模型调用")


class ProcedureAnswersTest(unittest.TestCase):
    def run_graph(self, local_context, *, original_question=QUESTION, compress=False):
        @tool
        def search_child_chunks(query: str) -> str:
            """返回测试文档，禁止使用真实知识库。"""
            return local_context

        llm = LossySummaryLlm()
        graph = create_agent_graph(llm, [search_child_chunks])
        threshold = 1 if compress else 100000
        with patch("rag_agent.nodes.WebSearchClient.search", return_value=[SOURCE]) as search, \
                patch("rag_agent.nodes.BASE_TOKEN_THRESHOLD", threshold), \
                patch("utils._get_token_encoding", return_value=None):
            result = graph.invoke({"messages": [HumanMessage(content=original_question)]},
                                  {"configurable": {"thread_id": "procedure-regression"}})
        return result, llm, search

    def test_web_original_can_restore_steps_missing_from_intermediate_answer(self):
        result, llm, search = self.run_graph("NO_RELEVANT_CHUNKS")
        search.assert_called_once_with(QUESTION)
        self.assertNotIn(FULL_PATH, result["agent_answers"][0]["answer"])
        self.assertIn(FULL_PATH, llm.aggregation_input)
        self.assertIn(FULL_PATH, result["messages"][-1].content)
        self.assertIn(SOURCE["url"], result["messages"][-1].content)
        self.assertEqual(llm.calls, ["web_answer", "aggregation"])

    def test_original_local_context_survives_lossy_compression(self):
        context = f"文件名：会议室指引.pdf\n内容：{ORIGINAL}"
        result, llm, search = self.run_graph(context, compress=True)
        search.assert_not_called()
        self.assertEqual(llm.calls, ["compression", "local_answer", "aggregation"])
        self.assertNotIn(FULL_PATH, result["agent_answers"][0]["answer"])
        self.assertIn(context, result["agent_answers"][0]["contexts"])
        self.assertIn("会议室指引.pdf", llm.aggregation_input)
        self.assertIn(FULL_PATH, result["messages"][-1].content)

    def test_followup_uses_procedure_intent_from_rewritten_question(self):
        result, llm, _ = self.run_graph("NO_RELEVANT_CHUNKS", original_question="那河源校区呢？")
        self.assertIn(FULL_PATH, llm.aggregation_input)
        self.assertIn(FULL_PATH, result["messages"][-1].content)

    def test_simple_fact_question_does_not_add_raw_evidence(self):
        evidence = _procedure_evidence("学校有几个学院？", [{
            "question": "学校有几个学院？", "answer": "26个。",
            "contexts": ["文档内容"], "web_sources": [SOURCE],
        }])
        self.assertEqual(evidence, "")

    def test_budget_prioritizes_cited_source_and_never_slices_a_path(self):
        other_sources = [{"title": f"其他网页{i}", "url": f"https://example.edu/{i}",
                          "content": "无关资料" * 1400} for i in range(5)]
        evidence = _procedure_evidence(QUESTION, [{
            "question": QUESTION, "answer": f"{SHORT_ANSWER}\n{SOURCE['url']}",
            "web_sources": [*other_sources, SOURCE, SOURCE],
            "contexts": [],
        }])
        self.assertLessEqual(len(evidence), 12000)
        self.assertEqual(evidence.count(FULL_PATH), 1)
        self.assertEqual(evidence.count(SOURCE["url"]), 1)
        # 无关长网页要么完整入选，要么整块跳过。
        self.assertEqual(evidence.count("无关资料") % 1400, 0)


if __name__ == "__main__":
    unittest.main()
