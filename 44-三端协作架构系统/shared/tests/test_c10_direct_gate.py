"""C10 直连门禁契约测试（SPEC-L0 §6 C10）。

口径：grep 门禁 + 白名单 ratchet（包化前不启用 import-linter）——
白名单外新增直连必须被拦截（exit 1）；存量只减不增。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_db_direct_imports.py"
WHITELIST = REPO_ROOT / "0-系统文档管理" / "db_direct_whitelist.tsv"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_db_direct_imports", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_db_direct_imports", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gate():
    return _load_module()


def _rec(path, kind="sqlite3", in_storage=False):
    return {"kind": kind, "path": path, "line": 1, "in_storage_layer": in_storage}


def test_whitelist_exists_and_nonempty(gate):
    assert WHITELIST.exists(), "C10 白名单缺失（须先 --write-whitelist 登记存量）"
    wl = gate.load_whitelist(WHITELIST)
    assert len(wl) >= 50, f"白名单登记行数异常（{len(wl)}），与 SPEC 基线 85 文件量级不符"


def test_ratchet_current_repo_clean(gate):
    """当前仓库对白名单必须零违规（CI 阻断语义）。"""
    records = gate.scan_repo()
    violations = gate.ratchet_check(records, gate.load_whitelist(WHITELIST))
    assert violations == [], f"白名单外新增直连: {violations[:3]}"


def test_ratchet_blocks_new_file(gate):
    wl = {("a/old.py", "sqlite3"): 2}
    records = [_rec("a/old.py"), _rec("b/new.py")]
    v = gate.ratchet_check(records, wl)
    assert len(v) == 1 and v[0]["type"] == "new_file" and v[0]["path"] == "b/new.py"


def test_ratchet_blocks_count_exceeded(gate):
    wl = {("a/old.py", "sqlite3"): 1}
    records = [_rec("a/old.py"), _rec("a/old.py")]
    v = gate.ratchet_check(records, wl)
    assert len(v) == 1 and v[0]["type"] == "count_exceeded" and v[0]["allowed"] == 1


def test_ratchet_allows_reduction(gate):
    """存量只减不增：白名单内文件直连减少/删除不违规。"""
    wl = {("a/old.py", "sqlite3"): 3, ("b/gone.py", "sqlite3"): 1}
    v = gate.ratchet_check([_rec("a/old.py")], wl)
    assert v == []


def test_storage_layer_exempt(gate):
    """存储层（19-DAL）内直连不计入白名单与违规。"""
    records = [_rec("19-数据访问层/dreambuddy_dal/x.py", in_storage=True)]
    assert gate.whitelist_counts(records) == {}
    assert gate.ratchet_check(records, {}) == []


def test_whitelist_roundtrip(gate, tmp_path):
    records = [_rec("a/x.py"), _rec("a/x.py"), _rec("b/y.py", kind="psycopg2")]
    p = tmp_path / "wl.tsv"
    n = gate.write_whitelist(records, p)
    assert n == 2
    wl = gate.load_whitelist(p)
    assert wl == {("a/x.py", "sqlite3"): 2, ("b/y.py", "psycopg2"): 1}


def test_excludes_runtime_dirs(gate):
    """.cognitive/.trae 等 gitignored 运行态目录不计入扫描。"""
    assert ".cognitive" in gate.EXCLUDE_PARTS
    assert ".trae" in gate.EXCLUDE_PARTS


def test_gate_source_no_direct_db(gate):
    """门禁脚本自身不得出现真实 DB 直连调用（正则字面量除外）。"""
    text = SCRIPT.read_text(encoding="utf-8")
    sq = "sqlite3" + ".connect("
    pg = "psycopg2" + ".connect("
    assert (sq + '"') not in text and (sq + "'") not in text
    assert pg not in text.replace("psycopg2\\.connect", "")
