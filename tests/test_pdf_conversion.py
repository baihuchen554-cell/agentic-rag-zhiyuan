"""实际转换带方括号和多点文件名的 PDF，防止被误当成通配模式。"""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
import pymupdf
from utils import pdf_to_markdown


class PdfConversionTest(unittest.TestCase):
    def test_brackets_and_dots_in_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "学生手册[v2].2026.pdf"
            with pymupdf.open() as document:
                page = document.new_page()
                page.insert_text((72, 200), "Student handbook test document\n" +
                                 "This paragraph explains rules and learning requirements.\n" * 15)
                document.save(source)
            output = root / "markdown"
            output.mkdir()
            pdf_to_markdown(source, output)
            expected = output / "学生手册[v2].2026.md"
            self.assertIn("Student handbook", expected.read_text(encoding="utf-8"))
            self.assertFalse((output / "学生手册[v2].md").exists())
            # 文件句柄必须已关闭，在 Windows 上也应能重命名原 PDF。
            source.rename(root / "renamed.pdf")
