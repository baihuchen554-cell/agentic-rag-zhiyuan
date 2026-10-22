"""使用真实本地 Qdrant 验证定向删除不会影响未选文档。"""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

import config
from core.document_manager import DocumentManager
from db.parent_store_manager import ParentStoreManager
from db.vector_db_manager import VectorDbManager
from qdrant_client import QdrantClient, models


class DocumentDeletionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.settings = patch.object(config, "MARKDOWN_DIR", str(self.root / "markdown"))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.client = QdrantClient(":memory:")
        self.addCleanup(self.client.close)
        self.client.create_collection("test", vectors_config=models.VectorParams(
            size=2, distance=models.Distance.COSINE))
        self.vector_db = VectorDbManager.__new__(VectorDbManager)
        self.vector_db._VectorDbManager__client = self.client
        self.parents = ParentStoreManager(str(self.root / "parents"))
        self.manager = DocumentManager(SimpleNamespace(
            vector_db=self.vector_db, parent_store=self.parents, collection_name="test"))
        self.sources = ["手册.pdf", "手册补充.pdf", "说明.md"]
        points = []
        for index, source in enumerate(self.sources):
            stem = Path(source).stem
            (self.manager.markdown_dir / f"{stem}.md").write_text(source, encoding="utf-8")
            self.parents.save(f"{stem}_p0", source, {"source": source})
            for child in range(2):
                points.append(models.PointStruct(id=index * 2 + child + 1, vector=[1.0, 0.0],
                    payload={"metadata": {"source": source, "parent_id": f"{stem}_p0"}}))
        self.client.upsert("test", points=points)

    def indexed_sources(self):
        points, _ = self.client.scroll("test", limit=100, with_payload=True)
        return {point.payload["metadata"]["source"] for point in points}

    def test_delete_one_preserves_similar_names_and_other_files(self):
        self.assertEqual(self.manager.delete_documents(["手册.pdf"]), 1)
        self.assertEqual(self.indexed_sources(), {"手册补充.pdf", "说明.md"})
        self.assertFalse((self.manager.markdown_dir / "手册.md").exists())
        self.assertEqual(self.parents.list_sources(), ["手册补充.pdf", "说明.md"])
        self.assertTrue((self.manager.markdown_dir / "手册补充.md").exists())
        self.assertTrue(self.parents.load_content("手册补充_p0")["content"])

    def test_delete_multiple_and_deduplicate_selection(self):
        self.assertEqual(self.manager.delete_documents(["手册.pdf", "说明.md", "手册.pdf"]), 2)
        self.assertEqual(self.indexed_sources(), {"手册补充.pdf"})
        self.assertEqual(self.parents.list_sources(), ["手册补充.pdf"])

    def test_empty_selection_does_nothing(self):
        self.assertEqual(self.manager.delete_documents([]), 0)
        self.assertEqual(self.indexed_sources(), set(self.sources))

    def test_stale_selection_is_rejected_before_any_deletion(self):
        with self.assertRaisesRegex(ValueError, "已不存在"):
            self.manager.delete_documents(["手册.pdf", "不存在.pdf"])
        self.assertEqual(self.indexed_sources(), set(self.sources))

    def test_vector_failure_keeps_local_documents_for_retry(self):
        with patch.object(self.vector_db, "delete_sources", side_effect=RuntimeError("失败")):
            with self.assertRaises(RuntimeError):
                self.manager.delete_documents(["手册.pdf"])
        self.assertEqual(self.parents.list_sources(), sorted(self.sources))
        self.assertTrue((self.manager.markdown_dir / "手册.md").exists())

    def test_path_traversal_is_rejected(self):
        self.parents.save("bad_p0", "test", {"source": "../outside.pdf"})
        with self.assertRaisesRegex(ValueError, "名称无效"):
            self.manager.delete_documents(["../outside.pdf"])
        self.assertEqual(self.indexed_sources(), set(self.sources))


if __name__ == "__main__":
    unittest.main()
