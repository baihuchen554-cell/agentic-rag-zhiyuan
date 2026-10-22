"""使用临时父文档和真实 Qdrant 验证入库计数、失败回滚及页面状态。"""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import config
from core.document_manager import DocumentManager, DocumentProgress
from db.parent_store_manager import ParentStoreManager
from db.vector_db_manager import VectorDbManager
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore, RetrievalMode
from qdrant_client import QdrantClient, models
from ui.upload_progress import render_upload_progress


class CountingEmbeddings(Embeddings):
    def __init__(self):
        self.batches = []
        self.fail_on = None

    def embed_documents(self, texts):
        self.batches.append(len(texts))
        if len(self.batches) == self.fail_on:
            raise RuntimeError("模拟第二批接口失败")
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


class IngestionProgressTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        settings = patch.multiple(config, MARKDOWN_DIR=str(self.root / "markdown"), EMBEDDING_BATCH_SIZE=20)
        settings.start()
        self.addCleanup(settings.stop)
        self.client = QdrantClient(":memory:")
        self.addCleanup(self.client.close)
        self.client.create_collection("test", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
        self.embeddings = CountingEmbeddings()
        collection = QdrantVectorStore(
            self.client, "test", embedding=self.embeddings,
            retrieval_mode=RetrievalMode.DENSE, validate_collection_config=False,
        )
        self.vector_db = VectorDbManager.__new__(VectorDbManager)
        self.vector_db._VectorDbManager__client = self.client
        self.vector_db.get_collection = lambda name: collection
        self.parents = ParentStoreManager(str(self.root / "parents"))

        def chunks(path, source_name):
            parent_id = f"{Path(path).stem}_p0"
            metadata = {"source": source_name, "parent_id": parent_id}
            return ([(parent_id, Document(page_content="原始正文", metadata=metadata))],
                    [Document(page_content=f"正文 {i}", metadata=metadata) for i in range(45)])

        self.rag = SimpleNamespace(
            vector_db=self.vector_db, parent_store=self.parents, collection_name="test",
            chunker=SimpleNamespace(create_chunks_single=chunks), initialize=lambda: None,
        )
        self.manager = DocumentManager(self.rag)
        self.source = self.root / "学生手册.md"
        self.source.write_text("# 手册\n正文", encoding="utf-8")

    def test_counts_only_committed_batches_and_completes_last(self):
        events = []

        def report(event):
            events.append(event)
            if event.stage == "indexing":
                self.assertEqual(self.client.count("test").count, event.completed_chunks)
                self.assertEqual(event.added, 0)

        self.assertEqual(self.manager.add_documents([str(self.source)], report), (1, 0))
        self.assertEqual(self.embeddings.batches, [20, 20, 5])
        self.assertEqual([event.completed_chunks for event in events if event.stage == "indexing"], [0, 20, 40, 45])
        self.assertEqual([event.stage for event in events[:3]], ["parsing", "chunking", "indexing"])
        self.assertEqual(events[-1].stage, "complete")
        self.assertEqual(events[-1].added, 1)
        self.assertTrue(self.parents.list_sources())
        self.assertNotIn("入库完成", render_upload_progress(events[0]))
        self.assertNotIn("100%", render_upload_progress(events[0]))

    def test_failed_later_batch_rolls_back_and_can_be_retried(self):
        self.embeddings.fail_on = 2
        events = []
        self.manager.add_documents([str(self.source)], events.append)
        self.assertEqual(events[-1].failed, 1)
        self.assertEqual(events[-1].skipped, 0)
        self.assertEqual(events[-1].added, 0)
        self.assertEqual(self.client.count("test").count, 0)
        self.assertFalse((self.manager.markdown_dir / self.source.name).exists())
        self.assertEqual(self.parents.list_sources(), [])
        html = render_upload_progress(events[-1])
        self.assertIn('data-state="error"', html)
        self.assertIn("入库未完成", html)
        self.assertNotIn("入库完成", html)
        self.embeddings.fail_on = None
        self.assertEqual(self.manager.add_documents([str(self.source)]), (1, 0))
        self.assertEqual(self.client.count("test").count, 45)

    def test_duplicate_and_new_documents_are_counted_separately(self):
        self.manager.add_documents([str(self.source)])
        other = self.root / "补充.md"
        other.write_text("补充正文", encoding="utf-8")
        events = []
        self.assertEqual(self.manager.add_documents([str(self.source), str(other)], events.append), (1, 1))
        self.assertEqual(events[0].stage, "skipped")
        self.assertEqual(events[-1].total_files, 2)
        self.assertEqual((events[-1].added, events[-1].skipped, events[-1].failed), (1, 1, 0))
        self.assertEqual(self.client.count("test").count, 90)

    def test_progress_card_escapes_names_and_labels_quantities(self):
        progress = DocumentProgress("indexing", filename='<script>bad</script>.pdf',
                                    file_index=1, total_files=2, completed_chunks=20, total_chunks=45)
        html = render_upload_progress(progress)
        self.assertIn("已写入 20 / 45 段文本", html)
        self.assertIn('aria-valuenow="20"', html)
        self.assertIn('aria-valuemax="45"', html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("100%", html)
        ready = render_upload_progress(DocumentProgress("ready", total_files=1))
        self.assertIn("等待入库", ready)
        self.assertNotIn('role="progressbar"', ready)

    def test_page_restores_controls_and_retains_failed_files_for_retry(self):
        from ui.gradio_app import create_gradio_ui
        with patch.object(config, "CHAT_HISTORY_PATH", str(self.root / "history.sqlite3")), \
                patch("ui.gradio_app.RAGSystem", return_value=self.rag):
            demo = create_gradio_ui()
            self.addCleanup(demo.close)
            callbacks = {function.fn.__name__: function.fn for function in demo.fns.values() if function.fn}
            self.embeddings.fail_on = 2
            stream = callbacks["upload_handler"]([str(self.source)])
            first = next(stream)
            self.assertFalse(first[0]["interactive"])
            self.assertFalse(first[7]["interactive"])
            self.assertIn("准备入库", first[6]["value"])
            self.assertNotIn("入库完成", first[6]["value"])
            final = list(stream)[-1]
            self.assertEqual(len(final), 10)
            self.assertTrue(final[0]["interactive"])
            self.assertEqual(final[0]["value"], [str(self.source)])
            self.assertIn("入库未完成", final[6]["value"])
            self.assertEqual(final[7]["value"], "重试入库")
            self.assertTrue(final[7]["interactive"])
            self.embeddings.fail_on = None
            success = list(callbacks["upload_handler"]([str(self.source)]))[-1]
            self.assertIsNone(success[0]["value"])
            self.assertIn("入库完成", success[6]["value"])
            self.assertIn(self.source.name, success[2]["choices"])
            self.assertTrue(success[2]["interactive"])


if __name__ == "__main__":
    unittest.main()
