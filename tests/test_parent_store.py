"""父块路径必须受限于本地存储，损坏文件不应影响其他文档。"""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
from db.parent_store_manager import ParentStoreManager


class ParentStoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = ParentStoreManager(self.root / "parents")
        self.store.save("手册[v2].2026_p0", "原文", {"source": "手册[v2].2026.pdf"})
        self.outside = self.root / "outside.json"
        self.outside.write_text('{"secret":"outside"}', encoding="utf-8")

    def test_read_write_and_delete_reject_outside_paths(self):
        for identifier in ("../outside", "..\\outside", str(self.outside), "C:outside", "", ".."):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    self.store.load(identifier)
                with self.assertRaises(ValueError):
                    self.store.save(identifier, "changed", {})
                with self.assertRaises(ValueError):
                    self.store.delete_many([identifier])
        self.assertIn("outside", self.outside.read_text(encoding="utf-8"))
        self.assertEqual(self.store.load_content("手册[v2].2026_p0")["content"], "原文")

    def test_validate_entire_delete_request_before_mutation(self):
        with self.assertRaises(ValueError):
            self.store.delete_many(["手册[v2].2026_p0", "../outside"])
        self.assertEqual(self.store.load_content("手册[v2].2026_p0.json")["content"], "原文")

    def test_corrupt_json_and_invalid_metadata_do_not_break_listing(self):
        folder = self.root / "parents"
        for name, content in {"broken": "{", "list": "[]", "metadata": '{"metadata":[]}',
                              "source": '{"metadata":{"source":[]}}'}.items():
            (folder / f"{name}.json").write_text(content, encoding="utf-8")
        self.assertEqual(self.store.list_sources(), ["手册[v2].2026.pdf"])
        self.assertEqual(self.store.find_ids_by_sources(["手册[v2].2026.pdf"]), ["手册[v2].2026_p0"])

    def test_missing_parent_is_a_normal_empty_result(self):
        self.assertEqual(self.store.load_content("missing_p0"), {})


if __name__ == "__main__":
    unittest.main()
