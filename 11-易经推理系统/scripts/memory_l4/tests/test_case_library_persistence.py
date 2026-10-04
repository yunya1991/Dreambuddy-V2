"""阶段1 RED 测试 — 案例库 JSON 持久化.

Spec: .trae/documents/strengthen-evolution-exploration.md 阶段1

修改 3 文件 (新增 save/load, 零回归):
  - washout_case_library.py          — WashoutCaseLibrary.save/load
  - washout_reversal_case_library.py — WashoutReversalCaseLibrary.save/load
  - pump_dump_reversal_case_library.py — PumpDumpReversalCaseLibrary.save/load

设计原则 (硬约束):
  - 持久化路径: 4-MEMORY/data/evolution_cases/{library_name}.json
  - __init__ 时自动 load (FAIL-OPEN: 文件不存在/损坏 → 空库)
  - add 后自动 save (FAIL-OPEN: 写入异常 → 仅日志, 不阻塞 add)
  - 环境变量 EVOLUTION_CASES_DIR 可覆盖默认路径
  - JSON 格式, dataclass asdict 序列化
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ============================================================
# sys.path 设置
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreamos.evolution.washout_case_library import WashoutCase, WashoutCaseLibrary
from dreamos.evolution.washout_reversal_case_library import WashoutReversalCaseLibrary
from dreamos.evolution.pump_dump_reversal_case_library import PumpDumpReversalCaseLibrary


def _make_case(case_id: str = "c1", label: str = "washout", pnl: float = 0.05) -> WashoutCase:
    """构造测试用案例."""
    return WashoutCase(
        case_id=case_id,
        coin="BTC",
        entry_time="2026-09-23T00:00:00Z",
        exit_time="2026-09-23T01:00:00Z",
        features_snapshot={"f1": 1.0, "f2": 2.0, "f3": 0.5},
        actual_label=label,
        pnl_pct=pnl,
        reward=WashoutCase.compute_reward(pnl),
        timestamp="2026-09-23T01:00:00Z",
    )


class TestWashoutCaseLibraryPersistence:
    """WashoutCaseLibrary JSON 持久化测试."""

    def test_save_and_load_roundtrip(self, tmp_path):
        """save 后 load, 案例应完全一致."""
        lib = WashoutCaseLibrary()
        lib.add(_make_case("c1", "washout", 0.05))
        lib.add(_make_case("c2", "weakness", -0.03))

        path = tmp_path / "washout.json"
        lib.save(str(path))

        lib2 = WashoutCaseLibrary()
        lib2.load(str(path))

        assert len(lib2) == 2
        c1 = lib2.get("c1")
        assert c1 is not None
        assert c1.coin == "BTC"
        assert c1.actual_label == "washout"
        assert c1.pnl_pct == 0.05
        c2 = lib2.get("c2")
        assert c2.actual_label == "weakness"
        assert c2.pnl_pct == -0.03

    def test_load_missing_file_returns_empty(self, tmp_path):
        """文件不存在 → load 不报错, 库为空."""
        path = tmp_path / "nonexistent.json"
        lib = WashoutCaseLibrary()
        lib.load(str(path))
        assert len(lib) == 0

    def test_load_corrupted_file_returns_empty(self, tmp_path):
        """文件损坏 → load FAIL-OPEN, 库为空."""
        path = tmp_path / "corrupt.json"
        path.write_text("{invalid json content", encoding="utf-8")
        lib = WashoutCaseLibrary()
        lib.load(str(path))
        assert len(lib) == 0

    def test_save_creates_parent_directory(self, tmp_path):
        """save 时父目录不存在 → 自动创建."""
        path = tmp_path / "subdir" / "nested" / "washout.json"
        lib = WashoutCaseLibrary()
        lib.add(_make_case())
        lib.save(str(path))
        assert path.exists()

    def test_add_auto_saves_when_path_set(self, tmp_path):
        """设置持久化路径后, add 自动触发 save."""
        path = tmp_path / "auto.json"
        lib = WashoutCaseLibrary(persist_path=str(path))
        lib.add(_make_case("c1"))

        # 文件应已生成
        assert path.exists()
        # 新实例 load 应能读到
        lib2 = WashoutCaseLibrary(persist_path=str(path))
        assert len(lib2) == 1

    def test_init_with_persist_path_auto_loads(self, tmp_path):
        """__init__(persist_path=...) → 自动 load 现有文件."""
        path = tmp_path / "init.json"
        lib = WashoutCaseLibrary()
        lib.add(_make_case("c1"))
        lib.add(_make_case("c2"))
        lib.save(str(path))

        lib2 = WashoutCaseLibrary(persist_path=str(path))
        assert len(lib2) == 2

    def test_duplicate_case_id_overwrites(self, tmp_path):
        """相同 case_id → 覆盖旧案例."""
        path = tmp_path / "dup.json"
        lib = WashoutCaseLibrary(persist_path=str(path))
        lib.add(_make_case("c1", "washout", 0.05))
        lib.add(_make_case("c1", "weakness", -0.03))  # 同 ID 覆盖

        assert len(lib) == 1
        c = lib.get("c1")
        assert c.actual_label == "weakness"

    def test_save_fail_open_on_permission_error(self, tmp_path):
        """save 写入异常 → 仅日志, 不抛错."""
        path = "/dev/null/cannot_write_here/washout.json"
        lib = WashoutCaseLibrary(persist_path=path)
        # add 不应抛错 (save FAIL-OPEN)
        lib.add(_make_case())
        assert len(lib) == 1


class TestWashoutReversalCaseLibraryPersistence:
    """WashoutReversalCaseLibrary 持久化测试."""

    def test_save_and_load_roundtrip(self, tmp_path):
        lib = WashoutReversalCaseLibrary()
        lib.add(_make_case("r1", "reversal_long_success", 0.08))
        lib.add(_make_case("r2", "reversal_long_fail", -0.04))

        path = tmp_path / "reversal.json"
        lib.save(str(path))

        lib2 = WashoutReversalCaseLibrary()
        lib2.load(str(path))
        assert len(lib2) == 2
        assert lib2.get("r1").actual_label == "reversal_long_success"

    def test_init_with_persist_path(self, tmp_path):
        path = tmp_path / "rev.json"
        lib = WashoutReversalCaseLibrary(persist_path=str(path))
        lib.add(_make_case("r1"))
        assert path.exists()

        lib2 = WashoutReversalCaseLibrary(persist_path=str(path))
        assert len(lib2) == 1


class TestPumpDumpReversalCaseLibraryPersistence:
    """PumpDumpReversalCaseLibrary 持久化测试."""

    def test_save_and_load_roundtrip(self, tmp_path):
        lib = PumpDumpReversalCaseLibrary()
        lib.add(_make_case("p1", "reversal_short_success", 0.06))
        lib.add(_make_case("p2", "reversal_short_fail", -0.05))

        path = tmp_path / "pump_dump.json"
        lib.save(str(path))

        lib2 = PumpDumpReversalCaseLibrary()
        lib2.load(str(path))
        assert len(lib2) == 2
        assert lib2.get("p1").actual_label == "reversal_short_success"

    def test_init_with_persist_path(self, tmp_path):
        path = tmp_path / "pd.json"
        lib = PumpDumpReversalCaseLibrary(persist_path=str(path))
        lib.add(_make_case("p1"))
        assert path.exists()

        lib2 = PumpDumpReversalCaseLibrary(persist_path=str(path))
        assert len(lib2) == 1


class TestEnvironmentVariableCasesDir:
    """EVOLUTION_CASES_DIR 环境变量测试."""

    def test_env_var_overrides_default_path(self, tmp_path, monkeypatch):
        """EVOLUTION_CASES_DIR → 覆盖默认路径."""
        custom_dir = str(tmp_path / "custom_cases")
        monkeypatch.setenv("EVOLUTION_CASES_DIR", custom_dir)

        lib = WashoutCaseLibrary(use_env_path=True, library_name="test_env")
        lib.add(_make_case("e1"))

        expected = Path(custom_dir) / "test_env.json"
        assert expected.exists()

    def test_env_var_not_set_uses_default(self, monkeypatch):
        """EVOLUTION_CASES_DIR 未设置 → 使用默认 4-MEMORY/data/evolution_cases/."""
        monkeypatch.delenv("EVOLUTION_CASES_DIR", raising=False)
        lib = WashoutCaseLibrary(use_env_path=True, library_name="test_default")
        # 默认路径应指向 4-MEMORY/data/evolution_cases/
        assert "evolution_cases" in lib.persist_path
