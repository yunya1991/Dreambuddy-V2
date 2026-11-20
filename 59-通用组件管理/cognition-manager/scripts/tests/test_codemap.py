"""cm map 四类检查的单元测试（锚点越界 / 无文档代码 / 文档漂移）。"""

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import codemap  # noqa: E402


class CodeMapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE docs(path TEXT PRIMARY KEY, mtime REAL)")
        self.conn.execute("CREATE TABLE edges(src TEXT, dst TEXT, kind TEXT)")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_anchor_out_of_range(self):
        self.write("mod/code.py", "a = 1\nb = 2\n")
        self.write("mod/doc.md", "见 [code](./code.py#L10-L20)\n")
        result = codemap.analyze(self.root, {"ignore": []}, self.conn)
        self.assertEqual(result["metrics"]["anchor_out_of_range"], 1)
        self.assertEqual(result["details"]["anchor_out_of_range"][0]["file_lines"], 2)

    def test_anchor_in_range_is_ok(self):
        self.write("mod/code.py", "a = 1\nb = 2\nc = 3\n")
        self.write("mod/doc.md", "见 [code](./code.py#L2-L3)\n")
        result = codemap.analyze(self.root, {"ignore": []}, self.conn)
        self.assertEqual(result["metrics"]["anchor_out_of_range"], 0)

    def test_code_without_doc(self):
        self.write("mod/INDEX.md", "# 模块\n")
        self.write("mod/docs.md", "# 说明\n")
        self.write("mod/orphan.py", "print(1)\n")
        self.write("mod/covered.py", "print(2)\n")
        self.conn.execute("INSERT INTO edges VALUES('mod/docs.md','mod/covered.py','references')")
        result = codemap.analyze(self.root, {"ignore": []}, self.conn)
        self.assertEqual(result["metrics"]["code_without_doc"], 1)
        self.assertEqual(result["details"]["code_without_doc"][0], "mod/orphan.py")

    def test_doc_drift(self):
        code = self.write("mod/code.py", "a = 1\n")
        self.write("mod/doc.md", "见 [code](./code.py)\n")
        old = time.time() - 10 * 86400
        os.utime(code, (time.time(), time.time()))
        self.conn.execute("INSERT INTO docs VALUES('mod/doc.md', ?)", (old,))
        self.conn.execute("INSERT INTO edges VALUES('mod/doc.md','mod/code.py','references')")
        result = codemap.analyze(self.root, {"ignore": []}, self.conn)
        self.assertEqual(result["metrics"]["doc_drift"], 1)
        self.assertEqual(result["details"]["doc_drift"][0]["target"], "mod/code.py")


if __name__ == "__main__":
    unittest.main()
