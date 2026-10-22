"""验证真实的跨进程独占锁及关闭旧连接后的数据完整性。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qdrant_client import QdrantClient, models


class DatabaseLockTest(unittest.TestCase):
    def test_second_process_reports_lock_and_preserves_data(self):
        project = Path(__file__).resolve().parents[1] / "project"
        script = """
import sys
sys.path.insert(0, sys.argv[1])
import config
config.QDRANT_DB_PATH = sys.argv[2]
from db.vector_db_manager import VectorDbManager, KnowledgeBaseInUseError
try:
    VectorDbManager()
except KnowledgeBaseInUseError as exc:
    print(str(exc))
    sys.exit(1)
"""
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "db")
            owner = QdrantClient(path=database)
            try:
                owner.create_collection("test", vectors_config=models.VectorParams(
                    size=2, distance=models.Distance.COSINE))
                owner.upsert("test", points=[models.PointStruct(id=1, vector=[1.0, 0.0])])
                env = dict(os.environ, DEEPSEEK_API_KEY="offline-test",
                           DASHSCOPE_API_KEY="offline-test", PYTHONIOENCODING="utf-8")
                result = subprocess.run([sys.executable, "-c", script, str(project), database],
                                        env=env, capture_output=True, text=True,
                                        encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("知识库正在被另一个程序使用", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)
                self.assertEqual(owner.count("test").count, 1)
            finally:
                owner.close()

            reopened = QdrantClient(path=database)
            try:
                self.assertEqual(reopened.count("test").count, 1)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
