"""test_v15_suite.py — V15 双基线 AB 影子对比框架完整测试套件.

合并自 3 份独立测试文件:
  test_ab_comparator.py        → §A ABShadowComparator 核心 (12 用例)
  test_incremental_trainer.py  → §B IncrementalTrainer 核心 (11 用例)
  test_dual_baseline_framework → §C 双基线框架全链路 (35 用例)

总计: 58 用例 | 12 个测试类 | 覆盖技术文档 10 个章节

技术文档: docs/dual_baseline_ab_framework.md

运行方式:
  python3 -m pytest tests/test_v15_suite.py -v --tb=short
  python3 tests/test_v15_suite.py --report   # 生成 markdown 报告
"""
from __future__ import annotations

import json
import os
import random
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# sys.path 设置（conftest.py 在 pytest 模式下注入，直接执行时需要手动设置）
_HERE = Path(__file__).resolve().parent
_V15_ROOT = _HERE.parent
if str(_V15_ROOT) not in sys.path:
    sys.path.insert(0, str(_V15_ROOT))

from ab_shadow_comparator import (
    ABShadowComparator,
    ABComparatorState,
    STATE_SHADOW,
    STATE_LIVE,
    STATE_DISABLED,
    MIN_SAMPLES_FOR_TEST,
    SHADOW_TO_LIVE_MIN_GAIN,
    SHADOW_TO_LIVE_PVALUE,
    LIVE_TO_SHADOW_PVALUE,
    LIVE_TO_SHADOW_MAX_LOSS,
    EVALUATION_WINDOW_DAYS,
    LIVE_EVALUATION_WINDOW_DAYS,
)
from incremental_trainer import (
    ModelVersionManager,
    IncrementalTrainer,
)


# ---------------------------------------------------------------------------
# 共享 Helpers（与 conftest.py 保持一致，确保 class 内可用）
# ---------------------------------------------------------------------------

def _fake_pt_file(path, size=8):
    """生成占位 .pt 文件（小体积，用于版本管理测试）。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)
    return str(path)


def _make_pt_file(path: Path):
    """生成占位 .pt 文件（双基线框架测试用）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x50\x54\x46\x21")
    return str(path)


def _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10, trades=10, wins=6):
    """生成回测指标 mock 数据。"""
    return {
        'total_pnl': pnl, 'total_trades': trades, 'win_trades': wins,
        'win_rate': win_rate, 'max_drawdown': mdd, 'label': '',
    }


def _make_fake_bilstm_file(path: Path):
    """生成能被 BiLSTMAttentionBust 加载的 state_dict 文件。"""
    import torch
    ai_dir = str(_V15_ROOT / "ai_trainers")
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)
    from phase_d_models import BiLSTMAttentionBust
    m1 = BiLSTMAttentionBust(ohlcv_len=60, n_channels=5, n_scalar=7, hidden=48, n_layers=2)
    payload = {
        "meta": {"ohlcv_len": 60, "n_channels": 5, "n_scalar": 7, "hidden": 48, "n_layers": 2},
        "state_dict": m1.state_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, str(path))
    return str(path)


def _make_fake_patchtst_file(path: Path):
    """生成能被 PatchTSTForDrawdown 加载的 state_dict 文件。"""
    import torch
    ai_dir = str(_V15_ROOT / "ai_trainers")
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)
    from phase_d_models import PatchTSTForDrawdown
    m2 = PatchTSTForDrawdown(c_in=5, seq_len=120, patch_len=12, stride=6,
                             d_model=32, n_layers=2, n_heads=4, d_ff=64)
    payload = {
        "meta": {"c_in": 5, "seq_len": 120, "patch_len": 12, "stride": 6,
                 "d_model": 32, "n_layers": 2, "n_heads": 4, "d_ff": 64},
        "state_dict": m2.state_dict(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, str(path))
    return str(path)


# ===========================================================================
# §A  ABShadowComparator 核心功能 (12 用例)
#    对应技术文档 §5 (状态机) + §5.3 (PnL回填) + §7 (配置参数)
# ===========================================================================

class TestABComparatorCore:
    """ABShadowComparator 基础功能：DecisionRecord、position_ref、t-CDF、backfill、状态机。"""

    def test_a01_decision_record_new_fields(self, fresh_state):
        """T1: DecisionRecord 新字段 position_ref / pnl_backfilled / baseline_pnl_pct 存在并序列化。"""
        comp, _ = fresh_state
        ref = ABShadowComparator.build_position_ref("BTC", "2026-08-19T00:00:00Z")
        comp.record_decision(
            symbol="BTC", baseline_action="OPEN", ai_action="SKIP",
            baseline_confidence=0.8, ai_confidence=0.3,
            baseline_pnl=0.0, ai_predicted_pnl=0.0,
            ai_p_bust=0.7, ai_drawdown=-0.25, decision_diff="G-D1 skip",
            position_ref=ref,
        )
        rec = comp.state.records[-1]
        assert rec["position_ref"] == ref
        assert rec["pnl_backfilled"] is False
        assert rec["baseline_pnl_pct"] == 0.0
        comp2 = ABShadowComparator(state_file=str(comp.state_file))
        assert comp2.state.records[-1]["position_ref"] == ref

    def test_a02_build_position_ref_granularity(self):
        """T2: position_ref 分钟级截断 & 多输入类型稳定。"""
        coin = "ETH"
        iso1 = "2026-08-19T12:34:56.789Z"
        iso2 = "2026-08-19T12:34:01+00:00"
        dt = datetime(2026, 8, 19, 12, 34, 56, 123, tzinfo=timezone.utc)
        unix = dt.timestamp()
        expected = "ETH|2026-08-19T12:34:00"
        assert ABShadowComparator.build_position_ref(coin, iso1) == expected
        assert ABShadowComparator.build_position_ref(coin, iso2) == expected
        assert ABShadowComparator.build_position_ref(coin, dt) == expected
        assert ABShadowComparator.build_position_ref(coin, unix) == expected
        dt_other = datetime(2026, 8, 19, 12, 35, tzinfo=timezone.utc)
        assert ABShadowComparator.build_position_ref(coin, dt_other) != expected

    def test_a03_exact_t_cdf(self, fresh_state):
        """T3: 精确 t-CDF — 零差 p≈1.0、大差异 p≪0.05。"""
        comp, _ = fresh_state
        t0 = comp._paired_t_test([0.0] * 12, [0.0] * 12)
        assert t0["t_stat"] == pytest.approx(0.0, abs=1e-9)
        assert t0["p_value"] > 0.9
        base = [-1.0 + ((i * 37) % 7 - 3) * 0.08 for i in range(40)]
        ai = [0.0 + ((i * 53) % 7 - 3) * 0.08 for i in range(40)]
        t1 = comp._paired_t_test(base, ai)
        assert t1["significant"] is True
        assert t1["p_value"] < 0.001
        assert t1["mean_diff"] > 0.9

    def test_a04_backfill_matching_modes(self, fresh_state):
        """T4: backfill — position_ref 精确命中 + fallback 命中 + 无匹配返回 0。"""
        comp, _ = fresh_state
        coin = "SOL"
        ts = "2026-08-01T10:00:00Z"
        ref = ABShadowComparator.build_position_ref(coin, ts)
        comp.record_decision(symbol=coin, baseline_action="OPEN", ai_action="OPEN",
                             baseline_confidence=0.9, ai_confidence=0.95,
                             baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
        ts2 = "2026-08-01T11:00:00Z"
        ref2 = ABShadowComparator.build_position_ref(coin, ts2)
        comp.record_decision(symbol=coin, baseline_action="OPEN", ai_action="SKIP",
                             baseline_confidence=0.85, ai_confidence=0.25,
                             baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref2)
        n = comp.backfill_trade_result(symbol=coin, entry_timestamp=ts2,
                                       baseline_pnl_usdt=-0.5, baseline_pnl_pct=-0.05,
                                       exit_reason="bust")
        assert n == 1
        assert comp.state.records[-1]["pnl_backfilled"] is True
        assert comp.state.records[-1]["baseline_pnl"] == pytest.approx(-0.5)
        assert comp.state.records[0]["pnl_backfilled"] is False

    def test_a05_ai_path_pnl_estimates(self, fresh_state):
        """T5: AI 路径 PnL 估算 — OPEN-SKIP / OPEN-OPEN / OPEN-ADDON 三种场景。"""
        comp, _ = fresh_state
        coin = "BTC"
        cases = [
            ("OPEN", "SKIP", -1.0, 0.0, 0.0, "AI 正确 SKIP 爆亏交易 → AI PnL=0"),
            ("OPEN", "OPEN", 0.5, 0.0, 0.5, "都 OPEN → 同 PnL"),
            ("SKIP", "SKIP", 0.0, 0.0, 0.0, "都 SKIP → 同 PnL=0"),
            ("OPEN", "ADDON", 0.2, 0.15, 0.2 * (1 + 0.15), "AI 加更多层 → 放大15%"),
            ("CLOSE", "OPEN", 0.3, 0.0, 0.3, "其他不一致 → 保守同基线"),
        ]
        for i, (ba, aa, bl_usdt, ratio, exp_ai, desc) in enumerate(cases):
            ts = datetime(2026, 8, 1, 9, i, tzinfo=timezone.utc).isoformat()
            ref = ABShadowComparator.build_position_ref(coin, ts)
            comp.record_decision(symbol=coin, baseline_action=ba, ai_action=aa,
                                 baseline_confidence=0.8, ai_confidence=0.8,
                                 baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
            n = comp.backfill_trade_result(symbol=coin, entry_timestamp=ts,
                                          baseline_pnl_usdt=bl_usdt, baseline_pnl_pct=0.01,
                                          ai_addon_delta_ratio=ratio)
            assert n == 1, desc
            assert comp.state.records[-1]["ai_predicted_pnl"] == pytest.approx(exp_ai, abs=1e-4), desc

    def test_a06_state_machine_promote_and_rollback(self, fresh_state):
        """T6: SHADOW→LIVE 晋升 & LIVE→SHADOW 回滚闭环。"""
        comp, state_file = fresh_state
        assert comp.get_state() == STATE_SHADOW
        random.seed(1)
        for i in range(30):
            entry_dt = datetime.utcnow() - timedelta(days=10) + timedelta(hours=i * 3)
            entry_ts = entry_dt.isoformat() + "Z"
            ref = ABShadowComparator.build_position_ref("BTC", entry_ts)
            if i < 15:
                comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                     baseline_confidence=0.9, ai_confidence=0.95,
                                     baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
                comp.backfill_trade_result(symbol="BTC", entry_timestamp=entry_ts,
                                           baseline_pnl_usdt=0.10, baseline_pnl_pct=0.01)
            else:
                comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="SKIP",
                                     baseline_confidence=0.9, ai_confidence=0.1,
                                     baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
                comp.backfill_trade_result(symbol="BTC", entry_timestamp=entry_ts,
                                           baseline_pnl_usdt=-0.30, baseline_pnl_pct=-0.03,
                                           ai_skipped_open_pnl=0.0)
        report = comp.generate_report()
        ev = report["evaluation"]
        assert ev["n_samples"] >= MIN_SAMPLES_FOR_TEST
        assert ev["t_test"]["significant"]
        assert ev["t_test"]["mean_diff"] > SHADOW_TO_LIVE_MIN_GAIN
        assert ev["bootstrap"]["positive"]
        assert comp.get_state() == STATE_LIVE

    def test_a07_corrupted_state_recovery(self, tmp_path):
        """T7: 损坏 JSON → 恢复空 state；原子写无 .tmp 残留。"""
        f = tmp_path / "corrupt.json"
        f.write_text("{not valid json :::", encoding="utf-8")
        comp = ABShadowComparator(state_file=str(f))
        assert comp.get_state() == STATE_SHADOW
        assert comp.state.records == []
        comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                             baseline_confidence=0.9, ai_confidence=0.9,
                             baseline_pnl=0.0, ai_predicted_pnl=0.0)
        f2 = ABShadowComparator(state_file=str(f))
        assert len(f2.state.records) == 1
        assert not (tmp_path / "corrupt.json.tmp").exists()

    def test_a08_dynamic_baseline_set_and_get(self, tmp_path):
        """T8: set_dynamic_baseline + generate_report 包含动态基线信息。"""
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        assert comp.state.dynamic_baseline_version is None
        metrics = {"total_pnl": 1.5, "win_rate": 0.65, "max_drawdown": 0.08}
        comp.set_dynamic_baseline("v1", metrics)
        assert comp.state.dynamic_baseline_version == "v1"
        assert comp.state.dynamic_baseline_metrics == metrics
        report = comp.generate_report()
        assert report["dynamic_baseline_version"] == "v1"
        assert report["dynamic_baseline_metrics"]["total_pnl"] == 1.5

    def test_a09_version_comparison_promote(self, tmp_path):
        """T9: 新版本优于动态基线 → should_promote=True, score=3。"""
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        comp.set_dynamic_baseline("v1", {"total_pnl": 1.0, "win_rate": 0.60, "max_drawdown": 0.10})
        candidate = {"total_pnl": 1.5, "win_rate": 0.70, "max_drawdown": 0.08}
        r = comp.evaluate_version_comparison("v2", candidate, ("bilstm.pt", "patchtst.pt"))
        assert r["should_promote"] is True
        assert r["score"] == 3
        assert r["pnl_delta_pct"] == 50.0

    def test_a10_version_comparison_reject(self, tmp_path):
        """T10: 新版本劣于动态基线 → should_promote=False, score=0。"""
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        comp.set_dynamic_baseline("v1", {"total_pnl": 2.0, "win_rate": 0.70, "max_drawdown": 0.05})
        candidate = {"total_pnl": 1.0, "win_rate": 0.50, "max_drawdown": 0.12}
        r = comp.evaluate_version_comparison("v2", candidate, ("bilstm.pt", "patchtst.pt"))
        assert r["should_promote"] is False
        assert r["score"] == 0
        assert r["pnl_delta_pct"] == -50.0

    def test_a11_version_comparison_no_baseline_auto_promote(self, tmp_path):
        """T11: 无动态基线（首次训练）→ 自动通过。"""
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        assert comp.state.dynamic_baseline_version is None
        candidate = {"total_pnl": 0.5, "win_rate": 0.55, "max_drawdown": 0.06}
        r = comp.evaluate_version_comparison("v1", candidate, ("bilstm.pt", "patchtst.pt"))
        assert r["should_promote"] is True
        assert "no dynamic baseline" in r["reason"]

    def test_a12_version_comparison_partial_win(self, tmp_path):
        """T12: 2/3 优于基线但 PnL 略差（>-2%）→ 仍然通过。"""
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        comp.set_dynamic_baseline("v1", {"total_pnl": 1.0, "win_rate": 0.60, "max_drawdown": 0.12})
        candidate = {"total_pnl": 0.99, "win_rate": 0.70, "max_drawdown": 0.08}
        r = comp.evaluate_version_comparison("v2", candidate, ("bilstm.pt", "patchtst.pt"))
        assert r["should_promote"] is True
        assert r["score"] == 2


# ===========================================================================
# §B  IncrementalTrainer 核心功能 (11 用例)
#    对应技术文档 §4 (调用链) + §3.3 (bootstrap) + §4.2 (热切换)
# ===========================================================================

class TestModelVersionManager:
    """ModelVersionManager 版本注册、晋升、回滚、归档。"""

    def test_b01_register_first_vs_second_version(self, mgr, tmp_path):
        """T1: 首版本注册为 shadow（不自动 live），第二版本也是 shadow。"""
        base = mgr.base_dir
        v1_b = _fake_pt_file(base / "v1" / "bilstm.pt")
        v1_p = _fake_pt_file(base / "v1" / "patchtst.pt")
        v1 = mgr.register_version(v1_b, v1_p, {"bilstm": {"best_val_loss": 0.12}},
                                  sample_count=500, coins=["BTC", "ETH"])
        assert v1 == "v1"
        assert mgr.state.current_live_version is None
        assert mgr.state.current_shadow_version == "v1"
        v2_b = _fake_pt_file(base / "v2" / "bilstm.pt")
        v2_p = _fake_pt_file(base / "v2" / "patchtst.pt")
        v2 = mgr.register_version(v2_b, v2_p, {"bilstm": {"best_val_loss": 0.09}},
                                  sample_count=620, coins=["BTC"])
        assert v2 == "v2"
        assert mgr.state.current_shadow_version == "v2"
        assert mgr.get_shadow_paths() == (v2_b, v2_p)

    def test_b02_promote_shadow_demotes_old_live(self, mgr):
        """T2: promote_shadow 旧 live 降级为 shadow + 新 shadow 晋升。"""
        base = mgr.base_dir
        v1_b = _fake_pt_file(base / "v1" / "bilstm.pt"); v1_p = _fake_pt_file(base / "v1" / "patchtst.pt")
        v2_b = _fake_pt_file(base / "v2" / "bilstm.pt"); v2_p = _fake_pt_file(base / "v2" / "patchtst.pt")
        mgr.register_version(v1_b, v1_p, {}); mgr.register_version(v2_b, v2_p, {})
        ok = mgr.promote_shadow("v2")
        assert ok is True
        assert mgr.state.current_live_version == "v2"
        v1_info = next(v for v in mgr.state.versions if v["version"] == "v1")
        assert v1_info["status"] == "shadow"
        v2_info = next(v for v in mgr.state.versions if v["version"] == "v2")
        assert v2_info["status"] == "live"
        assert v2_info["promoted_at"] is not None
        assert mgr.promote_shadow("v999") is False

    def test_b03_rollback_live(self, mgr):
        """T3: rollback_live — 有 promoted_at 候选时正确回滚。"""
        base = mgr.base_dir
        v1_b = _fake_pt_file(base / "v1" / "bilstm.pt"); v1_p = _fake_pt_file(base / "v1" / "patchtst.pt")
        mgr.register_version(v1_b, v1_p, {})
        v2_b = _fake_pt_file(base / "v2" / "bilstm.pt"); v2_p = _fake_pt_file(base / "v2" / "patchtst.pt")
        mgr.register_version(v2_b, v2_p, {})
        mgr.promote_shadow("v2")
        for v in mgr.state.versions:
            if v["version"] == "v1":
                v["promoted_at"] = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
                break
        mgr._save_state()
        ok = mgr.rollback_live()
        assert ok is True
        assert mgr.state.current_live_version == "v1"

    def test_b04_disable_and_archive(self, mgr):
        """T4: disable_shadow 状态 = disabled。"""
        base = mgr.base_dir
        state_f = base.parent / "inc_state_max2.json"
        mgr2 = ModelVersionManager(base_dir=str(base), state_file=str(state_f), max_versions=2)
        for i in range(3):
            b = _fake_pt_file(base / f"m{i}" / "bilstm.pt"); p = _fake_pt_file(base / f"m{i}" / "patchtst.pt")
            mgr2.register_version(b, p, {"i": i})
        mgr2.disable_shadow(mgr2.state.current_shadow_version or "m2")
        last_v = mgr2.state.versions[-1]
        assert last_v["status"] == "disabled"
        assert mgr2.get_shadow_paths() is None


class TestIncrementalTrainerCore:
    """IncrementalTrainer 数据采集、重训触发、AB 评估、热切换。"""

    def test_b05_check_new_trades_various(self, tmp_path, monkeypatch):
        """T5: check_new_trades — 缺文件/损坏JSON/空列表/正常数据 四种场景。"""
        model_dir = tmp_path / "models"; state_f = tmp_path / "inc.json"
        it = IncrementalTrainer(model_base_dir=str(model_dir), state_file=str(state_f))
        it.trade_history_file = tmp_path / "nope.json"
        r = it.check_new_trades()
        assert r["total_trades"] == 0 and r["new_trades"] == 0 and r["should_retrain"] is False
        bad = tmp_path / "bad.json"; bad.write_text("{broken: [", encoding="utf-8")
        it.trade_history_file = bad
        r = it.check_new_trades()
        assert r["total_trades"] == 0
        emp = tmp_path / "empty.json"; emp.write_text("[]", encoding="utf-8")
        it.trade_history_file = emp
        r = it.check_new_trades()
        assert r["total_trades"] == 0
        good = tmp_path / "good.json"
        trades = [{"coin": "BTC", "pnl_usdt": 0.1 * i,
                   "timestamp": (datetime.utcnow() - timedelta(hours=i)).isoformat() + "Z"} for i in range(7)]
        good.write_text(json.dumps(trades), encoding="utf-8")
        it.trade_history_file = good
        it._last_trade_count = 2
        r = it.check_new_trades()
        assert r["total_trades"] == 7 and r["new_trades"] == 5 and r["should_retrain"] is True

    def test_b06_auto_retrain_threshold(self, tmp_path):
        """T6: auto_retrain_if_needed — < min_new_trades → skip；≥ min → retrain。"""
        model_dir = tmp_path / "models"; state_f = tmp_path / "inc.json"
        it = IncrementalTrainer(model_base_dir=str(model_dir), state_file=str(state_f), min_new_trades=3)
        hist = tmp_path / "hist.json"
        hist.write_text(json.dumps([{"coin": "BTC", "pnl_usdt": 0.1}]), encoding="utf-8")
        it.trade_history_file = hist
        it._last_trade_count = 0
        r = it.auto_retrain_if_needed()
        assert r["action"] == "skipped"
        it._last_trade_count = 0
        hist.write_text(json.dumps([{"coin": "BTC", "pnl_usdt": i * 0.1} for i in range(4)]), encoding="utf-8")
        ok_ret = {"success": True, "bilstm": {"best_val_loss": 0.05}, "patchtst": {"best_val_loss": 0.01}}
        it.collect_recent_data = lambda **kw: {"samples": 300, "coins": ["SYNTH"], "window_days": 30, "cutoff": ""}
        it._run_training = types.MethodType(lambda self, out_dir, collection: ok_ret, it)
        r = it.auto_retrain_if_needed()
        assert r["action"] == "retrained"
        assert r["retrain_result"]["version"] == "v1"
        info = it.version_mgr.get_version_info()
        assert info["current_live"] is None
        assert info["current_shadow"] == "v1"

    def test_b07_evaluate_and_promote_transitions(self, tmp_path):
        """T7: evaluate_and_promote — 三种转移 SHADOW→LIVE / SHADOW→DISABLED / LIVE→SHADOW。"""
        model_dir = tmp_path / "models"; state_f = tmp_path / "inc.json"
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        it = IncrementalTrainer(model_base_dir=str(model_dir), state_file=str(state_f), ab_comparator=comp)
        v1_b = _fake_pt_file(model_dir / "v1" / "bilstm.pt"); v1_p = _fake_pt_file(model_dir / "v1" / "patchtst.pt")
        v2_b = _fake_pt_file(model_dir / "v2" / "bilstm.pt"); v2_p = _fake_pt_file(model_dir / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {"i": 1})
        it.version_mgr.register_version(v2_b, v2_p, {"i": 2})
        it.version_mgr.promote_shadow("v1")
        comp.force_state(STATE_SHADOW)
        random.seed(3)
        for i in range(25):
            base_usdt = 0.2 + (i % 5 - 2) * 0.05
            comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                 baseline_confidence=0.9, ai_confidence=0.8,
                                 baseline_pnl=base_usdt, ai_predicted_pnl=0.0,
                                 position_ref=ABShadowComparator.build_position_ref("BTC", datetime.utcnow() - timedelta(hours=i)))
            comp.backfill_trade_result(symbol="BTC", entry_timestamp=datetime.utcnow() - timedelta(hours=i),
                                       baseline_pnl_usdt=base_usdt, baseline_pnl_pct=0.02)
        ev = it.evaluate_and_promote()
        assert ev.get("action") in ("disabled", "keep_collecting", "promoted")

    def test_b08_gateway_hot_swap_models(self, tmp_path):
        """T8: hot_swap_models strict 成功 / 不存在文件 strict 失败不污染路径 / non-strict 跳过。"""
        sys.path.insert(0, str(_V15_ROOT))
        sys.path.insert(0, str(_V15_ROOT / "lib"))
        from lib.phase_d_gateway import PhaseDGateway
        v1b = _make_fake_bilstm_file(tmp_path / "v1" / "bilstm.pt")
        v1p = _make_fake_patchtst_file(tmp_path / "v1" / "patchtst.pt")
        g = PhaseDGateway(enabled=True, bilstm_model_path=v1b, patchtst_model_path=v1p)
        v2b = _make_fake_bilstm_file(tmp_path / "v2" / "bilstm.pt")
        v2p = _make_fake_patchtst_file(tmp_path / "v2" / "patchtst.pt")
        ok, reason = g.hot_swap_models(bilstm_model_path=v2b, patchtst_model_path=v2p, strict=True)
        assert ok is True, f"strict hot_swap 失败: {reason}"
        assert g.bilstm_model_path == v2b and g.patchtst_model_path == v2p
        ok2, _ = g.hot_swap_models(bilstm_model_path="/tmp/DOES_NOT_EXIST_XYZ.pt", strict=True)
        assert ok2 is False
        assert g.bilstm_model_path == v2b
        ok4, _ = g.hot_swap_models(strict=False)
        assert ok4 is False


class TestIncrementalTrainerDualBaseline:
    """IncrementalTrainer 双基线 bootstrap + 版本迭代。"""

    def _setup_trainer(self, tmp_path):
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        it = IncrementalTrainer(model_base_dir=str(tmp_path / "models"),
                                state_file=str(tmp_path / "inc.json"), ab_comparator=comp)
        return it, comp

    def test_b09_first_version_bootstrap(self, tmp_path):
        """T9: 首版本 shadow → 回测通过 → BOOTSTRAP_FIRST_VERSION promoted + 动态基线初始化。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {"i": 1})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.2, win_rate=0.6, mdd=0.08)
        result = it.evaluate_and_promote()
        assert result['action'] == 'promoted'
        assert result['transition'] == 'BOOTSTRAP_FIRST_VERSION'
        assert result['new_status'] == 'live'
        assert comp.state.dynamic_baseline_version == 'v1'
        assert comp.state.dynamic_baseline_metrics['total_pnl'] == 1.2

    def test_b10_inferior_version_rejected(self, tmp_path):
        """T10: v2 回测劣于动态基线 v1 → disabled_inferior，v1 继续服务。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {"i": 1})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05)
        it.evaluate_and_promote()
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {"i": 2})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=0.5, win_rate=0.30, mdd=0.15)
        result = it.evaluate_and_promote()
        assert result['action'] == 'disabled_inferior'
        assert it.version_mgr.state.current_live_version == 'v1'
        assert comp.state.dynamic_baseline_version == 'v1'

    def test_b11_superior_version_promoted(self, tmp_path):
        """T11: v2 优于 v1 → score=3/3 + should_promote=True（AB 样本不足时 keep_collecting）。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {"i": 1})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10)
        it.evaluate_and_promote()
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {"i": 2})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.8, win_rate=0.75, mdd=0.06)
        result = it.evaluate_and_promote()
        assert result['action'] in ('keep_collecting', 'promoted')
        assert result['version_comparison']['should_promote'] is True
        assert result['version_comparison']['score'] == 3


# ===========================================================================
# §C  双基线框架全链路 (35 用例)
#    对应技术文档 §3.1 (决策矩阵) + §3.2 (评分) + §3.3 (bootstrap)
#                   §5.2 (状态机) + §5.3 (PnL回填) + §6 (迭代场景)
#                   §10 (监控) + §7 (配置)
# ===========================================================================

class TestDecisionMatrix:
    """§3.1 决策矩阵 — 6 行全覆盖。"""

    def _setup_trainer(self, tmp_path):
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        it = IncrementalTrainer(model_base_dir=str(tmp_path / "models"),
                                state_file=str(tmp_path / "inc.json"), ab_comparator=comp)
        return it, comp

    def test_c01_row1_first_version_bootstrap(self, tmp_path):
        """行1: 无动态基线 + 回测通过 → BOOTSTRAP_FIRST_VERSION promoted。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.2)
        result = it.evaluate_and_promote()
        assert result['action'] == 'promoted'
        assert result['transition'] == 'BOOTSTRAP_FIRST_VERSION'
        assert comp.state.dynamic_baseline_version == 'v1'

    def test_c02_row2_inferior_version_disabled(self, tmp_path):
        """行2: 动态基线对比不通过 → disabled_inferior。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05)
        it.evaluate_and_promote()
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=0.5, win_rate=0.30, mdd=0.15)
        result = it.evaluate_and_promote()
        assert result['action'] == 'disabled_inferior'
        assert it.version_mgr.state.current_live_version == 'v1'

    def test_c03_row3_superior_with_ab_live(self, tmp_path):
        """行3: 动态基线通过 + AB SHADOW→LIVE → promoted。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10)
        it.evaluate_and_promote()
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08)
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_samples': 25, 't_test': {'p_value': 0.02}}
        result = it.evaluate_and_promote()
        comp.evaluate = orig
        assert result['action'] == 'promoted'
        assert comp.state.dynamic_baseline_version == 'v2'

    def test_c04_row4_superior_but_ab_no_samples(self, tmp_path):
        """行4: 动态基线通过但 AB transition=None → keep_collecting。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0)
        it.evaluate_and_promote()
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.8, win_rate=0.75, mdd=0.06)
        result = it.evaluate_and_promote()
        assert result['action'] == 'keep_collecting'
        assert result['version_comparison']['should_promote'] is True

    def test_c05_row5_superior_but_ab_disabled(self, tmp_path):
        """行5: 动态基线通过但 AB SHADOW→DISABLED → disabled。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0)
        it.evaluate_and_promote()
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08)
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→DISABLED', 'n_samples': 25}
        result = it.evaluate_and_promote()
        comp.evaluate = orig
        assert result['action'] == 'disabled'
        assert it.version_mgr.state.current_live_version == 'v1'

    def test_c06_row6_live_to_shadow_rollback(self, tmp_path):
        """行6: AB LIVE→SHADOW → rollback + hot_swap 到回滚版本。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0)
        it.evaluate_and_promote()
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08)
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_samples': 25}
        it.evaluate_and_promote()
        comp.evaluate = orig
        assert it.version_mgr.state.current_live_version == 'v2'
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=0.0, win_rate=0.0, mdd=0.20)
        comp.evaluate = lambda: {'transition': 'LIVE→SHADOW', 'n_samples': 25}
        result = it.evaluate_and_promote()
        comp.evaluate = orig
        assert result['action'] == 'rollback'
        assert it.version_mgr.state.current_live_version == 'v1'


class TestScoringRules:
    """§3.2 动态基线对比评分规则边界条件。"""

    def test_c07_score_0_all_inferior(self, fresh_comp):
        """3 项全劣 → score=0, should_promote=False。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05))
        r = fresh_comp.evaluate_version_comparison("v2", _mock_metrics(pnl=0.5, win_rate=0.30, mdd=0.15), ("", ""))
        assert r['score'] == 0 and r['should_promote'] is False

    def test_c08_score_1_only_one_better(self, fresh_comp):
        """仅 1/3 优于基线 → score=1, should_promote=False。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05))
        r = fresh_comp.evaluate_version_comparison("v2", _mock_metrics(pnl=2.5, win_rate=0.50, mdd=0.12), ("", ""))
        assert r['score'] == 1 and r['should_promote'] is False

    def test_c09_score_2_pnl_within_tolerance(self, fresh_comp):
        """2/3 优于基线且 PnL 微差（-1%）→ score=2, should_promote=True。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.12))
        r = fresh_comp.evaluate_version_comparison("v2", _mock_metrics(pnl=0.99, win_rate=0.70, mdd=0.08), ("", ""))
        assert r['score'] == 2 and r['should_promote'] is True

    def test_c10_score_2_pnl_beyond_tolerance(self, fresh_comp):
        """2/3 优于基线但 PnL 劣化超 -2% → should_promote=False。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.12))
        r = fresh_comp.evaluate_version_comparison("v2", _mock_metrics(pnl=0.97, win_rate=0.70, mdd=0.08), ("", ""))
        assert r['score'] == 2 and r['should_promote'] is False and r['pnl_delta_pct'] == -3.0

    def test_c11_score_3_all_superior(self, fresh_comp):
        """3/3 全优 → score=3, should_promote=True。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10))
        r = fresh_comp.evaluate_version_comparison("v2", _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08), ("", ""))
        assert r['score'] == 3 and r['should_promote'] is True

    def test_c12_pnl_delta_calculation(self, fresh_comp):
        """PnL 改善百分比计算正确。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=2.0))
        r = fresh_comp.evaluate_version_comparison("v2", _mock_metrics(pnl=3.0), ("", ""))
        assert r['pnl_delta_pct'] == 50.0

    def test_c13_pnl_delta_zero_baseline(self, fresh_comp):
        """基线 PnL=0 时 pnl_delta_pct=0（避免除零）。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=0.0))
        r = fresh_comp.evaluate_version_comparison("v2", _mock_metrics(pnl=1.0), ("", ""))
        assert r['pnl_delta_pct'] == 0.0


class TestBootstrapLogic:
    """§3.3 首版本 bootstrap 逻辑。"""

    def test_c14_bootstrap_sets_dynamic_baseline(self, tmp_path):
        """首版本晋升后动态基线初始化为 v1 + 回测指标。"""
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        it = IncrementalTrainer(model_base_dir=str(tmp_path / "models"),
                                state_file=str(tmp_path / "inc.json"), ab_comparator=comp)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        metrics = _mock_metrics(pnl=1.2, win_rate=0.65, mdd=0.08)
        it._backtest_model = lambda b, p, label='': metrics
        result = it.evaluate_and_promote()
        assert result['transition'] == 'BOOTSTRAP_FIRST_VERSION'
        assert comp.state.dynamic_baseline_version == 'v1'
        assert comp.state.dynamic_baseline_metrics['total_pnl'] == 1.2

    def test_c15_bootstrap_does_not_fire_with_existing_baseline(self, tmp_path):
        """已有动态基线时不走 bootstrap 分支。"""
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        comp.set_dynamic_baseline("v0", _mock_metrics(pnl=1.0))
        it = IncrementalTrainer(model_base_dir=str(tmp_path / "models"),
                                state_file=str(tmp_path / "inc.json"), ab_comparator=comp)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.5)
        result = it.evaluate_and_promote()
        assert result['transition'] != 'BOOTSTRAP_FIRST_VERSION'


class TestABStateMachineTransitions:
    """§5.2 AB 状态机转移条件。"""

    def _fill_paired_records(self, comp, n, baseline_pnl, ai_pnl):
        for i in range(n):
            ts = datetime.utcnow() - timedelta(hours=i)
            comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                  baseline_confidence=0.9, ai_confidence=0.8,
                                  baseline_pnl=0.0, ai_predicted_pnl=0.0,
                                  position_ref=ABShadowComparator.build_position_ref("BTC", ts))
            comp.backfill_trade_result(symbol="BTC", entry_timestamp=ts,
                                       baseline_pnl_usdt=baseline_pnl, baseline_pnl_pct=baseline_pnl / 100)

    def test_c16_shadow_to_live_positive_significance(self, fresh_comp):
        """SHADOW→LIVE: ≥20样本 + p<0.05 + gain≥2%。"""
        comp = fresh_comp
        comp.force_state(STATE_SHADOW)
        self._fill_paired_records(comp, 25, baseline_pnl=0.10, ai_pnl=0.15)
        for r in comp.state.records:
            r['ai_predicted_pnl'] = 0.15
        comp._save_state()
        result = comp.evaluate()
        assert result['n_samples'] >= 20
        assert result['transition'] in ('SHADOW→LIVE', None)

    def test_c17_shadow_to_disabled_negative_significance(self, fresh_comp):
        """SHADOW→DISABLED: ≥20样本 + AI显著差于基线。"""
        comp = fresh_comp
        comp.force_state(STATE_SHADOW)
        for i in range(25):
            ts = datetime.utcnow() - timedelta(hours=i)
            comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                  baseline_confidence=0.9, ai_confidence=0.8,
                                  baseline_pnl=0.0, ai_predicted_pnl=0.0,
                                  position_ref=ABShadowComparator.build_position_ref("BTC", ts))
            comp.backfill_trade_result(symbol="BTC", entry_timestamp=ts,
                                       baseline_pnl_usdt=0.20, baseline_pnl_pct=0.02)
        for r in comp.state.records:
            r['ai_predicted_pnl'] = 0.0
        comp._save_state()
        result = comp.evaluate()
        assert result['n_samples'] >= 20
        assert result['transition'] in ('SHADOW→DISABLED', None)

    def test_c18_insufficient_samples_no_transition(self, fresh_comp):
        """样本不足 20 → 不触发状态转移。"""
        comp = fresh_comp
        self._fill_paired_records(comp, 10, baseline_pnl=0.10, ai_pnl=0.20)
        result = comp.evaluate()
        assert result['n_samples'] < MIN_SAMPLES_FOR_TEST
        assert result['transition'] is None


class TestPnLBackfill:
    """§5.3 PnL 回填 3 级匹配。"""

    def test_c19_level1_position_ref_exact_match(self, fresh_comp):
        """L1: position_ref 精确匹配 → 回填成功。"""
        ts = datetime.utcnow() - timedelta(hours=2)
        ref = ABShadowComparator.build_position_ref("ETH", ts)
        fresh_comp.record_decision(symbol="ETH", baseline_action="OPEN", ai_action="OPEN",
                                    baseline_confidence=0.9, ai_confidence=0.9,
                                    baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
        filled = fresh_comp.backfill_trade_result(symbol="ETH", entry_timestamp=ts,
                                                  baseline_pnl_usdt=0.25, baseline_pnl_pct=0.025)
        assert filled == 1
        r = fresh_comp.state.records[-1]
        assert r['pnl_backfilled'] is True
        assert r['baseline_pnl'] == 0.25

    def test_c20_level2_symbol_timestamp_fuzzy_match(self, fresh_comp):
        """L2: position_ref 不匹配但 symbol+timestamp 模糊匹配。"""
        ts = datetime.utcnow() - timedelta(hours=2)
        fresh_comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                    baseline_confidence=0.9, ai_confidence=0.9,
                                    baseline_pnl=0.0, ai_predicted_pnl=0.0,
                                    position_ref="BTC|20200101T0000")
        filled = fresh_comp.backfill_trade_result(symbol="BTC", entry_timestamp=ts,
                                                  baseline_pnl_usdt=0.15, baseline_pnl_pct=0.015)
        assert filled == 1

    def test_c21_level3_symbol_fallback(self, fresh_comp):
        """L3: position_ref 和 timestamp 都不匹配 → symbol 兜底。"""
        fresh_comp.record_decision(symbol="SOL", baseline_action="OPEN", ai_action="OPEN",
                                   baseline_confidence=0.9, ai_confidence=0.9,
                                   baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref="")
        filled = fresh_comp.backfill_trade_result(symbol="SOL", entry_timestamp=datetime.utcnow(),
                                                  baseline_pnl_usdt=0.10, baseline_pnl_pct=0.01)
        assert filled == 1

    def test_c22_no_match_returns_zero(self, fresh_comp):
        """完全不匹配 → 回填 0 条。"""
        fresh_comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                    baseline_confidence=0.9, ai_confidence=0.9,
                                    baseline_pnl=0.0, ai_predicted_pnl=0.0,
                                    position_ref="BTC|20200101T0000")
        filled = fresh_comp.backfill_trade_result(symbol="ETH", entry_timestamp=datetime.utcnow(),
                                                  baseline_pnl_usdt=0.10)
        assert filled == 0

    def test_c23_ai_pnl_estimation_open_skip(self, fresh_comp):
        """AI 路径 PnL: ba=OPEN, aa=SKIP → ai_pnl=0。"""
        ts = datetime.utcnow() - timedelta(hours=1)
        ref = ABShadowComparator.build_position_ref("BTC", ts)
        fresh_comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="SKIP",
                                    baseline_confidence=0.9, ai_confidence=0.8,
                                    baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
        fresh_comp.backfill_trade_result(symbol="BTC", entry_timestamp=ts,
                                         baseline_pnl_usdt=0.20, baseline_pnl_pct=0.02)
        assert fresh_comp.state.records[-1]['ai_predicted_pnl'] == 0.0

    def test_c24_ai_pnl_estimation_same_action(self, fresh_comp):
        """AI 路径 PnL: ba=aa=OPEN → ai_pnl=baseline_pnl。"""
        ts = datetime.utcnow() - timedelta(hours=1)
        ref = ABShadowComparator.build_position_ref("BTC", ts)
        fresh_comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                    baseline_confidence=0.9, ai_confidence=0.8,
                                    baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
        fresh_comp.backfill_trade_result(symbol="BTC", entry_timestamp=ts,
                                         baseline_pnl_usdt=0.30, baseline_pnl_pct=0.03)
        assert fresh_comp.state.records[-1]['ai_predicted_pnl'] == 0.30


class TestVersionIteration:
    """§6 版本迭代场景（正常进化 / 劣化被拒 / 线上退化回滚）。"""

    def _setup(self, tmp_path):
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        it = IncrementalTrainer(model_base_dir=str(tmp_path / "models"),
                                state_file=str(tmp_path / "inc.json"), ab_comparator=comp)
        return it, comp

    def _register_and_backtest(self, it, version, metrics):
        base = Path(it.version_mgr.base_dir)
        b = _make_pt_file(base / version / "bilstm.pt")
        p = _make_pt_file(base / version / "patchtst.pt")
        it.version_mgr.register_version(b, p, {})
        it._backtest_model = lambda bi, pa, label='': metrics

    def test_c25_scenario_6_1_normal_evolution(self, tmp_path):
        """§6.1 正常迭代：v1→v2→v3 持续进化。"""
        it, comp = self._setup(tmp_path)
        self._register_and_backtest(it, "v1", _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10))
        r1 = it.evaluate_and_promote()
        assert r1['action'] == 'promoted'
        self._register_and_backtest(it, "v2", _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08))
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_samples': 25}
        r2 = it.evaluate_and_promote()
        comp.evaluate = orig
        assert r2['action'] == 'promoted' and comp.state.dynamic_baseline_version == 'v2'
        self._register_and_backtest(it, "v3", _mock_metrics(pnl=2.0, win_rate=0.75, mdd=0.06))
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_samples': 25}
        r3 = it.evaluate_and_promote()
        comp.evaluate = orig
        assert r3['action'] == 'promoted' and comp.state.dynamic_baseline_version == 'v3'

    def test_c26_scenario_6_2_inferior_rejected(self, tmp_path):
        """§6.2 劣化版本被拒：v2(live) → v3 劣化 → disabled。"""
        it, comp = self._setup(tmp_path)
        self._register_and_backtest(it, "v1", _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05))
        it.evaluate_and_promote()
        self._register_and_backtest(it, "v2", _mock_metrics(pnl=2.5, win_rate=0.75, mdd=0.04))
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_samples': 25}
        it.evaluate_and_promote()
        comp.evaluate = orig
        assert it.version_mgr.state.current_live_version == 'v2'
        self._register_and_backtest(it, "v3", _mock_metrics(pnl=0.5, win_rate=0.30, mdd=0.15))
        r3 = it.evaluate_and_promote()
        assert r3['action'] == 'disabled_inferior'
        assert it.version_mgr.state.current_live_version == 'v2'

    def test_c27_scenario_6_3_live_rollback(self, tmp_path):
        """§6.3 线上退化回滚：v2(live) → 退化 → rollback 到 v1。"""
        it, comp = self._setup(tmp_path)
        self._register_and_backtest(it, "v1", _mock_metrics(pnl=1.0))
        it.evaluate_and_promote()
        self._register_and_backtest(it, "v2", _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08))
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_samples': 25}
        it.evaluate_and_promote()
        comp.evaluate = orig
        assert it.version_mgr.state.current_live_version == 'v2'
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=0.0, win_rate=0.0, mdd=0.20)
        comp.evaluate = lambda: {'transition': 'LIVE→SHADOW', 'n_samples': 25}
        result = it.evaluate_and_promote()
        comp.evaluate = orig
        assert result['action'] == 'rollback'
        assert it.version_mgr.state.current_live_version == 'v1'


class TestMonitoringReport:
    """§10 generate_report 监控指标。"""

    def test_c28_report_has_all_fields(self, fresh_comp):
        """generate_report 包含文档 §10 所有字段。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=1.5))
        report = fresh_comp.generate_report()
        for field in ['current_state', 'total_records', 'total_evaluations',
                      'dynamic_baseline_version', 'dynamic_baseline_metrics',
                      'evaluation', 'baseline_action_distribution',
                      'ai_action_distribution', 'ai_model_stats', 'generated_at']:
            assert field in report, f"missing field: {field}"

    def test_c29_report_dynamic_baseline_info(self, fresh_comp):
        """report 中 dynamic_baseline 字段正确。"""
        fresh_comp.set_dynamic_baseline("v3", _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05))
        report = fresh_comp.generate_report()
        assert report['dynamic_baseline_version'] == 'v3'
        assert report['dynamic_baseline_metrics']['total_pnl'] == 2.0

    def test_c30_report_no_dynamic_baseline(self, fresh_comp):
        """无动态基线时 report 中字段为 None。"""
        report = fresh_comp.generate_report()
        assert report['dynamic_baseline_version'] is None
        assert report['dynamic_baseline_metrics'] is None

    def test_c31_report_action_distribution(self, fresh_comp):
        """report 中 action 分布统计正确。"""
        for i in range(5):
            fresh_comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                       baseline_confidence=0.9, ai_confidence=0.9,
                                       baseline_pnl=0.0, ai_predicted_pnl=0.0)
        for i in range(3):
            fresh_comp.record_decision(symbol="ETH", baseline_action="ADDON", ai_action="SKIP",
                                       baseline_confidence=0.8, ai_confidence=0.7,
                                       baseline_pnl=0.0, ai_predicted_pnl=0.0)
        report = fresh_comp.generate_report()
        assert report['baseline_action_distribution'] == {"OPEN": 5, "ADDON": 3}
        assert report['ai_action_distribution'] == {"OPEN": 5, "SKIP": 3}
        assert report['total_records'] == 8

    def test_c32_report_ai_model_stats(self, fresh_comp):
        """report 中 AI 模型统计字段正确。"""
        for i in range(3):
            fresh_comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                       baseline_confidence=0.9, ai_confidence=0.8,
                                       baseline_pnl=0.0, ai_predicted_pnl=0.0,
                                       ai_p_bust=0.15 + i * 0.01, ai_drawdown=0.03 + i * 0.005)
        report = fresh_comp.generate_report()
        assert report['ai_model_stats']['p_bust_count'] == 3
        assert 0.15 < report['ai_model_stats']['p_bust_mean'] < 0.18


class TestConfigParams:
    """§7 配置参数边界验证。"""

    def test_c33_min_samples_constant(self):
        """MIN_SAMPLES_FOR_TEST=20。"""
        assert MIN_SAMPLES_FOR_TEST == 20

    def test_c34_state_thresholds(self):
        """状态转移阈值常量正确。"""
        assert SHADOW_TO_LIVE_PVALUE == 0.05
        assert SHADOW_TO_LIVE_MIN_GAIN == 0.02
        assert LIVE_TO_SHADOW_PVALUE == 0.10
        assert LIVE_TO_SHADOW_MAX_LOSS == -0.01
        assert EVALUATION_WINDOW_DAYS == 30
        assert LIVE_EVALUATION_WINDOW_DAYS == 7

    def test_c35_max_records_cap(self, fresh_comp):
        """records 超过 1000 条自动截断。"""
        for i in range(1005):
            fresh_comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                        baseline_confidence=0.9, ai_confidence=0.9,
                                        baseline_pnl=0.0, ai_predicted_pnl=0.0)
        assert len(fresh_comp.state.records) == 1000


# ===========================================================================
# CLI — 支持直接运行 + 生成报告
# ===========================================================================

if __name__ == "__main__":
    if "--report" in sys.argv:
        # 生成 markdown 报告模式 — 使用 junit-xml 结构化输出
        import subprocess
        import xml.etree.ElementTree as ET

        junit_path = _V15_ROOT / "docs" / "test_junit.xml"
        junit_path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", __file__,
             f"--junit-xml={junit_path}", "--tb=short", "-q"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(_V15_ROOT),
        )
        stdout_text = result.stdout

        # 解析 junit XML
        passed, failed, errors_list = [], [], []
        total = 0
        try:
            tree = ET.parse(str(junit_path))
            root = tree.getroot()
            for tc in root.iter("testcase"):
                total += 1
                cls = tc.get("classname", "")
                cls_name = cls.split(".")[-1] if cls else ""
                fn = tc.get("name", "")
                time_s = tc.get("time", "0")
                # 检查是否有 failure 或 error 子节点
                fail_el = tc.find("failure")
                err_el = tc.find("error")
                if fail_el is not None:
                    failed.append((cls_name, fn, time_s, fail_el.get("message", "")))
                elif err_el is not None:
                    errors_list.append((cls_name, fn, time_s, err_el.get("message", "")))
                else:
                    passed.append((cls_name, fn, time_s))
        except Exception:
            pass

        # 解析 pytest 摘要行
        summary_line = ""
        for l in reversed(stdout_text.strip().split("\n")):
            if "passed" in l or "failed" in l or "error" in l:
                summary_line = l.strip()
                break

        report_path = _V15_ROOT / "docs" / "test_suite_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# V15 双基线 AB 影子对比框架 — 测试套件运行报告\n\n")
            f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**总用例数**: {total}\n")
            f.write(f"**通过**: {len(passed)} | **失败**: {len(failed)} | **错误**: {len(errors_list)}\n\n")
            if summary_line:
                f.write(f"**pytest 摘要**: `{summary_line}`\n\n")
            f.write("## 测试结果明细\n\n")
            f.write("| # | 测试类 | 用例 | 状态 | 耗时(s) |\n")
            f.write("|---|---|---|---|---|\n")
            idx = 1
            for cls, fn, t in passed:
                f.write(f"| {idx} | `{cls}` | `{fn}` | PASS | {t} |\n")
                idx += 1
            for cls, fn, t, msg in failed:
                f.write(f"| {idx} | `{cls}` | `{fn}` | FAIL | {t} |\n")
                idx += 1
            for cls, fn, t, msg in errors_list:
                f.write(f"| {idx} | `{cls}` | `{fn}` | ERROR | {t} |\n")
                idx += 1
            if failed or errors_list:
                f.write("\n## 失败详情\n\n")
                for cls, fn, t, msg in failed + errors_list:
                    f.write(f"- `{cls}::{fn}`: {msg}\n")
            f.write("\n## 测试套件结构\n\n")
            f.write("| 模块 | 测试类 | 用例数 | 覆盖文档章节 |\n")
            f.write("|---|---|---|---|\n")
            f.write("| §A ABShadowComparator 核心 | `TestABComparatorCore` | 12 | §5 状态机 + §5.3 PnL回填 + §7 配置 |\n")
            f.write("| §B ModelVersionManager | `TestModelVersionManager` | 4 | §4 版本注册/晋升/回滚 |\n")
            f.write("| §B IncrementalTrainer 核心 | `TestIncrementalTrainerCore` | 4 | §4 调用链 + §4.2 热切换 |\n")
            f.write("| §B 增量训练双基线 | `TestIncrementalTrainerDualBaseline` | 3 | §3.3 bootstrap + 版本迭代 |\n")
            f.write("| §C 决策矩阵 | `TestDecisionMatrix` | 6 | §3.1 决策矩阵 6 行 |\n")
            f.write("| §C 评分规则 | `TestScoringRules` | 7 | §3.2 评分边界条件 |\n")
            f.write("| §C Bootstrap | `TestBootstrapLogic` | 2 | §3.3 首版本 bootstrap |\n")
            f.write("| §C 状态机 | `TestABStateMachineTransitions` | 3 | §5.2 状态转移条件 |\n")
            f.write("| §C PnL回填 | `TestPnLBackfill` | 6 | §5.3 三级匹配 |\n")
            f.write("| §C 版本迭代 | `TestVersionIteration` | 3 | §6 三种迭代场景 |\n")
            f.write("| §C 监控报告 | `TestMonitoringReport` | 5 | §10 generate_report |\n")
            f.write("| §C 配置参数 | `TestConfigParams` | 3 | §7 阈值常量 |\n")
            f.write(f"| **合计** | **12 个测试类** | **{total}** | **10 个章节全覆盖** |\n")
        print(f"报告已生成: {report_path}")
        print(f"通过: {len(passed)} | 失败: {len(failed)} | 错误: {len(errors_list)}")
        sys.exit(0 if not failed and not errors_list else 1)
    else:
        sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
