"""C5 第六批：_probe_sqlite_records 只读直连收编契约测试。

覆盖：
  - probe 文件 sqlite3 直连已消除（connect 计数 = 0），port 上界只减不增；
  - fetch_all_rows_id_desc 开关关（legacy）与开关开（FD_PROBE_STORE_PORT=1）
    输出逐字段相等（id DESC 全序，无过滤）；
  - FAIL-OPEN（DB 缺失 port 分支返回 []）；legacy 分支异常上抛保持原语义；
  - 默认 legacy：开关未设时 port 故障不影响结果（双模块对象两侧打桩）。

注：11 系统白名单其余 14 个 legacy 条目不属本批——
  bcrm2/storage/kg_store/backfill_fma_shadow 为写路径（SPEC 暂缓，需实盘重启窗口）；
  daily_report_system 读的是 ~/Library WorkBuddy automations.db（项目外 DB，不属 records port 语义）；
  8 个测试/验证文件为 tmp_path 种子脚手架（登记保留，非收编目标）。
"""

import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "11-易经推理系统" / "scripts" / "memory_l4"))
sys.path.insert(0, str(REPO_ROOT / "11-易经推理系统"))

import _five_domain_store_port as port_mod_flat  # noqa: E402  # probe 内部实际引用（独立模块对象）
from scripts.memory_l4 import _five_domain_store_port as port_mod  # noqa: E402

L4 = REPO_ROOT / "11-易经推理系统/scripts/memory_l4"
PROBE_PATH = L4 / "_probe_sqlite_records.py"
PORT_PATH = L4 / "_five_domain_store_port.py"


@contextmanager
def _switch(on: bool):
    name = "FD_PROBE_STORE_PORT"
    old = os.environ.get(name)
    if on:
        os.environ[name] = "1"
    else:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def _seed(tmp_path: Path) -> str:
    db = tmp_path / "records.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, "
        "category TEXT, sub_category TEXT, metrics TEXT, raw TEXT, "
        "timeseries TEXT, timestamp TEXT)"
    )
    rows = [
        ("fred", "macro", "FEDFUNDS", '{"value": 3.7}', "2026-10-01T08:00:00"),
        ("yfinance", "market", "^VIX", '{"value": 22.5}', "2026-10-02T15:00:00"),
        ("panewslab", "overview", "overview_market", '{"cap": 2.7e12}', "2026-10-03T00:00:00"),
    ]
    for src, cat, sub, metrics, stamp in rows:
        conn.execute(
            "INSERT INTO records (source, category, sub_category, metrics, timestamp) "
            "VALUES (?,?,?,?,?)",
            (src, cat, sub, metrics, stamp),
        )
    conn.commit()
    conn.close()
    return str(db)


def test_probe_connects_collected():
    direct = "sqlite3." + "connect("  # 动态拼接避免本文件自身成为命中（C10 ratchet 口径）
    assert PROBE_PATH.read_text(encoding="utf-8").count(direct) == 0
    # port 集中点：新增 fetch_all_rows_id_desc 后 connect 总数上界（只减不增由 ratchet 门禁看守）
    assert PORT_PATH.read_text(encoding="utf-8").count(direct) <= 9


def test_fetch_all_rows_id_desc_port_equals_legacy(tmp_path):
    db = _seed(tmp_path)
    with _switch(False):
        legacy = [tuple(r) for r in port_mod.fetch_all_rows_id_desc(db)]
    with _switch(True):
        ported = [tuple(r.values()) for r in port_mod.fetch_all_rows_id_desc(db)]
    assert legacy == ported
    assert len(legacy) == 3, "种子数据必须产出非空结果，否则等价断言无意义"
    # 列序：source, sub_category, metrics, timestamp, id；id DESC
    ids = [r[4] for r in legacy]
    assert ids == sorted(ids, reverse=True)
    assert legacy[0][0] == "panewslab"


def test_missing_db_fail_open(tmp_path):
    missing = str(tmp_path / "nope.db")
    with _switch(True):
        assert port_mod.fetch_all_rows_id_desc(missing) == []


def test_legacy_branch_raises_on_missing_db(tmp_path):
    """legacy 分支异常上抛（保持原语义：FAIL-OPEN 仅属 port 分支）。"""
    missing = str(tmp_path / "nope.db")
    with _switch(False):
        try:
            port_mod.fetch_all_rows_id_desc(missing)
        except Exception:
            return
    raise AssertionError("legacy 分支不得吞掉连接异常")


def test_legacy_is_default_when_switch_unset(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    _broken = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))  # noqa: E731
    # probe 通过 memory_l4 目录 sys.path 引用的是独立模块对象，两侧都要打桩
    monkeypatch.setattr(port_mod, "RecordsStorePort", _broken)
    monkeypatch.setattr(port_mod_flat, "RecordsStorePort", _broken)
    with _switch(False):
        assert len(port_mod.fetch_all_rows_id_desc(db)) == 3  # port 故障不影响 legacy
    with _switch(True):
        assert port_mod.fetch_all_rows_id_desc(db) == []  # port 故障 → FAIL-OPEN 空
