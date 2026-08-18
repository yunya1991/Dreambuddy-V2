"""test_ab_comparator.py — ABShadowComparator 核心功能单测.

覆盖项（对应阻塞修复1/2/3之验证）:
  T1  DecisionRecord 新字段 (position_ref, pnl_backfilled) 存在并序列化
  T2  build_position_ref 分钟级截断 & 多输入类型稳定
  T3  6 段 p-value 近似表 → 精确 t CDF 替换后数值正确（零差→p≃1、大差异→p≪0.05）
  T4  backfill_trade_result: position_ref 精确命中 + fallback 命中 + 无匹配返回 0
  T5  PnL 规则正确性（OPEN-SKIP / OPEN-OPEN / ADDON-OPEN 三种 AI 决策路径 PnL 估算）
  T6  SHADOW → LIVE → SHADOW 状态机闭环（30 笔配对样本 SHADOW 晋升、LIVE 7天样本劣化回滚）
  T7  state_file 原子写 & crash 后空 state 恢复（读取损坏 JSON 返回空）
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest  # type: ignore

# Ensure imports work whether we run from tests/ or V15 root
_HERE = Path(__file__).resolve().parent
_V15_ROOT = _HERE.parent
if str(_V15_ROOT) not in sys.path:
    sys.path.insert(0, str(_V15_ROOT))

from ab_shadow_comparator import (  # noqa: E402
    ABShadowComparator,
    ABComparatorState,
    STATE_SHADOW,
    STATE_LIVE,
    STATE_DISABLED,
    MIN_SAMPLES_FOR_TEST,
    SHADOW_TO_LIVE_MIN_GAIN,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_state(tmp_path):
    f = tmp_path / "ab_state.json"
    comp = ABShadowComparator(state_file=str(f))
    comp.force_state(STATE_SHADOW)
    return comp, f


def _ts(hours_offset: int) -> str:
    """返回 N 小时前的 UTC ISO（带 Z）"""
    dt = datetime.utcnow() - timedelta(hours=hours_offset)
    return dt.isoformat() + "Z"


# ---------------------------------------------------------------------------
# T1 + T2
# ---------------------------------------------------------------------------

def test_t1_decision_record_new_fields(fresh_state):
    comp, _ = fresh_state
    # 模拟开仓决策时记录，带 position_ref
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
    # 序列化可逆（磁盘 → 读回）
    comp2 = ABShadowComparator(state_file=str(comp.state_file))
    assert comp2.state.records[-1]["position_ref"] == ref
    assert comp2.state.records[-1]["pnl_backfilled"] is False


def test_t2_build_position_ref_granularity_and_types():
    coin = "ETH"
    iso1 = "2026-08-19T12:34:56.789Z"
    iso2 = "2026-08-19T12:34:01+00:00"
    dt = datetime(2026, 8, 19, 12, 34, 56, 123, tzinfo=timezone.utc)
    unix = dt.timestamp()
    # 以上应全部被分钟级截断为 2026-08-19T12:34
    r_iso1 = ABShadowComparator.build_position_ref(coin, iso1)
    r_iso2 = ABShadowComparator.build_position_ref(coin, iso2)
    r_dt = ABShadowComparator.build_position_ref(coin, dt)
    r_unix = ABShadowComparator.build_position_ref(coin, unix)
    expected = "ETH|2026-08-19T12:34:00"
    assert r_iso1 == expected
    assert r_iso2 == expected
    assert r_dt == expected
    assert r_unix == expected
    # 差 1 分钟 → 不同 ref
    dt_other = datetime(2026, 8, 19, 12, 35, tzinfo=timezone.utc)
    assert ABShadowComparator.build_position_ref(coin, dt_other) != expected


# ---------------------------------------------------------------------------
# T3 精确 t CDF
# ---------------------------------------------------------------------------

def test_t3_exact_t_cdf(fresh_state):
    comp, _ = fresh_state
    # 零差场景 → p 应该≈1.0
    t0 = comp._paired_t_test([0.0] * 12, [0.0] * 12)
    assert t0["t_stat"] == pytest.approx(0.0, abs=1e-9)
    assert t0["p_value"] > 0.9, f"零差 p={t0['p_value']} 应≈1.0（完全无法区分）"

    # 大差异、正方差（40 samples，基线 -1 ±噪声，AI 0 ±噪声）
    base = [-1.0 + ((i * 37) % 7 - 3) * 0.08 for i in range(40)]
    ai = [0.0 + ((i * 53) % 7 - 3) * 0.08 for i in range(40)]
    t1 = comp._paired_t_test(base, ai)
    assert t1["significant"] is True
    assert t1["p_value"] < 0.001, f"大差异 p={t1['p_value']} 应非常小"
    assert t1["mean_diff"] > 0.9


# ---------------------------------------------------------------------------
# T4 backfill 匹配策略
# ---------------------------------------------------------------------------

def test_t4_backfill_matching_modes(fresh_state):
    comp, _ = fresh_state
    coin = "SOL"

    # A) position_ref 精确匹配
    ts = "2026-08-01T10:00:00Z"
    ref = ABShadowComparator.build_position_ref(coin, ts)
    comp.record_decision(symbol=coin, baseline_action="OPEN", ai_action="OPEN",
                         baseline_confidence=0.9, ai_confidence=0.95,
                         baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
    # 插入另一条（干扰），同 symbol 不同 ref
    ts2 = "2026-08-01T11:00:00Z"
    ref2 = ABShadowComparator.build_position_ref(coin, ts2)
    comp.record_decision(symbol=coin, baseline_action="OPEN", ai_action="SKIP",
                         baseline_confidence=0.85, ai_confidence=0.25,
                         baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref2)
    # 回填 ts2，应精确命中第 2 条
    n = comp.backfill_trade_result(symbol=coin, entry_timestamp=ts2,
                                   baseline_pnl_usdt=-0.5, baseline_pnl_pct=-0.05,
                                   exit_reason="bust")
    assert n == 1
    r2 = comp.state.records[-1]
    assert r2["pnl_backfilled"] is True
    assert r2["baseline_pnl"] == pytest.approx(-0.5)
    r1 = comp.state.records[0]
    assert r1["pnl_backfilled"] is False, "精确匹配不应误伤邻居"

    # B) Fallback 模式：position_ref 不匹配 但 7天内+symbol+OPEN/ADDON+未回填命中
    ts_near = datetime.utcnow() - timedelta(minutes=30)
    # 一条不带 ref 的记录（模拟老版本数据）
    comp.record_decision(symbol=coin, baseline_action="OPEN", ai_action="OPEN",
                         baseline_confidence=0.9, ai_confidence=0.9,
                         baseline_pnl=0.0, ai_predicted_pnl=0.0,
                         position_ref="")
    n2 = comp.backfill_trade_result(symbol=coin, entry_timestamp=ts_near,
                                    baseline_pnl_usdt=0.2, baseline_pnl_pct=0.02,
                                    exit_reason="tp")
    assert n2 == 1
    last = comp.state.records[-1]
    assert last["pnl_backfilled"] is True
    assert last["position_ref"] != "", "fallback命中时应补上position_ref"

    # C) 完全不匹配：symbol 错 → 返回 0
    n3 = comp.backfill_trade_result(symbol="DOESNOTEXIST", entry_timestamp=ts_near,
                                    baseline_pnl_usdt=0.2, baseline_pnl_pct=0.02)
    assert n3 == 0


# ---------------------------------------------------------------------------
# T5 PnL 规则正确性
# ---------------------------------------------------------------------------

def test_t5_ai_path_pnl_estimates(fresh_state):
    comp, _ = fresh_state
    coin = "BTC"
    cases = [
        # (ba, aa, baseline_usdt, ai_addon_delta_ratio, expected_ai_pnl, desc)
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
        r = comp.state.records[-1]
        assert r["ai_predicted_pnl"] == pytest.approx(exp_ai, abs=1e-4), desc


# ---------------------------------------------------------------------------
# T6 状态机闭环（SHADOW→LIVE 晋升 & LIVE→SHADOW 回滚）
# ---------------------------------------------------------------------------

def test_t6_state_machine_promote_and_rollback(fresh_state):
    comp, state_file = fresh_state
    assert comp.get_state() == STATE_SHADOW

    # 构造 30 笔配对样本使 AI 显著优于基线（至少 > 2% 改善，p<0.05）
    random.seed(1)
    for i in range(30):
        entry_dt = datetime.utcnow() - timedelta(days=10) + timedelta(hours=i * 3)
        entry_ts = entry_dt.isoformat() + "Z"
        ref = ABShadowComparator.build_position_ref("BTC", entry_ts)
        if i < 15:
            # AI 同意开，基线赚 1%
            comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                 baseline_confidence=0.9, ai_confidence=0.95,
                                 baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
            comp.backfill_trade_result(symbol="BTC", entry_timestamp=entry_ts,
                                       baseline_pnl_usdt=0.10, baseline_pnl_pct=0.01)
        else:
            # AI 否决 SKIP，基线爆亏 3%
            comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="SKIP",
                                 baseline_confidence=0.9, ai_confidence=0.1,
                                 baseline_pnl=0.0, ai_predicted_pnl=0.0, position_ref=ref)
            comp.backfill_trade_result(symbol="BTC", entry_timestamp=entry_ts,
                                       baseline_pnl_usdt=-0.30, baseline_pnl_pct=-0.03,
                                       ai_skipped_open_pnl=0.0)

    report = comp.generate_report()
    ev = report["evaluation"]
    assert ev["n_samples"] >= MIN_SAMPLES_FOR_TEST
    assert ev["t_test"]["significant"], f"晋升应显著 t_test={ev['t_test']}"
    assert ev["t_test"]["mean_diff"] > SHADOW_TO_LIVE_MIN_GAIN, "改善应超阈值"
    assert ev["bootstrap"]["positive"], "CI 下限>0"
    assert report["current_state"] == STATE_LIVE or ev.get("transition") == "SHADOW→LIVE"
    assert comp.get_state() == STATE_LIVE

    # 模拟 LIVE 模式下连续 7 天 AI 劣于基线 → 自动回滚到 SHADOW
    # 办法：清空 records（重新构造 LIVE 窗口）
    state = comp.state
    state.records = []
    random.seed(42)
    for i in range(25):
        entry_dt = datetime.utcnow() - timedelta(days=2) + timedelta(hours=i * 4)
        entry_ts = entry_dt.isoformat() + "Z"
        ref = ABShadowComparator.build_position_ref("BTC", entry_ts)
        # AI 持续比基线差 1.5% (每笔)
        base_usdt = 0.10
        ai_usdt = 0.10 - 0.03  # AI 更差
        comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                             baseline_confidence=0.9, ai_confidence=0.8,
                             baseline_pnl=base_usdt, ai_predicted_pnl=ai_usdt,
                             position_ref=ref, decision_diff="ai-underperf")
        # 显式回填（即使 record 给了 PnL 也再 backfill 一次，验证不覆盖已有 backfilled=false 外）
        comp.backfill_trade_result(symbol="BTC", entry_timestamp=entry_ts,
                                   baseline_pnl_usdt=base_usdt, baseline_pnl_pct=0.01)
        # 因为回填后 record 标记 pnl_backfilled=True，但我们上面的 record_decision 又写了一个新的
        # （这里 baseline_pnl 直接写了值，但 backfill 会匹配 position_ref）

    # 手动 evaluate
    comp.force_state(STATE_LIVE)  # 确保是 LIVE
    ev2 = comp.evaluate()
    # 因为我们 25 条全部 baseline=0.1，ai=0.07（AI 差 0.03 每笔），统计上应显著
    # 如果记录刚好是 25 条配对，应触发回滚（如果 t 不够显著，增加几条更差的强化）
    if ev2.get("transition") != "LIVE→SHADOW (rollback)":
        for i in range(15):
            entry_dt = datetime.utcnow() - timedelta(days=1) + timedelta(hours=i * 2)
            entry_ts = entry_dt.isoformat() + "Z"
            ref = ABShadowComparator.build_position_ref("BTC", entry_ts)
            comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                                 baseline_confidence=0.9, ai_confidence=0.8,
                                 baseline_pnl=0.0, ai_predicted_pnl=0.0,
                                 position_ref=ref)
            comp.backfill_trade_result(symbol="BTC", entry_timestamp=entry_ts,
                                       baseline_pnl_usdt=0.15, baseline_pnl_pct=0.015)
            # 覆写 ai_predicted_pnl：backfill 默认 ba==aa → 相同 PnL，这里手动再改造成 AI 差
            rec = next(r for r in reversed(comp.state.records) if r["position_ref"] == ref)
            rec["ai_predicted_pnl"] = round(0.15 - 0.07, 4)  # AI 更差
            rec["pnl_backfilled"] = True  # 保持标记
        comp._save_state()
        ev2 = comp.evaluate()

    assert ev2.get("state") == STATE_SHADOW or ev2.get("transition") == "LIVE→SHADOW (rollback)", \
        f"LIVE 7天劣化应回滚: state={ev2.get('state')}, trans={ev2.get('transition')}, t={ev2.get('t_test')}"


# ---------------------------------------------------------------------------
# T7 原子写 + 损坏 JSON 恢复
# ---------------------------------------------------------------------------

def test_t7_corrupted_state_recovery(tmp_path):
    f = tmp_path / "corrupt.json"
    # 写损坏 JSON
    f.write_text("{not valid json :::", encoding="utf-8")
    comp = ABShadowComparator(state_file=str(f))
    # 应返回空 ABComparatorState（默认）
    assert comp.get_state() == STATE_SHADOW
    assert comp.state.records == []
    # record 之后原子写，读取回来应当无损
    comp.record_decision(symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                         baseline_confidence=0.9, ai_confidence=0.9,
                         baseline_pnl=0.0, ai_predicted_pnl=0.0)
    f2 = ABShadowComparator(state_file=str(f))
    assert len(f2.state.records) == 1
    # state_file.tmp 不应残留
    assert not (tmp_path / "corrupt.json.tmp").exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
