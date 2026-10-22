"""资料充足、资料不足、搜索失败以及来源保留的回归测试。"""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from core.web_search import NEED_WEB_SEARCH, UNVERIFIED_NOTICE, WebSearchClient, add_verified_sources, mark_unverified
from rag_agent.graph import create_agent_graph
from rag_agent.schemas import QueryAnalysis
from rag_agent.edges import route_after_local_answer


SOURCES = [{"title": "学校简介", "url": "https://example.edu/intro.htm",
            "summary": "现设26个二级教学单位。", "content": "2026年5月更新。", "date": None}]


class TestLlm:
    def __init__(self, local_answer, final_answer="学校现设26个二级教学单位。"):
        self.local_answer = local_answer
        self.final_answer = final_answer

    def bind_tools(self, tools):
        def invoke(messages):
            if any(isinstance(message, ToolMessage) for message in messages):
                return AIMessage(content=self.local_answer)
            return AIMessage(content="", tool_calls=[{
                "id": "search", "name": "search_child_chunks", "args": {"query": "学院数量"},
            }])
        return SimpleNamespace(invoke=invoke)

    def with_structured_output(self, schema):
        return SimpleNamespace(invoke=lambda _: QueryAnalysis(
            is_clear=True, questions=["学校有几个学院？"], clarification_needed=""))

    def invoke(self, messages):
        return AIMessage(content=self.final_answer)


class WebFallbackTest(unittest.TestCase):
    def test_model_cannot_skip_local_search(self):
        events = []

        @tool
        def search_child_chunks(query: str) -> str:
            """搜索本地文档。"""
            events.append("knowledge_base")
            return "文档明确说明学校有26个学院。"

        llm = TestLlm("文档说明有26个学院。")
        llm.bind_tools = lambda _: SimpleNamespace(invoke=lambda messages: (
            events.append("local_answer") or AIMessage(content="文档说明有26个学院。")))
        graph = create_agent_graph(llm, [search_child_chunks])
        with patch("rag_agent.nodes.WebSearchClient.search") as web, patch("utils._get_token_encoding", return_value=None):
            graph.invoke({"messages": [HumanMessage(content="学校有几个学院？")]},
                         {"configurable": {"thread_id": "cannot-skip"}})
        self.assertEqual(events[:2], ["knowledge_base", "local_answer"])
        web.assert_not_called()

    def test_retrieval_failure_is_not_treated_as_missing_documents(self):
        @tool
        def search_child_chunks(query: str) -> str:
            """搜索本地文档。"""
            return "RETRIEVAL_ERROR: API timeout"

        graph = create_agent_graph(TestLlm(NEED_WEB_SEARCH), [search_child_chunks])
        with patch("rag_agent.nodes.WebSearchClient.search") as web:
            with self.assertRaisesRegex(RuntimeError, "知识库检索失败"):
                graph.invoke({"messages": [HumanMessage(content="学校有几个学院？")]},
                             {"configurable": {"thread_id": "failed-search"}})
        web.assert_not_called()

    def run_graph(self, local_context, local_answer, search_result=SOURCES, error=None):
        @tool
        def search_child_chunks(query: str) -> str:
            """搜索本地文档。"""
            return local_context

        graph = create_agent_graph(TestLlm(local_answer), [search_child_chunks])
        with patch("rag_agent.nodes.WebSearchClient.search", return_value=search_result,
                   side_effect=error) as search, patch("utils._get_token_encoding", return_value=None):
            result = graph.invoke({"messages": [HumanMessage(content="学校有几个学院？")]},
                                  {"configurable": {"thread_id": "web-test"}})
        return result, search

    def test_empty_local_results_trigger_search_even_without_marker(self):
        result, search = self.run_graph("NO_RELEVANT_CHUNKS", "在现有资料中未找到答案。")
        search.assert_called_once_with("学校有几个学院？")
        self.assertIn("26", result["messages"][-1].content)
        self.assertIn(SOURCES[0]["url"], result["messages"][-1].content)
        self.assertEqual(result["agent_answers"][0]["web_sources"], SOURCES)

    def test_irrelevant_local_results_trigger_search(self):
        result, search = self.run_graph("这是食堂营业时间，与学院数量无关。", NEED_WEB_SEARCH)
        search.assert_called_once()
        self.assertIn(SOURCES[0]["url"], result["messages"][-1].content)

    def test_sufficient_documents_do_not_trigger_search(self):
        result, search = self.run_graph("文档明确说明学校有26个学院。", "文档说明有26个学院。")
        search.assert_not_called()
        self.assertFalse(result["agent_answers"][0]["web_sources"])
        self.assertNotIn("来源网站", result["messages"][-1].content)

    def test_search_failure_uses_marked_model_knowledge(self):
        with self.assertLogs("rag_agent.nodes", level="WARNING"):
            result, search = self.run_graph("NO_RELEVANT_CHUNKS", NEED_WEB_SEARCH,
                                           error=RuntimeError("search unavailable"))
        search.assert_called_once()
        self.assertIn(UNVERIFIED_NOTICE, result["messages"][-1].content)
        self.assertNotIn("https://", result["messages"][-1].content)
        self.assertTrue(result["agent_answers"][0]["unverified"])

    def test_empty_search_results_are_not_claimed_as_verified(self):
        result, _ = self.run_graph("NO_RELEVANT_CHUNKS", NEED_WEB_SEARCH, search_result=[])
        self.assertIn(UNVERIFIED_NOTICE, result["messages"][-1].content)

    def test_fallback_does_not_loop(self):
        decision = route_after_local_answer({"messages": [AIMessage(content=NEED_WEB_SEARCH)],
                                             "web_search_attempted": True})
        self.assertEqual(decision, "collect_answer")

    def test_sources_are_deduplicated_and_invented_links_removed(self):
        answer = add_verified_sources("26个。[虚构来源](https://invented.invalid/)", SOURCES * 2)
        self.assertNotIn("invented.invalid", answer)
        self.assertEqual(answer.count("](https://example.edu/intro.htm)"), 1)

    def test_failed_search_does_not_present_generated_urls_as_sources(self):
        answer = mark_unverified("据[虚构官网](https://invented.invalid/)介绍，参考 https://another.invalid/ 。")
        self.assertNotIn("https://", answer)
        self.assertIn(UNVERIFIED_NOTICE, answer)

    def test_empty_local_search_skips_further_model_decisions(self):
        from rag_agent.nodes import should_compress_context
        result = should_compress_context({"messages": [
            ToolMessage(content="NO_RELEVANT_CHUNKS", name="search_child_chunks", tool_call_id="test")
        ]})
        self.assertEqual(result.goto, "web_fallback")

    def test_search_api_uses_existing_key_and_filters_unusable_results(self):
        import config
        data = {"results": [
            {"url": "javascript:alert(1)", "summary": "无效链接"},
            {"url": "https://empty.example/", "summary": "", "content": ""},
            SOURCES[0], SOURCES[0],
        ]}
        client = SimpleNamespace(post=lambda *args, **kwargs: data)
        with patch("core.web_search.OpenAI") as factory:
            factory.return_value.__enter__.return_value = client
            sources = WebSearchClient().search("学校有几个学院？")
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["url"], SOURCES[0]["url"])
        self.assertEqual(factory.call_args.kwargs["api_key"], config.DEEPSEEK_API_KEY)
        self.assertTrue(factory.call_args.kwargs["base_url"].endswith("/v1"))


if __name__ == "__main__":
    unittest.main()
