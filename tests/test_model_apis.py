"""离线验证模型协议与 RAG 集成：python -m unittest discover -s tests -v。"""

import json
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import config
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_qdrant.sparse_embeddings import SparseEmbeddings, SparseVector


class LocalSparseEmbeddings(SparseEmbeddings):
    """避免测试下载本地 BM25 模型。"""

    def __init__(self, **kwargs):
        pass

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return SparseVector(indices=[1], values=[1.0])


class ApiProtocolTest(unittest.TestCase):
    def test_embedding_and_rag_workflow(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, body))
                if self.path == "/v1/embeddings":
                    self.send_json({
                        "object": "list",
                        "model": body["model"],
                        "data": [
                            {"object": "embedding", "index": i,
                             "embedding": [1.0] + [0.0] * 1023}
                            for i, _ in enumerate(body["input"])
                        ],
                        "usage": {"prompt_tokens": 1, "total_tokens": 1},
                    })
                    return

                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return

                names = [tool["function"]["name"] for tool in body.get("tools", [])]
                if "QueryAnalysis" in names:
                    message = self.tool_call("QueryAnalysis", {
                        "is_clear": True,
                        "questions": ["文档中的测试内容是什么？"],
                        "clarification_needed": "",
                    })
                elif names and not any(m["role"] == "tool" for m in body["messages"]):
                    message = self.tool_call("search_child_chunks", {"query": "测试内容"})
                else:
                    message = {"role": "assistant", "content": "文档中的测试内容已找到。"}

                finish = "tool_calls" if message.get("tool_calls") else "stop"
                base = {"id": "chatcmpl-local", "created": 1, "model": body["model"]}
                if body.get("stream"):
                    delta = dict(message)
                    if delta.get("tool_calls"):
                        delta["tool_calls"] = [dict(delta["tool_calls"][0], index=0)]
                    chunks = [
                        {**base, "object": "chat.completion.chunk", "choices": [
                            {"index": 0, "delta": delta, "finish_reason": None}]},
                        {**base, "object": "chat.completion.chunk", "choices": [
                            {"index": 0, "delta": {}, "finish_reason": finish}]},
                    ]
                    data = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
                    data += "data: [DONE]\n\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(data.encode())
                else:
                    self.send_json({**base, "object": "chat.completion", "choices": [
                        {"index": 0, "message": message, "finish_reason": finish}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    })

            @staticmethod
            def tool_call(name, arguments):
                return {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call-local", "type": "function", "function": {
                        "name": name, "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }]}

            def send_json(self, data):
                payload = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.server_close)
            stack.callback(server.shutdown)
            base_url = f"http://127.0.0.1:{server.server_port}/v1"
            stack.enter_context(patch.multiple(config,
                EMBEDDING_API_KEY="offline-test", DEEPSEEK_API_KEY="offline-test",
                EMBEDDING_BASE_URL=base_url, DEEPSEEK_BASE_URL=base_url,
                QDRANT_DB_PATH=str(Path(directory) / "qdrant"),
                PARENT_STORE_PATH=str(Path(directory) / "parents"),
                MARKDOWN_DIR=str(Path(directory) / "markdown"),
                CHAT_HISTORY_PATH=str(Path(directory) / "chat.sqlite3"),
            ))
            stack.enter_context(patch("db.vector_db_manager.FastEmbedSparse", LocalSparseEmbeddings))
            stack.enter_context(patch("utils._get_token_encoding", return_value=None))
            from core.rag_system import RAGSystem

            rag = RAGSystem()
            client = rag.vector_db._VectorDbManager__client
            stack.callback(client.close)
            rag.initialize()
            store = rag.vector_db.get_collection(rag.collection_name)
            self.assertEqual(requests, [], "初始化不应调用向量或对话 API")

            docs = [Document(page_content=f"测试内容 {i}", metadata={"source": "test.md"})
                    for i in range(45)]
            store.add_documents(docs)
            embedding_requests = [body for path, body in requests if path.endswith("/embeddings")]
            self.assertEqual([len(b["input"]) for b in embedding_requests], [20, 20, 5])
            for body in embedding_requests:
                self.assertEqual(body["model"], "qwen3.7-text-embedding-flash")
                self.assertEqual(body["dimensions"], 1024)
                self.assertEqual(body["encoding_format"], "float")
                self.assertTrue(all(isinstance(text, str) for text in body["input"]))
            self.assertEqual(client.count(rag.collection_name).count, 45)

            result = rag.agent_graph.invoke(
                {"messages": [HumanMessage(content="文档讲了什么？")]}, rag.get_config())
            self.assertEqual(result["messages"][-1].content, "文档中的测试内容已找到。")
            self.assertTrue(result["agent_answers"][0]["contexts"])
            self.assertIn("测试内容", result["agent_answers"][0]["contexts"][0])

            # 同一会话的流式回答，以及超过历史保留量后触发的摘要调用。
            from core.chat_interface import ChatInterface
            updates = list(ChatInterface(rag).chat("再说明一下。", []))
            messages = updates[-1]
            self.assertIsInstance(messages, list)
            self.assertEqual(messages[-1]["content"], "文档中的测试内容已找到。")
            self.assertEqual(len(messages), 2, "聊天区展示折叠的处理摘要和一条最终回答")
            self.assertEqual(messages[0]["metadata"]["status"], "done")
            self.assertIn("检索知识库", messages[0]["content"])
            self.assertNotIn("QueryAnalysis", str(messages))
            rag.agent_graph.invoke(
                {"messages": [HumanMessage(content="还有什么？")]}, rag.get_config())

            chat_requests = [body for path, body in requests if path.endswith("/chat/completions")]
            self.assertGreaterEqual(len(chat_requests), 9)
            self.assertTrue(any(body.get("stream") for body in chat_requests))
            self.assertTrue(any(any(m["role"] == "tool" for m in body["messages"])
                                for body in chat_requests))
            for body in chat_requests:
                self.assertEqual(body["model"], "deepseek-flash")
                self.assertEqual(body["thinking"], {"type": "disabled"})

            # 已存在索引仍校验维度，禁止静默写入不兼容向量。
            with patch.object(config, "DENSE_DIMENSIONS", 512):
                with self.assertRaisesRegex(ValueError, "1024.*512"):
                    rag.vector_db.create_collection(rag.collection_name)

    def test_missing_credentials(self):
        with patch.multiple(config, EMBEDDING_API_KEY="", DEEPSEEK_API_KEY=""):
            with self.assertRaisesRegex(ValueError, "project/.env.*DEEPSEEK_API_KEY.*DASHSCOPE_API_KEY"):
                config.validate_model_api_settings()


if __name__ == "__main__":
    unittest.main()
