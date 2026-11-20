"""CogSteward 自检：功能用例 + V1 / V6 / V8 可复核校验 + M2 路由 / 回滚。

运行：
    python3 -m unittest discover -s scripts/tests -v
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PACKAGE_ROOT / "scripts"
CLI = SCRIPTS_DIR / "cm_cli.py"
EVAL = SCRIPTS_DIR / "eval_golden.py"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core import (  # noqa: E402
    admission,
    apply as apply_engine,
    contract,
    indexer,
    report,
    router,
    scanner,
    selfcheck,
    signature,
    skill_lint,
    store,
)
import release_check  # noqa: E402

MODULE_ROOT = PACKAGE_ROOT.parent


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_fixture(root: Path):
    write_text(root / "README.md", "# 示例工作区\n\n[指南](docs/guide.md)\n")
    write_text(root / "docs" / "guide.md", "# 指南\n\n[返回](../README.md)\n")
    write_text(root / "notes" / "中文 文件.md", "# 中文文件\n\n内容\n")

    links = ["# 链接样本\n"]
    for i in range(1, 31):
        links.append("- [断链 {}](missing-{:02d}.md)".format(i, i))
    for i in range(200):
        target = "../README.md" if i % 2 == 0 else "../docs/guide.md"
        links.append("- [正常 {}]({})".format(i, target))
    write_text(root / "specs" / "links.md", "\n".join(links) + "\n")

    write_text(root / "skills" / "demo" / "SKILL.md", (
        "---\nname: demo\ndisplay_name: 演示\nversion: 0.1.0\n"
        "triggers: [日报, 汇报]\n---\n\n# 演示技能\n"
    ))

    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n demo")
    (root / "assets" / "manual.pdf").write_bytes(b"%PDF-1.4 demo")

    write_text(root / ".git" / "ignored.md", "# 不应被索引\n")
    write_text(root / "node_modules" / "pkg" / "readme.md", "# 不应被索引\n")
    write_text(root / "__pycache__" / "x.pyc", "binary-ish")


def run_cli(root: Path, *argv):
    return subprocess.run(
        [sys.executable, str(CLI), "--root", str(root), *argv],
        capture_output=True, text=True, timeout=120,
    )


class CoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_fixture(self.root)
        store.init_workspace(self.root, mode="dev")

    def tearDown(self):
        self._tmp.cleanup()

    def scan(self, full=False):
        config = store.load_config(self.root)
        conn = store.connect(self.root)
        try:
            return scanner.scan(self.root, config, conn, full=full)
        finally:
            conn.close()

    def doctor(self):
        config = store.load_config(self.root)
        conn = store.connect(self.root)
        try:
            return report.doctor(self.root, config, conn)
        finally:
            conn.close()

    # ---------- 初始化 ----------

    def test_init_layout(self):
        base = self.root / ".cm"
        for sub in ("traces", "backup", "cache"):
            self.assertTrue((base / sub).is_dir(), sub)
        self.assertTrue((base / "config.yaml").exists())
        self.assertTrue((base / "index.db").exists())
        config = store.load_config(self.root)
        self.assertEqual(config["mode"], "dev")
        self.assertEqual(config["high_threshold"], 0.8)
        self.assertEqual(config["low_threshold"], 0.5)
        self.assertFalse(config["apply"])
        self.assertTrue(config["signature_salt"])

    def test_init_existing_keeps_config(self):
        salt = store.load_config(self.root)["signature_salt"]
        result = store.init_workspace(self.root, mode="office")
        self.assertEqual(result["status"], "existing")
        self.assertEqual(store.load_config(self.root)["signature_salt"], salt)

    def test_office_mode_switch(self):
        other = Path(tempfile.mkdtemp())
        try:
            store.init_workspace(other, mode="office")
            config = store.load_config(other)
            self.assertEqual(config["mode"], "office")
            self.assertEqual(config["low_threshold"], 0.55)
            self.assertEqual(config["session_ttl_days"], 14)
            self.assertEqual(config["materialize"], "none")
        finally:
            shutil.rmtree(other, ignore_errors=True)

    # ---------- 扫描 ----------

    def test_scan_classification_and_ignore(self):
        stats = self.scan()
        # README / guide / 中文文件 / links = 4 文本；png / pdf = 2 二进制
        self.assertEqual(stats["text"], 4)
        self.assertEqual(stats["binary"], 2)
        self.assertEqual(stats["skills"], 1)
        self.assertEqual(stats["errors"], 0)

        conn = store.connect(self.root)
        try:
            paths = {row["path"] for row in conn.execute("SELECT path FROM docs")}
            skill_path = conn.execute("SELECT path FROM skills").fetchone()["path"]
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(docs)")}
        finally:
            conn.close()

        self.assertIn("README.md", paths)
        self.assertIn("notes/中文 文件.md", paths)
        self.assertIn("assets/logo.png", paths)
        self.assertEqual(skill_path, "skills/demo/SKILL.md")
        for ignored in (".git/ignored.md", "node_modules/pkg/readme.md", "__pycache__/x.pyc"):
            self.assertNotIn(ignored, paths)
        self.assertNotIn("body", columns)
        self.assertNotIn("content", columns)

    def test_extract_links_skips_code_fences(self):
        text = (
            "[真链接](docs/guide.md)\n\n"
            "```python\n"
            "return clip[0, 1](Score_new)\n"
            "outcome = PATH_VERBS[inner](args)\n"
            "handler(**parameters)\n"
            "```\n"
            "[另一个](README.md)\n"
        )
        self.assertEqual(scanner.extract_links(text), ["docs/guide.md", "README.md"])

    def test_scan_incremental_is_idempotent(self):
        first = self.scan()
        second = self.scan()
        self.assertEqual(second["scanned"], 0)
        self.assertEqual(second["unchanged"], first["scanned"] + first["unchanged"])
        conn = store.connect(self.root)
        try:
            count = conn.execute("SELECT COUNT(*) AS n FROM docs").fetchone()["n"]
            docs_fts = conn.execute("SELECT COUNT(*) AS n FROM docs_fts").fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(count, first["text"] + first["binary"])
        self.assertEqual(docs_fts, count)

    def test_symlink_loop_is_safe(self):
        loop = self.root / "docs" / "loop"
        try:
            os.symlink(self.root / "docs", loop)
        except (OSError, NotImplementedError):
            self.skipTest("symlink 不可用")
        stats = self.scan()
        self.assertEqual(stats["errors"], 0)

    # ---------- 体检 ----------

    def test_doctor_broken_links_exact(self):
        self.scan()
        result = self.doctor()
        self.assertEqual(result["metrics"]["broken_links"], 30)
        self.assertEqual(result["metrics"]["orphan_files"], 0)
        self.assertEqual(result["metrics"]["index_drift"], 0)
        self.assertEqual(result["metrics"]["skill_conflicts"], 0)
        self.assertLessEqual(len(result["recommendations"]), 3)
        self.assertTrue(any("断链" in item for item in result["recommendations"]))
        self.assertIn(result["health"], ("good", "attention", "poor"))

    def test_doctor_orphan_and_drift(self):
        self.scan()
        write_text(self.root / "notes" / "new.md", "# 新文件\n")
        write_text(self.root / "docs" / "guide.md", "# 指南\n\n已被修改\n")

        result = self.doctor()
        self.assertEqual(result["metrics"]["orphan_files"], 1)
        self.assertEqual(result["metrics"]["index_drift"], 1)
        reasons = {item["reason"] for item in result["details"]["index_drift"]}
        self.assertIn("hash_mismatch", reasons)

        self.scan()
        repaired = self.doctor()
        self.assertEqual(repaired["metrics"]["orphan_files"], 0)
        self.assertEqual(repaired["metrics"]["index_drift"], 0)

    def test_deleted_file_counts_as_drift(self):
        self.scan()
        (self.root / "notes" / "中文 文件.md").unlink()
        result = self.doctor()
        self.assertGreaterEqual(result["metrics"]["index_drift"], 1)
        reasons = {item["reason"] for item in result["details"]["index_drift"]}
        self.assertIn("missing", reasons)

    def test_skill_conflicts(self):
        write_text(self.root / "skills" / "other" / "SKILL.md", (
            "---\nname: demo\nversion: 0.2.0\ntriggers: [汇报, 周报]\n---\n\n# 另一个技能\n"
        ))
        write_text(self.root / "skills" / "no-version" / "SKILL.md", (
            "---\nname: no-version\n---\n\n# 无版本\n"
        ))
        self.scan()
        result = self.doctor()
        kinds = {item["kind"] for item in result["details"]["skill_conflicts"]}
        self.assertIn("duplicate_name", kinds)
        self.assertIn("missing_version", kinds)
        self.assertIn("trigger_overlap", kinds)
        self.assertGreaterEqual(result["metrics"]["skill_conflicts"], 3)

    def test_sessions_and_pending(self):
        conn = sqlite3.connect(str(self.root / ".cm" / "index.db"))
        try:
            now = time.time()
            conn.execute(
                "INSERT INTO sessions(content_ref, created_at, expires_at, triaged_at) "
                "VALUES('s1', ?, ?, NULL)", (now - 8 * 86400, now + 6 * 86400))
            conn.execute(
                "INSERT INTO pending(kind, payload_ref, created_at, review_count, state) "
                "VALUES('memory', 'p1', ?, 0, 'open')", (now - 48 * 3600,))
            conn.commit()
        finally:
            conn.close()

        result = self.doctor()
        self.assertEqual(result["metrics"]["stale_sessions"], 1)
        self.assertEqual(result["metrics"]["pending_backlog"], 1)
        self.assertAlmostEqual(result["metrics"]["oldest_pending_hours"], 48.0, delta=1.0)
        self.assertEqual(result["health"], "poor")

    # ---------- CLI ----------

    def test_cli_smoke_json(self):
        proc = run_cli(self.root, "init", "--scan", "--doctor", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIn("init", payload)
        self.assertIn("scan", payload)
        self.assertEqual(payload["doctor"]["metrics"]["broken_links"], 30)
        self.assertEqual(payload["doctor"]["schema_version"], "1.0")

    def test_cli_not_initialized_exit_code(self):
        other = Path(tempfile.mkdtemp())
        try:
            proc = run_cli(other, "doctor")
            self.assertEqual(proc.returncode, store.EXIT_NOT_INIT)
            self.assertIn("尚未初始化", proc.stderr)
        finally:
            other.rmdir()

    def test_cli_human_output(self):
        proc = run_cli(self.root, "init", "--scan", "--doctor")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("工作区体检", proc.stdout)
        self.assertIn("断链", proc.stdout)
        self.assertIn("建议：", proc.stdout)


class SignatureCase(unittest.TestCase):
    """M2：意图指纹归一化。"""

    def test_same_intent_same_fingerprint(self):
        salt = "test-salt"
        first = "帮我创建一份发布检查清单"
        second = "新建发布检查清单，麻烦弄一下"
        self.assertEqual(signature.normalize(first), signature.normalize(second))
        self.assertEqual(
            signature.fingerprint(first, salt),
            signature.fingerprint(second, salt),
        )
        self.assertEqual(len(signature.fingerprint(first, salt)), 16)

    def test_salt_isolated(self):
        text = "帮我创建一份发布检查清单"
        self.assertNotEqual(
            signature.fingerprint(text, "salt-a"),
            signature.fingerprint(text, "salt-b"),
        )

    def test_stopwords_and_verb_normalization(self):
        normalized = signature.normalize("请帮我执行一下部署脚本")
        self.assertIn("deploy", normalized)
        self.assertIn("run", normalized)
        self.assertNotIn("帮我", normalized)


class AdmissionCase(unittest.TestCase):
    """M2：记忆准入四问。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_text(self.root / "docs" / "guide.md", "# 指南\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_non_memory_skipped(self):
        result = admission.evaluate(self.root, "doc")
        self.assertFalse(result["applicable"])
        self.assertTrue(result["passed"])
        self.assertFalse(result["pending"])

    def test_not_derivable_passes(self):
        result = admission.evaluate(self.root, "memory", {
            "a1": {"result": "not_derivable"},
            "a2": {"result": "none"},
            "a3": {"result": "evidence_ref", "ref": "docs/guide.md"},
            "a4": {"result": "yes"},
        })
        self.assertTrue(result["passed"])
        self.assertFalse(result["pending"])
        self.assertEqual(result["decision"], "accept")

    def test_derivable_missing_path_goes_pending(self):
        result = admission.evaluate(self.root, "memory", {
            "a1": {"result": "derivable_from", "paths": ["docs/missing.md"]},
            "a2": {"result": "none"},
            "a3": {"result": "none"},
            "a4": {"result": "yes"},
        })
        self.assertTrue(result["pending"])
        self.assertEqual(result["checks"]["A1"]["result"], "unknown")

    def test_a4_no_blocks(self):
        result = admission.evaluate(self.root, "memory", {
            "a1": {"result": "not_derivable"},
            "a2": {"result": "none"},
            "a3": {"result": "evidence_ref", "ref": "docs/guide.md"},
            "a4": {"result": "no"},
        })
        self.assertTrue(result["blocked"])
        self.assertEqual(result["decision"], "reject")

    def test_a3_none_caps_confidence(self):
        result = admission.evaluate(self.root, "memory", {
            "a1": {"result": "not_derivable"},
            "a2": {"result": "none"},
            "a3": {"result": "none"},
            "a4": {"result": "yes"},
        })
        self.assertEqual(result["kind"], "observation")
        self.assertEqual(result["confidence_cap"], 0.5)


class RouterCase(unittest.TestCase):
    """M2：路由、confidence 复算、plan/apply、幂等、回滚。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_text(self.root / "docs" / "guide.md", "# 指南\n\n内容\n")
        write_text(self.root / "docs" / "keep.md", "# 保留\n")
        store.init_workspace(self.root, mode="dev")
        self.config = store.load_config(self.root)
        self.conn = store.connect(self.root)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def route(self, content, **kwargs):
        return router.route(self.root, self.config, self.conn, content, **kwargs)

    def test_doc_route_is_high_but_plan_does_not_write(self):
        before = sorted(path.name for path in (self.root / "docs").iterdir())
        result = self.route("接口规范说明：读取 docs/guide.md")
        self.assertEqual(result["primary"], "doc")
        self.assertEqual(result["apply_mode"], "plan")
        self.assertEqual(result["next_action"], "create_doc")
        self.assertGreaterEqual(result["confidence"], 0.8)
        self.assertIsNotNone(result["patch"])
        self.assertFalse(result["requires_user_confirm"])
        self.assertEqual(result["schema_version"], "1.1")
        self.assertTrue(result["idempotency_key"].startswith("sha256:"))
        after = sorted(path.name for path in (self.root / "docs").iterdir())
        self.assertEqual(before, after, "plan 模式不得落盘")

        parts = result["confidence_parts"]
        expected = (
            self.config["weight_evidence"] * parts["evidence"]
            + self.config["weight_consistency"] * parts["consistency"]
            + self.config["weight_history"] * parts["history"]
            + self.config["weight_conflict"] * (1 - parts["conflict"])
        )
        self.assertAlmostEqual(result["confidence"], expected, delta=0.001)

    def test_skill_requires_two_executions(self):
        content = "发布检查清单：执行发布流程步骤"
        first = self.route(content)
        self.assertEqual(first["primary"], "skill")
        self.assertTrue(first["requires_user_confirm"])
        self.assertEqual(first["next_action"], "ask_user")

        router.mark_done(self.root, self.config, self.conn, content)
        still_one = self.route(content)
        self.assertTrue(still_one["requires_user_confirm"])

        router.mark_done(self.root, self.config, self.conn, content)
        third = self.route(content)
        self.assertFalse(third["requires_user_confirm"])
        self.assertEqual(third["next_action"], "create_skill")
        self.assertGreaterEqual(third["confidence"], 0.8)
        self.assertEqual(third["evidence"][0]["kind"], "execution_count")
        self.assertEqual(third["evidence"][0]["value"], 2)

    def test_confirm_exempts_but_is_not_execution(self):
        content = "发布检查清单：执行发布流程步骤"
        router.mark_done(self.root, self.config, self.conn, content)
        confirmed = self.route(content, confirm=True)
        self.assertFalse(confirmed["requires_user_confirm"])
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM executions").fetchone()["n"]
        self.assertEqual(count, 1)
        confirm_row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM intent_confirms").fetchone()["n"]
        self.assertEqual(confirm_row, 1)

    def test_low_confidence_returns_no_patch(self):
        result = self.route("随便聊聊今天的天气")
        self.assertEqual(result["primary"], "session")
        self.assertEqual(result["next_action"], "ask_user")
        self.assertIsNone(result["patch"])
        self.assertLess(result["confidence"], self.config["low_threshold"])

    def test_memory_pending_without_facts(self):
        result = self.route("踩坑经验：上次部署失败的原因")
        self.assertEqual(result["primary"], "memory")
        self.assertEqual(result["next_action"], "write_pending")
        self.assertTrue(result["admission"]["pending"])
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM pending WHERE state='open'").fetchone()
        self.assertEqual(row["n"], 1)

    def test_memory_write_memory_with_facts(self):
        result = self.route(
            "踩坑经验：docs/guide.md 里的部署失败原因",
            facts={
                "a1": {"result": "not_derivable"},
                "a2": {"result": "none"},
                "a3": {"result": "evidence_ref", "ref": "docs/guide.md"},
                "a4": {"result": "yes"},
            },
        )
        self.assertEqual(result["primary"], "memory")
        self.assertEqual(result["next_action"], "write_memory")
        self.assertIsNotNone(result["patch"])
        self.assertEqual(result["target"]["path"], ".cm/memory/{}.md".format(result["signature"]))

    def test_apply_is_idempotent(self):
        store.update_config(self.root, {"apply": True})
        config = store.load_config(self.root)
        content = "接口规范说明：读取 docs/guide.md"
        results = [
            router.route(self.root, config, self.conn, content, apply_requested=True)
            for _ in range(5)
        ]
        self.assertEqual(results[0]["apply_mode"], "apply")
        self.assertTrue(results[0]["apply"]["applied"])
        for item in results[1:]:
            self.assertEqual(item["apply_mode"], "plan")
            self.assertTrue(item["apply"]["replayed"])
            self.assertFalse(item["apply"]["applied"])
        applied = self.conn.execute(
            "SELECT COUNT(*) AS n FROM apply_runs").fetchone()["n"]
        self.assertEqual(applied, 1)

    def test_patch_over_ten_files_degrades_to_plan(self):
        apply_engine.MAX_FILES = 10
        store.update_config(self.root, {"apply": True})
        config = store.load_config(self.root)
        patch = {
            "summary": "超限",
            "files": [
                {"op": "create", "path": "docs/over-{}.md".format(index),
                 "content": "x", "sha256": hashlib.sha256(b"x").hexdigest()}
                for index in range(11)
            ],
        }
        with self.assertRaises(store.CmError):
            apply_engine.apply_patch(self.root, "rt-20261119-9999", "sha256:over-limit",
                                     patch, conn=None)


class ApplyRollbackCase(unittest.TestCase):
    """M2：三类 op 的快照与逆序回滚。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_text(self.root / "docs" / "a.md", "# A\n\n原始内容\n")
        write_text(self.root / "docs" / "b.md", "# B\n\n待删除\n")
        self.original_a = (self.root / "docs" / "a.md").read_bytes()
        self.original_b = (self.root / "docs" / "b.md").read_bytes()
        store.init_workspace(self.root, mode="dev")

    def tearDown(self):
        self._tmp.cleanup()

    def _sha(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_apply_and_rollback_three_ops(self):
        new_content = "# 新文件\n\n内容\n"
        modified = "# A\n\n追加内容\n"
        patch = {
            "summary": "三类操作",
            "files": [
                {"op": "create", "path": "docs/new.md", "content": new_content,
                 "sha256": hashlib.sha256(new_content.encode()).hexdigest()},
                {"op": "modify", "path": "docs/a.md", "content": modified,
                 "sha256": hashlib.sha256(modified.encode()).hexdigest()},
                {"op": "delete", "path": "docs/b.md", "content": "", "sha256": ""},
            ],
        }
        conn = store.connect(self.root)
        try:
            applied = apply_engine.apply_patch(
                self.root, "rt-20261119-0001", "sha256:rollback-test", patch, conn=conn)
            self.assertTrue(applied["applied"])
            self.assertTrue((self.root / "docs" / "new.md").exists())
            self.assertEqual((self.root / "docs" / "a.md").read_text(encoding="utf-8"), modified)
            self.assertFalse((self.root / "docs" / "b.md").exists())

            manifest = self.root / ".cm" / "backup" / "rt-20261119-0001" / "manifest.json"
            self.assertTrue(manifest.exists())
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "applied")
            self.assertEqual(len(data["files"]), 3)

            rolled = apply_engine.rollback(self.root, "rt-20261119-0001", conn=conn)
            self.assertTrue(rolled["rolled_back"])
            self.assertFalse((self.root / "docs" / "new.md").exists())
            self.assertEqual((self.root / "docs" / "a.md").read_bytes(), self.original_a)
            self.assertTrue((self.root / "docs" / "b.md").exists())
            self.assertEqual(
                (self.root / "docs" / "b.md").read_bytes(), self.original_b)
        finally:
            conn.close()

    def test_rollback_aborts_on_external_change(self):
        modified = "# A\n\n补丁内容\n"
        patch = {
            "summary": "仅修改",
            "files": [
                {"op": "modify", "path": "docs/a.md", "content": modified,
                 "sha256": hashlib.sha256(modified.encode()).hexdigest()},
            ],
        }
        conn = store.connect(self.root)
        try:
            apply_engine.apply_patch(
                self.root, "rt-20261119-0002", "sha256:conflict-test", patch, conn=conn)
            write_text(self.root / "docs" / "a.md", "# A\n\n补丁后被手改\n")
            rolled = apply_engine.rollback(self.root, "rt-20261119-0002", conn=conn)
            self.assertFalse(rolled["rolled_back"])
            self.assertEqual(rolled["conflicts"][0]["reason"], "hash_mismatch")
            self.assertIn("补丁后被手改",
                          (self.root / "docs" / "a.md").read_text(encoding="utf-8"))
        finally:
            conn.close()


class M2CliCase(unittest.TestCase):
    """M2：CLI 新命令冒烟。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_text(self.root / "docs" / "guide.md", "# 指南\n")
        store.init_workspace(self.root, mode="dev")

    def tearDown(self):
        self._tmp.cleanup()

    def test_route_json_and_config(self):
        proc = run_cli(self.root, "route", "接口规范说明：读取 docs/guide.md", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["primary"], "doc")
        self.assertEqual(payload["apply_mode"], "plan")

        proc = run_cli(self.root, "config", "apply=on", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        config = json.loads(proc.stdout)["config"]
        self.assertTrue(config["apply"])

        proc = run_cli(self.root, "route", "接口规范说明：读取 docs/guide.md",
                       "--apply", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["apply_mode"], "apply")
        self.assertTrue(payload["apply"]["applied"])

        run_id = payload["id"]
        proc = run_cli(self.root, "rollback", run_id, "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["rolled_back"])

    def test_mark_done_json(self):
        proc = run_cli(self.root, "mark-done", "执行发布流程步骤", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["executions_90d"], 1)
        self.assertEqual(payload["source"], "mark_done")


class M3Case(unittest.TestCase):
    """M3：index 总览 / check 只读 / skill lint。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_fixture(self.root)
        store.init_workspace(self.root, mode="dev")

    def tearDown(self):
        self._tmp.cleanup()

    def test_index_reports_counts(self):
        proc = run_cli(self.root, "index", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["command"], "index")
        self.assertEqual(payload["mode"], "incremental")
        self.assertEqual(payload["schema_version"], "1.0")
        counts = payload["counts"]
        self.assertEqual(counts["docs"], 6)
        self.assertEqual(counts["skills"], 1)
        self.assertEqual(counts["broken_links"], 30)
        self.assertEqual(counts["orphan_files"], 0)
        self.assertEqual(counts["index_drift"], 0)
        self.assertTrue(payload["notes"])

    def test_index_check_does_not_rebuild(self):
        run_cli(self.root, "index", "--json")
        write_text(self.root / "notes" / "late.md", "# 后来\n")

        checked = json.loads(
            run_cli(self.root, "index", "--check", "--json").stdout)
        self.assertEqual(checked["mode"], "check")
        self.assertEqual(checked["counts"]["orphan_files"], 1)
        self.assertEqual(checked["counts"]["docs"], 6)

        rebuilt = json.loads(
            run_cli(self.root, "index", "--json").stdout)
        self.assertEqual(rebuilt["counts"]["orphan_files"], 0)
        self.assertEqual(rebuilt["counts"]["docs"], 7)

    def test_index_human_output(self):
        proc = run_cli(self.root, "index")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("文档总数", proc.stdout)
        self.assertIn("孤儿文件", proc.stdout)

    def test_skill_lint_clean(self):
        proc = run_cli(self.root, "skill", "lint", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["summary"]["skills"], 1)
        self.assertEqual(payload["summary"]["total"], 0)
        self.assertEqual(payload["issues"], [])

    def test_skill_lint_detects_issues(self):
        write_text(self.root / "skills" / "bad" / "SKILL.md", (
            "---\nname: demo\ntriggers: 日报, 周报\n"
            "depends_on: [不存在的技能]\n---\n\n# 坏技能\n"
        ))
        write_text(self.root / "skills" / "user" / "SKILL.md", (
            "---\nname: user\nversion: 0.1.0\ntriggers: [复盘]\n"
            "depends_on: [demo]\n---\n\n# 使用演示\n"
        ))
        proc = run_cli(self.root, "skill", "lint", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        kinds = {item["kind"] for item in payload["issues"]}
        self.assertIn("duplicate_name", kinds)
        self.assertIn("missing_version", kinds)
        self.assertIn("triggers_not_list", kinds)
        self.assertIn("missing_dependency", kinds)
        self.assertIn("trigger_overlap", kinds)
        self.assertGreaterEqual(payload["summary"]["error"], 2)
        missing = [
            item for item in payload["issues"]
            if item["kind"] == "missing_dependency"
        ]
        self.assertEqual([item["skills"] for item in missing], [["demo"]])

    def test_skill_lint_ignores_identical_cross_module_copy(self):
        content = (
            "---\nname: mirror\nversion: 1.0.0\ntriggers: [镜像]\n---\n\n# 镜像技能\n"
        )
        write_text(self.root / "skills" / "mod-a" / "mirror" / "SKILL.md", content)
        write_text(self.root / "skills" / "mod-b" / "mirror" / "SKILL.md", content)
        proc = run_cli(self.root, "skill", "lint", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        kinds = {item["kind"] for item in payload["issues"]}
        self.assertNotIn("duplicate_name", kinds)

    def test_skill_lint_human_output(self):
        proc = run_cli(self.root, "skill", "lint")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("技能检查", proc.stdout)
        self.assertIn("未发现问题", proc.stdout)

    def test_skill_without_subcommand_is_usage_error(self):
        proc = run_cli(self.root, "skill")
        self.assertEqual(proc.returncode, store.EXIT_USAGE)
        self.assertIn("cm skill lint", proc.stderr)


class PackCase(unittest.TestCase):
    """M2b：pack 只读、预算裁剪、候选字段完整。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_fixture(self.root)
        store.init_workspace(self.root, mode="dev")
        proc = run_cli(self.root, "scan", "--full", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def tearDown(self):
        self._tmp.cleanup()

    def _snapshot(self):
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() and ".cm" not in path.relative_to(self.root).parts
        }

    def test_pack_hits_and_fields(self):
        proc = run_cli(self.root, "pack", "指南", "--budget", "100000", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["read_only"])
        self.assertLessEqual(payload["estimated_tokens"], 100000)
        paths = [item["path"] for item in payload["items"]]
        self.assertIn("docs/guide.md", paths)
        for item in payload["items"]:
            self.assertEqual(
                set(item),
                {"path", "title", "kind", "doc_type", "estimated_tokens", "score", "reason"}
                | ({"version"} if item["kind"] == "skill" else set()),
            )
            self.assertGreater(item["estimated_tokens"], 0)

    def test_pack_skill_trigger_hit(self):
        proc = run_cli(self.root, "pack", "日报 汇报", "--budget", "100000", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        skill_paths = [item["path"] for item in payload["items"] if item["kind"] == "skill"]
        self.assertIn("skills/demo/SKILL.md", skill_paths)

    def test_pack_budget_never_exceeded(self):
        for budget in (1, 5, 12, 40):
            proc = run_cli(self.root, "pack", "指南", "--budget", str(budget), "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertLessEqual(payload["estimated_tokens"], budget)
            if budget == 1:
                self.assertEqual(payload["items"], [])
                self.assertTrue(payload["truncated"])
                self.assertGreater(payload["skipped"], 0)

    def test_pack_is_read_only(self):
        before = self._snapshot()
        run_cli(self.root, "pack", "指南", "--budget", "100000", "--json")
        run_cli(self.root, "pack", "日报", "--budget", "1", "--json")
        self.assertEqual(before, self._snapshot())


class TriageCase(unittest.TestCase):
    """M2b：triage 默认演练，显式开关才迁移状态。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        build_fixture(self.root)
        store.init_workspace(self.root, mode="dev")
        now = time.time()
        conn = store.connect(self.root)
        try:
            conn.execute(
                "INSERT INTO sessions(content_ref, created_at, expires_at, triaged_at) "
                "VALUES('sig-old', ?, ?, NULL)", (now - 10 * 86400, now - 3 * 86400))
            conn.execute(
                "INSERT INTO sessions(content_ref, created_at, expires_at, triaged_at) "
                "VALUES('sig-new', ?, ?, NULL)", (now, now + 3 * 86400))
            conn.execute(
                "INSERT INTO pending(kind, payload_ref, created_at, review_count, state) "
                "VALUES('memory', 'p-new', ?, 0, 'open')", (now,))
            conn.execute(
                "INSERT INTO pending(kind, payload_ref, created_at, review_count, state) "
                "VALUES('memory', 'p-old', ?, 3, 'open')", (now,))
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self):
        conn = store.connect(self.root)
        try:
            sessions = {
                row["content_ref"]: row["triaged_at"]
                for row in conn.execute("SELECT content_ref, triaged_at FROM sessions")
            }
            pending = {
                row["payload_ref"]: (row["review_count"], row["state"])
                for row in conn.execute("SELECT payload_ref, review_count, state FROM pending")
            }
        finally:
            conn.close()
        return sessions, pending

    def test_dry_run_lists_without_mutation(self):
        proc = run_cli(self.root, "triage", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["sessions"]["expired"], 1)
        self.assertEqual(payload["sessions"]["marked_expired"], 0)
        self.assertEqual(payload["pending"]["open"], 2)
        self.assertEqual(payload["pending"]["dropped"], 0)
        sessions, pending = self._state()
        self.assertIsNone(sessions["sig-old"])
        self.assertEqual(pending["p-new"], (0, "open"))
        self.assertEqual(pending["p-old"], (3, "open"))

    def test_apply_migrates_states(self):
        proc = run_cli(self.root, "triage", "--expire-sessions", "--drop-pending", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["dry_run"])
        self.assertEqual(payload["sessions"]["marked_expired"], 1)
        self.assertEqual(payload["pending"]["dropped"], 1)
        self.assertEqual(payload["pending"]["incremented"], 1)
        sessions, pending = self._state()
        self.assertIsNotNone(sessions["sig-old"])
        self.assertIsNone(sessions["sig-new"])
        self.assertEqual(pending["p-new"], (1, "open"))
        self.assertEqual(pending["p-old"], (3, "dropped"))

    def test_drop_threshold_after_reviews(self):
        for _ in range(3):
            proc = run_cli(self.root, "triage", "--drop-pending", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
        _, pending = self._state()
        self.assertEqual(pending["p-new"], (3, "open"))
        proc = run_cli(self.root, "triage", "--drop-pending", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["pending"]["dropped"], 1)
        _, pending = self._state()
        self.assertEqual(pending["p-new"], (3, "dropped"))


class EvalGoldenCase(unittest.TestCase):
    """M2b：eval_golden 的 P/R/F1、κ、校准与退出码。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, rows) -> Path:
        path = self.dir / name
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        return path

    def _run(self, *argv):
        return subprocess.run(
            [sys.executable, str(EVAL), *argv],
            capture_output=True, text=True, timeout=60,
        )

    def test_metrics_kappa_and_below_threshold(self):
        rows = [
            {"id": "g1", "label": "skill", "labeler": "A", "predicted": "skill", "confidence": 0.9},
            {"id": "g2", "label": "skill", "labeler": "A", "predicted": "doc", "confidence": 0.85},
            {"id": "g3", "label": "doc", "labeler": "A", "predicted": "doc", "confidence": 0.7},
            {"id": "g4", "label": "memory", "labeler": "A", "predicted": "memory", "confidence": 0.6},
            {"id": "g5", "label": "session", "labeler": "A", "predicted": "session", "confidence": 0.4},
            {"id": "g1", "label": "skill", "labeler": "B"},
            {"id": "g2", "label": "doc", "labeler": "B"},
            {"id": "g3", "label": "doc", "labeler": "B"},
            {"id": "g4", "label": "session", "labeler": "B"},
        ]
        golden = self._write("golden.jsonl", rows)
        proc = self._run("--golden", str(golden), "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        payload = json.loads(proc.stdout)
        metrics = payload["metrics"]
        by_label = {item["label"]: item for item in metrics["per_class"]}
        self.assertEqual(by_label["skill"]["precision"], 1.0)
        self.assertEqual(by_label["skill"]["recall"], 0.5)
        self.assertEqual(by_label["doc"]["precision"], 0.5)
        self.assertEqual(by_label["memory"]["f1"], 1.0)
        self.assertEqual(metrics["accuracy"], 0.8)
        self.assertAlmostEqual(metrics["macro_f1"], 0.8333, places=3)
        self.assertEqual(payload["calibration"]["high_precision"], 0.5)
        self.assertIsNotNone(payload["calibration"]["ece"])
        self.assertAlmostEqual(payload["agreement"]["value"], 0.3333, places=3)
        self.assertEqual(payload["agreement"]["pairs"], 4)
        self.assertEqual(payload["status"], "below_threshold")

    def test_pass_threshold(self):
        rows = [
            {"id": "p{}".format(i), "label": label, "labeler": "A",
             "predicted": label, "confidence": 0.9}
            for i, label in enumerate(("skill", "doc", "memory", "session"))
        ]
        golden = self._write("pass.jsonl", rows)
        proc = self._run("--golden", str(golden), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertAlmostEqual(payload["metrics"]["macro_f1"], 1.0)
        self.assertAlmostEqual(payload["calibration"]["ece"], 0.1)

    def test_missing_data_exit_codes(self):
        proc = self._run("--golden", str(self.dir / "nope.jsonl"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("需人工标注", proc.stderr)

        golden = self._write("unlabeled.jsonl", [{"id": "x", "content": "无标注"}])
        proc = self._run("--golden", str(golden))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("需人工标注", proc.stderr)

    def test_no_predictions_is_insufficient(self):
        golden = self._write("labels.jsonl", [
            {"id": "a", "label": "skill", "labeler": "A"},
            {"id": "b", "label": "doc", "labeler": "A"},
        ])
        proc = self._run("--golden", str(golden), "--json")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "insufficient")
        self.assertIn("需人工标注", payload["note"])


class ConstraintCase(unittest.TestCase):
    """V6 零第三方依赖 / V8 无内部私有数据。"""

    def test_v6_no_third_party_imports(self):
        allowed = set(sys.stdlib_module_names) | {
            "core", "store", "scanner", "report", "cm_cli",
            "signature", "admission", "router", "apply", "pack", "triage",
            "indexer", "skill_lint",
        }
        targets = list((SCRIPTS_DIR / "core").glob("*.py")) + [CLI]
        self.assertTrue(targets)
        offenders = []
        for path in targets:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    if name and name not in allowed:
                        offenders.append("{}:{}".format(path.name, name))
        self.assertEqual(offenders, [], "发现第三方依赖：{}".format(offenders))

    def test_v8_no_internal_private_data(self):
        forbidden = ["4-MEMORY", "35-广义", "41-文件索引", "/Users/", "dreambuddy", "VM-"]
        hits = []
        for path in PACKAGE_ROOT.rglob("*"):
            if not path.is_file():
                continue
            if "tests" in path.parts or ".git" in path.parts:
                continue
            if path.suffix.lower() not in {".md", ".yaml", ".yml", ".py"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in forbidden:
                if token.lower() in text.lower():
                    hits.append("{}:{}".format(path.relative_to(PACKAGE_ROOT), token))
        self.assertEqual(hits, [], "发现内部私有数据：{}".format(hits))

    def test_package_layout_matches_platform(self):
        names = {path.name for path in PACKAGE_ROOT.iterdir()}
        self.assertTrue({"SKILL.md", "manifest.yaml", "scripts",
                         "references", "templates"}.issubset(names))
        self.assertNotIn("assets", names)
        self.assertFalse((PACKAGE_ROOT / "assets").exists())

    def test_skill_frontmatter_required_fields(self):
        text = (PACKAGE_ROOT / "SKILL.md").read_text(encoding="utf-8")
        meta = store.parse_flat_yaml(text.split("---", 2)[1])
        for field in ("name", "display_name", "display_name_en", "description",
                      "description_zh", "description_en", "version", "author"):
            self.assertTrue(str(meta.get(field, "")).strip(), "缺少 frontmatter 字段：{}".format(field))
        self.assertRegex(str(meta["version"]), r"^\d+\.\d+\.\d+$")


class V9ExceptionCase(unittest.TestCase):
    """V9 十二例异常路径：可复现者实测，N/A 项写明构造方法后跳过。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self._tmp.cleanup()

    def _is_root(self) -> bool:
        return hasattr(os, "geteuid") and os.geteuid() == 0

    # 1. 空工作区
    def test_v9_01_empty_workspace(self):
        store.init_workspace(self.root, mode="dev")
        proc = run_cli(self.root, "scan", "--full", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["scanned"], 0)
        self.assertEqual(stats["errors"], 0)
        doctor = json.loads(run_cli(self.root, "doctor", "--json").stdout)
        for key in ("broken_links", "orphan_files", "index_drift", "skill_conflicts"):
            self.assertEqual(doctor["metrics"][key], 0)
        self.assertEqual(doctor["health"], "good")

    # 2. 只读工作区
    def test_v9_02_readonly_workspace(self):
        if self._is_root():
            self.skipTest("root 用户不受只读权限限制")
        self.root.chmod(0o500)
        try:
            proc = run_cli(self.root, "init")
            self.assertEqual(proc.returncode, store.EXIT_IO, proc.stderr)
            self.assertIn("文件系统访问失败", proc.stderr)
        finally:
            self.root.chmod(0o700)

    # 3. 超过 max_text_bytes 视为二进制
    def test_v9_03_oversize_text_file(self):
        store.init_workspace(self.root, mode="dev")
        store.update_config(self.root, {"max_text_bytes": 128})
        write_text(self.root / "big.md", "# 大文件\n[断链](missing.md)\n" + "内容" * 200)
        proc = run_cli(self.root, "scan", "--full", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["binary"], 1)
        self.assertEqual(stats["text"], 0)

        conn = store.connect(self.root)
        try:
            row = conn.execute(
                "SELECT doc_type, title FROM docs WHERE path='big.md'").fetchone()
            edges = conn.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(row["doc_type"], "binary")
        self.assertEqual(row["title"], "big")
        self.assertEqual(edges, 0)

    # 4. 非 UTF-8 文本
    def test_v9_04_non_utf8_text(self):
        store.init_workspace(self.root, mode="dev")
        (self.root / "legacy.md").write_bytes(
            "# 旧文件\n".encode("gbk") + b"\xff\xfe\x00bad")
        proc = run_cli(self.root, "scan", "--full", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["text"], 1)

        conn = store.connect(self.root)
        try:
            row = conn.execute(
                "SELECT title FROM docs WHERE path='legacy.md'").fetchone()
        finally:
            conn.close()
        self.assertTrue(row["title"])

    # 5. 符号链接环
    def test_v9_05_symlink_loop(self):
        store.init_workspace(self.root, mode="dev")
        write_text(self.root / "docs" / "guide.md", "# 指南\n")
        try:
            os.symlink(self.root, self.root / "docs" / "loop")
            os.symlink(self.root / "docs" / "guide.md",
                       self.root / "docs" / "guide-link.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlink 不可用")
        proc = run_cli(self.root, "scan", "--full", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["text"], 1)

    # 6. 空格 / 中文文件名
    def test_v9_06_space_and_chinese_names(self):
        store.init_workspace(self.root, mode="dev")
        write_text(self.root / "带 空格 的 目录" / "中文 文件 名.md", "# 标题\n")
        proc = run_cli(self.root, "scan", "--full", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["text"], 1)

        conn = store.connect(self.root)
        try:
            paths = {row["path"] for row in conn.execute("SELECT path FROM docs")}
        finally:
            conn.close()
        self.assertIn("带 空格 的 目录/中文 文件 名.md", paths)

    # 7. 大小写差异路径
    def test_v9_07_case_variants(self):
        store.init_workspace(self.root, mode="dev")
        write_text(self.root / "case" / "Guide.MD", "# 大写扩展名\n")
        proc = run_cli(self.root, "scan", "--full", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["text"], 1)

        run_cli(self.root, "scan", "--full")
        conn = store.connect(self.root)
        try:
            paths = {row["path"] for row in conn.execute("SELECT path FROM docs")}
        finally:
            conn.close()
        self.assertEqual(paths, {"case/Guide.MD"})

    # 8. 权限拒绝
    def test_v9_08_permission_denied(self):
        if self._is_root():
            self.skipTest("root 用户不受文件权限限制")
        store.init_workspace(self.root, mode="dev")
        target = self.root / "secret.md"
        write_text(target, "# 机密\n")
        target.chmod(0o000)
        try:
            proc = run_cli(self.root, "scan", "--full", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            stats = json.loads(proc.stdout)
            self.assertEqual(stats["errors"], 1)
            self.assertEqual(stats["text"], 0)
        finally:
            target.chmod(0o600)

    # 9. 数据库损坏
    def test_v9_09_corrupt_database(self):
        store.init_workspace(self.root, mode="dev")
        (self.root / ".cm" / "index.db").write_bytes(b"not a sqlite database" * 64)
        proc = run_cli(self.root, "doctor")
        self.assertEqual(proc.returncode, store.EXIT_DB, proc.stderr)
        self.assertIn("索引数据库不可用", proc.stderr)

    # 10. 并发写
    def test_v9_10_concurrent_scan(self):
        store.init_workspace(self.root, mode="dev")
        for index in range(120):
            write_text(self.root / "mod" / "doc-{:03d}.md".format(index),
                       "# 文档 {}\n".format(index))

        errors = []

        def worker():
            try:
                config = store.load_config(self.root)
                conn = store.connect(self.root)
                try:
                    scanner.scan(self.root, config, conn, full=True)
                finally:
                    conn.close()
            except Exception as exc:  # noqa: BLE001 - 汇总给主线程断言
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

        conn = store.connect(self.root)
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM docs WHERE status='active'").fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(count, 120)

    # 11. 磁盘空间不足（N/A）
    def test_v9_11_disk_full_na(self):
        """构造方法：mock os.write 抛 ENOSPC，或把小容量 tmpfs 挂到工作区。"""
        self.skipTest(
            "N/A：写路径集中在单个 SQLite 文件与 WAL，ENOSPC 需 mock os.write 注入；"
            "现有回归不覆盖磁盘配额")

    # 12. 中断恢复（N/A）
    def test_v9_12_interrupt_recovery_na(self):
        """构造方法：在 scanner.scan 提交事务前注入 KeyboardInterrupt，再重跑校验幂等。"""
        self.skipTest(
            "N/A：增量扫描幂等（size 未变即跳过），中断后重跑可自愈；"
            "SIGINT 注入需在产线代码加故障点，未实施")


class PerformanceCase(unittest.TestCase):
    """V1 首次体验 ≤30 秒 / V2 扫描 ≤3 秒（1000 文件 fixture）。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        for index in range(1000):
            folder = cls.root / "mod-{:02d}".format(index % 10)
            write_text(
                folder / "doc-{:04d}.md".format(index),
                "# 文档 {}\n\n这是第 {} 个测试文件。\n".format(index, index) + "内容占位。" * 60,
            )

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_v1_first_run_under_30s(self):
        started = time.perf_counter()
        proc = run_cli(self.root, "init", "--scan", "--doctor", "--json")
        elapsed = time.perf_counter() - started
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["scan"]["text"], 1000)
        self.assertLessEqual(elapsed, 30.0, "V1 未通过：{:.2f}s".format(elapsed))
        print("\n[V1] 首次体验 {:.2f}s（≤30s）".format(elapsed))

    def test_v2_scan_index_under_3s(self):
        run_cli(self.root, "init")
        started = time.perf_counter()
        proc = run_cli(self.root, "scan", "--full", "--json")
        elapsed = time.perf_counter() - started
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertLessEqual(elapsed, 3.0, "V2 未通过：{:.2f}s".format(elapsed))
        print("\n[V2] 全量扫描 1000 文件 {:.2f}s（≤3s）".format(elapsed))


class HealthCase(unittest.TestCase):
    """health 统计口径：九项指标全部参与。"""

    def test_clean_is_good(self):
        self.assertEqual(report.health_of({}), "good")

    def test_one_legacy_problem_is_attention(self):
        self.assertEqual(report.health_of({"broken_links": 1}), "attention")

    def test_code_doc_problems_reach_poor(self):
        metrics = {"anchor_out_of_range": 1, "code_without_doc": 1, "doc_drift": 1}
        self.assertEqual(report.health_of(metrics), "poor")

    def test_missing_keys_do_not_raise(self):
        self.assertEqual(report.health_of({"code_without_doc": 1}), "attention")


class ContractCase(unittest.TestCase):
    """指标契约单一源：结构、三端副本、自检与发布闸门。"""

    def test_contract_loads_nine_metrics(self):
        data = contract.load()
        self.assertEqual(data["schema_version"], "1.0")
        self.assertEqual(len(data["metrics"]), 9)
        self.assertEqual(len(data["ratios"]), 5)
        self.assertEqual(tuple(report.PROBLEM_KEYS), contract.problem_keys(data))
        for key in report.PROBLEM_KEYS:
            self.assertTrue(contract.labels(data)[key].strip(), key)

    def test_contract_thresholds_are_monotonic(self):
        for item in contract.metrics():
            self.assertLess(item["warn_at"], item["high_at"], item["key"])

    def test_three_copies_are_identical(self):
        copies = [
            PACKAGE_ROOT / "references" / "metrics-contract.json",
            MODULE_ROOT / "skills" / "cogsteward-pro" / "references" / "metrics-contract.json",
            MODULE_ROOT / "services" / "skillhub-audit-api" / "src" / "metrics-contract.json",
        ]
        digests = {hashlib.sha256(path.read_bytes()).hexdigest() for path in copies}
        self.assertEqual(len(digests), 1, "三端契约副本不一致：{}".format(copies))

    def test_selfcheck_passes(self):
        result = selfcheck.run()
        self.assertTrue(result["ok"], result)

    def test_release_check_passes(self):
        result = release_check.run()
        self.assertTrue(result["ok"], result)

    def test_pro_report_reads_contract_and_flags_coverage(self):
        pro = MODULE_ROOT / "skills" / "cogsteward-pro" / "scripts" / "report.py"
        payload = json.dumps({"metrics": {"broken_links": 3, "doc_drift": 4},
                              "inventory": {"documents": 100}})
        proc = subprocess.run([sys.executable, str(pro), "--metrics", payload],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("契约 v1.0", proc.stdout)
        self.assertIn("未提供孤儿文件指标", proc.stdout)

        full = json.dumps({"metrics": {"broken_links": 3, "orphan_files": 1},
                           "inventory": {"documents": 100}})
        proc = subprocess.run([sys.executable, str(pro), "--metrics", full],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("未提供孤儿文件指标", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
