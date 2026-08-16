"""Paper 全链路测试 — Task 7 (2026-08-16): 选币 → 易经 → 路由 → 执行 → 记账.

验证目标:
    1. 强信号路径: OrchestratorV2 paper 链能真实 OPEN 并落盘账本(记账),
       而不是永远 REJECTED (生产 233 周期全 REJECTED 的对照实验)。
    2. 弱信号路径: 置信度门禁 (<0.50) 在全链中仍然生效。
    3. 并发门禁: 最多 3 仓 (V9 红线)。
    4. 平仓回填 + 认知闭环: record_real_exit → lessons 落盘 → 下轮注入。
    5. dry_run 安全门: paper 链永不触碰真实下单路径。

隔离: 所有状态文件由 conftest.py autouse fixture 重定向到 pytest tmp 目录,
绝不触碰生产 cli/scheduler_data/ (2026-08-15 污染事故教训)。

修复记录 (2026-08-16, 用户批准 "1和2全部修复"):
    B-1 [已修复]: TRIGRAM_NAMES 原按传统伏羲序排列, 但代码按二进制值索引 →
        全阳(111)曾映射"坤"而非"乾"。已重排为二进制值序(000坤→111乾)。
        回归测试: test_trigram_polarity_correct。
    F-1 [已修复]: 旧置信度公式天花板 0.75×0.8=0.6, MIN_CONFIDENCE=0.50 实际
        不可达(生产 233 周期全 REJECTED 根因)。修复: base 0.75→0.85(同向)/
        0.50→0.45(异向, 异向永不过阈), clarity 方向信号 0.8→1.0(HOLD 保持0.5)。
        新天花板 0.85; MIN_CONFIDENCE 保持 0.50 不动(阈值语义恢复可达)。
    F-2 [已修复]: goodentry lesson 阈值 0.70→0.50, 与执行门禁对齐,
        过门禁的盈利单全部沉淀正向经验。回归测试: test_f2_gap_closed。
"""
import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2, record_real_exit
from dreamos.capabilities.trading import orchestrator_v2 as orch_mod
from dreamos.capabilities.trading import v15_executor as v15x
from dreamos.capabilities.trading.v15_executor import V15Executor

# ── 测试夹具 ──────────────────────────────────────────────────────────────
# 修复后 (2026-08-16): 该强多行情 + seed=5 → LONG conf=0.765 (B-1+F-1 修复后:
# base 0.85 × 1动爻罚0.9 × trend 1.0 × consistency 1.0 × clarity 1.0)。
STRONG_SEED = 5

STRONG_BULL_MD = {
    "symbol": "TEST",
    "supply_demand_score": 0.85,
    "technical_score": 0.85,
    "capital_flow_score": 0.85,
    "sentiment_score": 0.85,
    "trend_strength": 1.0,
    "volatility": 0.05,
    "volume_ratio": 0.3,
    "price_position": 0.5,
    "ma5": 110.0,
    "ma10": 105.0,
    "ma20": 100.0,
    "momentum_direction": "UP",
    "close_price": 112.0,
    "entry_price": 112.0,
}

WEAK_FLAT_MD = {
    "symbol": "TEST",
    "supply_demand_score": 0.5,
    "technical_score": 0.5,
    "capital_flow_score": 0.5,
    "sentiment_score": 0.5,
    "trend_strength": 0.1,
    "volatility": 0.3,
    "volume_ratio": 1.0,
    "price_position": 0.5,
    "ma5": 100.0,
    "ma10": 100.0,
    "ma20": 100.0,
    "momentum_direction": "FLAT",
    "close_price": 100.0,
    "entry_price": 100.0,
}


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ── Test 1: 强信号全链路 OPEN + 记账 ─────────────────────────────────────

def test_full_chain_strong_signal_opens_position(tmp_path):
    """选币→易经→路由→执行→记账: 强信号应真实开仓(paper)并落盘."""
    orch = OrchestratorV2(use_hermes=False, seed=STRONG_SEED)
    assert orch.executor.dry_run is True, "paper 链必须 dry_run"

    result = orch.run_cycle(dict(STRONG_BULL_MD))

    # 全链状态
    assert result["status"] == "COMPLETED", f"errors={result['errors']}"
    assert result["errors"] == []

    # Layer A: 选币
    assert result["selection"]["status"] == "OK"
    assert "pools" in result["selection"]

    # Layer B: 易经信号 (seed=5, B-1+F-1 修复后 conf≈0.765)
    sig = result["signal"]
    assert sig["status"] == "OK"
    assert sig["direction"] == "LONG"
    assert sig["confidence"] >= 0.70, (
        f"conf={sig['confidence']} F-1修复后强信号应显著过阈(新天花板0.85)"
    )
    assert sig["hexagram"].get("original_gua")
    assert "cognitive_adjustment" in sig

    # Layer C+D: 执行 + 路由 → OPEN
    exe = result["execution"]
    assert exe["status"] == "OPEN", f"position={exe.get('position')}"
    pos = exe["position"]
    assert pos["status"] == "OPEN"

    # V9 红线参数核验 (不可变基线)
    assert pos["tp_pct"] == pytest.approx(0.04), "V9: TP 4%"
    assert pos["addon_gap_pct"] == pytest.approx(0.08), "V9: 加仓间隔 8%"
    assert pos["addons_remaining"] == 3, "V9: 最多3次加仓"
    assert pos["entry_price"] == pytest.approx(112.0)

    # 仓位数学: (260/3 预算 × 5 杠杆) / 112 入场价
    expected_size = (260.0 / 3 * 5.0) / 112.0
    assert pos["position_size"] == pytest.approx(expected_size, rel=1e-6)

    # Layer E: 认知快照 (P1-3 契约: 不伪造审查)
    assert result["review"]["status"] == "OK"
    assert result["review"]["mode"] == "awaiting_real_feedback"

    # 记账核验 1: 持仓账本落盘 (隔离目录)
    ledger = _read_json(v15x.POSITIONS_FILE)
    assert "TEST" in ledger["positions"]
    rec = ledger["positions"]["TEST"]
    assert rec["status"] == "OPEN"
    assert rec["direction"] == "LONG"
    assert rec["position_size"] == pytest.approx(expected_size, rel=1e-6)

    # 记账核验 2: 周期状态落盘
    state = _read_json(orch_mod.STATE_FILE)
    assert state["total_cycles"] == 1
    assert len(state["cycle_history"]) == 1


# ── Test 2: 弱信号门禁回归 ────────────────────────────────────────────────

def test_full_chain_weak_signal_stays_rejected():
    """弱信号 (conf<0.50) 在全链中必须被拒, 不落账本."""
    orch = OrchestratorV2(use_hermes=False, seed=42)
    result = orch.run_cycle(dict(WEAK_FLAT_MD))

    assert result["status"] == "COMPLETED"
    sig = result["signal"]
    assert sig["confidence"] < 0.50

    exe = result["execution"]
    assert exe["status"] == "REJECTED"
    assert "confidence" in exe["position"].get("reason", "")

    # 账本必须为空 (拒绝不落账)
    if Path(v15x.POSITIONS_FILE).exists():
        ledger = _read_json(v15x.POSITIONS_FILE)
        assert ledger["positions"] == {}


# ── Test 3: 并发门禁 (V9: 最多3仓) ───────────────────────────────────────

def test_full_chain_max_concurrent_positions_gate():
    """C层: 3 仓全开后第 4 笔必须被拒."""
    ex = V15Executor(dry_run=True)
    for i, sym in enumerate(["AAA", "BBB", "CCC"]):
        r = ex.execute_signal({
            "symbol": sym, "direction": "LONG",
            "confidence": 0.6, "entry_price": 100.0 + i,
        })
        assert r["status"] == "OPEN", f"{sym} 应开仓: {r}"

    r4 = ex.execute_signal({
        "symbol": "DDD", "direction": "LONG",
        "confidence": 0.6, "entry_price": 100.0,
    })
    assert r4["status"] == "REJECTED"
    assert "max concurrent" in r4["reason"]


# ── Test 4a: 平仓回填 → F层记账 (真实链路 conf) ──────────────────────────

def test_full_chain_exit_backfill_updates_state():
    """记账闭环前半: OPEN → 平仓回填(修复后 conf≈0.765) → W/L+PnL+lesson 落盘.

    F-2 修复后行为: 过门禁的盈利单 (conf≥0.50) 产生 goodentry lesson,
    正向学习通道打通。
    """
    orch = OrchestratorV2(use_hermes=False, seed=STRONG_SEED)
    result = orch.run_cycle(dict(STRONG_BULL_MD))
    assert result["execution"]["status"] == "OPEN"
    entry_conf = result["signal"]["confidence"]
    assert entry_conf >= 0.50, "F-1 修复后强信号必须过执行门禁"

    exit_result = {
        "symbol": "TEST", "direction": "LONG",
        "entry_price": 112.0, "exit_price": 116.48,
        "position_size": result["execution"]["position"]["position_size"],
        "confidence": entry_conf,
        "hexagram": result["signal"]["hexagram"],
        "addon_count": 0, "hold_hours": 6.0,
        "exit_reason": "TP hit|paper-test",
        "pnl_usdt": 4.2, "pnl_pct": 0.04,
    }
    review = record_real_exit(exit_result)
    assert review["status"] == "OK"
    assert review["state_update"] == "OK"
    assert review.get("assessment")

    # F层记账核验: W/L + 累计PnL 落盘
    state = _read_json(orch_mod.STATE_FILE)
    assert state["wins"] == 1
    assert state["losses"] == 0
    assert state["total_pnl"] == pytest.approx(4.2)
    assert state["consecutive_losses"] == 0

    # F-2 修复后行为: 过门禁盈利单 → goodentry lesson 产生
    assert len(review.get("lessons", [])) >= 1, "F-2 修复: 盈利单应沉淀正向经验"
    assert any("goodentry" in l.get("lesson_id", "") for l in review["lessons"])


# ── Test 4b: 认知闭环管线 (契约级 conf=0.75) ──────────────────────────────

def test_cognitive_loop_positive_lesson_injection():
    """记账闭环后半: 盈利 lesson → 落盘 → 新实例加载 → 下轮正向注入.

    用契约级 conf=0.75 (与既有 test_phase7_cognitive_injection 一致)
    验证 E层管线本身完好; conf>=0.70 在真实链路不可达是 F-2 参数问题,
    不是管线故障。
    """
    exit_result = {
        "symbol": "TEST", "direction": "LONG",
        "entry_price": 112.0, "exit_price": 116.48,
        "position_size": 3.8, "confidence": 0.75,
        "hexagram": {}, "addon_count": 0, "hold_hours": 6.0,
        "exit_reason": "TP hit|paper-test",
        "pnl_usdt": 4.2, "pnl_pct": 0.04,
    }
    review = record_real_exit(exit_result)
    assert review["status"] == "OK"
    assert review["state_update"] == "OK"
    assert len(review["lessons"]) >= 1, "conf=0.75 盈利单应产生 goodentry lesson"

    # lessons 落盘 (隔离目录)
    lessons = _read_json(orch_mod.LESSONS_FILE)
    stored = lessons.get("lessons", lessons if isinstance(lessons, list) else [])
    assert len(stored) >= 1

    # 新实例启动加载 → 认知上下文
    orch2 = OrchestratorV2(use_hermes=False, seed=STRONG_SEED)
    ctx = orch2.reviewer.get_cognitive_context()
    assert ctx["total_reviews"] >= 1
    assert ctx["total_pnl"] > 0
    assert ctx["win_rate"] > 0.6
    assert ctx["confidence_adjustment"] > 0, "盈利教训应产生正向调整"

    # 下一周期: 注入痕迹随信号携带 (P1-1)
    result2 = orch2.run_cycle(dict(STRONG_BULL_MD))
    sig2 = result2["signal"]
    assert result2["review"]["cognitive_context"]["total_reviews"] >= 1
    if "confidence_raw" in sig2:
        assert sig2["confidence"] == pytest.approx(
            max(0.0, min(1.0, sig2["confidence_raw"] + sig2["cognitive_adjustment"])),
            abs=1e-4,
        )


# ── Test 4c: F-2 修复回归 — 正向学习通道打通 ──────────────────────────────

def test_f2_gap_closed(tmp_path):
    """F-2 修复回归: goodentry 阈值 0.70→0.50 与执行门禁对齐。

    修复前: conf∈[0.50,0.70) 盈利单无 lesson (旧天花板0.6 → 正向学习不可达)。
    修复后: 过门禁(≥0.50)的盈利单全部沉淀正向经验; 未过门禁的不沉淀。
    """
    from dreamos.capabilities.trading.cognitive_reviewer import CognitiveReviewer

    reviewer = CognitiveReviewer(lessons_filepath=str(tmp_path / "lessons.json"))

    # 过门禁的盈利单 → 必须产生 goodentry lesson
    review = reviewer.review({
        "symbol": "GAP", "direction": "LONG",
        "entry_price": 100.0, "exit_price": 104.0,
        "confidence": 0.54,  # 修复前 F-2 盲区典型值
        "addon_count": 0, "hold_hours": 5.0,
        "exit_reason": "TP hit", "pnl_usdt": 3.0, "pnl_pct": 0.04,
    })
    assert review["assessment"] in ("GOOD", "NEUTRAL", "BAD")
    assert any("goodentry" in l.get("lesson_id", "") for l in review["lessons"]), (
        "F-2 修复后: 过门禁盈利单必须沉淀正向经验"
    )

    # 未过门禁的盈利单 (<0.50) → 不产生 lesson (边界仍有效)
    review2 = reviewer.review({
        "symbol": "EDGE", "direction": "LONG",
        "entry_price": 100.0, "exit_price": 104.0,
        "confidence": 0.49,
        "addon_count": 0, "hold_hours": 5.0,
        "exit_reason": "TP hit", "pnl_usdt": 3.0, "pnl_pct": 0.04,
    })
    assert not any("goodentry" in l.get("lesson_id", "") for l in review2["lessons"])


# ── Test 5: dry_run 安全门 ────────────────────────────────────────────────

def test_dry_run_gate_never_touches_real_orders():
    """P0-3: paper 链 OPEN 时真实下单路径必须被 dry_run 门拦截."""
    ex = V15Executor(dry_run=True)  # 显式 paper
    r = ex.execute_signal({
        "symbol": "SAFE", "direction": "LONG",
        "confidence": 0.9, "entry_price": 100.0,
    })
    assert r["status"] == "OPEN"
    real = r.get("real_order", {})
    assert real.get("dry_run") is True
    assert real.get("status") == "simulated"

    # 默认行为 (无显式参数 + 无环境变量) 也必须是 dry_run
    import os
    assert os.environ.get("DREAMOS_TRADING_DRY_RUN", "true").lower() != "false"
    ex_default = V15Executor()
    assert ex_default.dry_run is True


# ── Test 6: B-1 卦序极性回归测试 (修复后必须常绿) ─────────────────────────

def test_trigram_polarity_correct():
    """B-1 修复回归: 全阳爻(111) → 乾(Heaven/UP), 全阴爻(000) → 坤(Earth/DOWN)。

    修复前: TRIGRAM_NAMES 按传统伏羲序排列但按二进制值索引, 极性反转。
    2026-08-16 修复: 重排为二进制值序。本测试锁定修复, 防止回归。
    """
    from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator

    g = YijingSignalGenerator(seed=42)
    # 全阳: 两维分数均远超所有阈值 (0.35/0.55/0.65) → bits 应为 7 (111)
    bits = g._score_to_trigram(0.85, 0.85)
    assert bits == 7
    from dreamos.capabilities.trading.yijing_signal_generator import (
        TRIGRAM_NAMES, TRIGRAM_DIRECTIONS,
    )
    assert TRIGRAM_NAMES[7] == "Qian", "111=乾(Heaven)"
    assert TRIGRAM_NAMES[0] == "Kun", "000=坤(Earth)"
    # 极性语义: 乾=UP, 坤=DOWN
    assert TRIGRAM_DIRECTIONS["Qian"] == "UP"
    assert TRIGRAM_DIRECTIONS["Kun"] == "DOWN"


# ── Test 7: 真实行情冒烟 (只读, 不落账本) ─────────────────────────────────

def test_live_enrichment_smoke():
    """生产同路: enrich_market_data 注入12项指标 + B层可消费。

    只读测试: 仅 generate() 不 execute(), 不触碰账本。
    网络不可达时优雅跳过。
    """
    from dreamos.cli.auto_trader import AutoTrader
    from dreamos.capabilities.trading.market_enrichment import enrich_market_data
    from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator

    try:
        trader = AutoTrader(dry_run=True, exchange="hyperliquid")
        md = enrich_market_data(
            "BTC",
            {"symbol": "BTC", "entry_price": 0.0, "close_price": 0.0},
            trader._fetch_market_data,
        )
    except Exception as e:
        pytest.skip(f"live 数据不可达: {e}")

    if not md.get("ma20"):
        pytest.skip("live K线不足, enrichment 降级")

    required = [
        "ma5", "ma10", "ma20", "momentum_direction", "volatility",
        "volume_ratio", "price_position", "trend_strength",
        "technical_score", "supply_demand_score",
        "capital_flow_score", "sentiment_score",
    ]
    missing = [k for k in required if k not in md]
    assert not missing, f"指标注入缺失: {missing}"
    assert md["entry_price"] > 0

    sig = YijingSignalGenerator(seed=42).generate(md)
    assert sig["direction"] in ("LONG", "SHORT", "HOLD")
    assert 0.0 <= sig["confidence"] <= 1.0
    # 观测输出: 真实行情下的信号 (预期多为低conf — F-1 根因记录)
    print(
        f"\nLIVE BTC: dir={sig['direction']} conf={sig['confidence']} "
        f"trend={md['trend_strength']} gua={sig['hexagram']['original_gua']}"
    )
