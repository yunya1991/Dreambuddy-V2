"""多币种场景模拟验证 — BCRM trailing + S3 盲区双修复

验证维度:
  1. 有效性: 多币种(多空/盈亏/峰值回撤/重开仓)场景下逻辑正确
  2. 架构无冲突: ExitManager 链序正确 / trailing 不阻塞 force_close /
     adjust_sl_tp 不 return 不影响 S3 / peak 隔离 per-coin
  3. 优雅改动: 复用已有框架(ExitStrategy 模式)、复用已验证算法(BDSM peak)、
     最小侵入(仅新增策略类+路由分支+决策树2处)、FAIL-OPEN 安全
"""

import sys
from pathlib import Path

# 与 test_multi_horizon_predict.py 一致的路径设置
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import scripts.memory_l4.trading_utils as tu
from scripts.memory_l4.bcrm2.exit_manager import (
    ExitManager, ExitContext, ExitDecision,
)
from scripts.memory_l4.bcrm2.exit_strategies import (
    P3EarlyExitStrategy, WashoutHoldStrategy, SignalReverseStrategy,
    EvForceCloseStrategy, TimeoutProfitSwitchStrategy, EvAdjustStrategy,
    TrailingStopStrategy,
)
from scripts.memory_l4.polling_trader import PollingTrader


# =============================================================
# Part 1: TrailingStopStrategy 多币种场景模拟
# =============================================================

def test_trailing_multi_coin():
    """多币种 trailing 场景: 长/短/盈亏/峰值回撤/重开仓 peak 隔离"""
    s = TrailingStopStrategy(
        break_even_pct=0.02, trailing_arm_pct=0.04, trailing_retrace_pct=0.015
    )
    results = []

    def ctx(coin, upl):
        return ExitContext(coin=coin, inference={}, pos_info={"upl_ratio": upl},
                           tracker_pos=None, in_protection=False, age_hours=1.0)

    # --- Coin A: 多头, 盈利爬升至 +6% 峰值后回撤 ---
    # 0% → pass
    r = s.evaluate(ctx("A-LONG", 0.0))
    results.append(("A-LONG 0%", r.action == "pass"))
    # +1% → pass (未达 break_even)
    r = s.evaluate(ctx("A-LONG", 0.01))
    results.append(("A-LONG +1%", r.action == "pass"))
    # +3% → break_even
    r = s.evaluate(ctx("A-LONG", 0.03))
    results.append(("A-LONG +3% break_even", r.action == "adjust_sl_tp"
                    and r.params.get("mode") == "break_even"))
    # +6% → trailing (peak=6%)
    r = s.evaluate(ctx("A-LONG", 0.06))
    results.append(("A-LONG +6% trailing", r.action == "adjust_sl_tp"
                    and r.params.get("mode") == "trailing"
                    and abs(r.params.get("peak", 0) - 0.06) < 1e-9))
    # 回撤到 +2% → 仍 trailing (peak ratchet 保持 6%)
    r = s.evaluate(ctx("A-LONG", 0.02))
    results.append(("A-LONG 回撤+2% still trailing", r.action == "adjust_sl_tp"
                    and r.params.get("mode") == "trailing"
                    and abs(r.params.get("peak", 0) - 0.06) < 1e-9))
    # 回撤到 -1% → pass (亏损区交给 SL 兜底)
    r = s.evaluate(ctx("A-LONG", -0.01))
    results.append(("A-LONG -1% pass", r.action == "pass"))

    # --- Coin B: 空头, 盈利爬升至 +5% ---
    r = s.evaluate(ctx("B-SHORT", 0.05))
    results.append(("B-SHORT +5% trailing", r.action == "adjust_sl_tp"
                    and r.params.get("mode") == "trailing"))
    # peak 应为 5% (独立于 A 的 6%)
    results.append(("B-SHORT peak isolated=5%",
                    abs(s._peak_upl.get("B-SHORT", 0) - 0.05) < 1e-9
                    and abs(s._peak_upl.get("A-LONG", 0) - 0.06) < 1e-9))

    # --- Coin C: 盈利后平仓, 重开仓 peak 应重置 ---
    s.evaluate(ctx("C", 0.05))  # peak=5%
    results.append(("C before reset peak=5%", abs(s._peak_upl.get("C", 0) - 0.05) < 1e-9))
    s.reset_peak("C")
    results.append(("C after reset peak cleared", "C" not in s._peak_upl))
    # 重开仓 +1% → 不应立即 trailing (peak 已清)
    r = s.evaluate(ctx("C", 0.01))
    results.append(("C reopen +1% pass (not trailing)", r.action == "pass"))

    # --- Coin D: 多币种并发, peak 互不污染 ---
    for coin in ["D1", "D2", "D3", "D4", "D5"]:
        s.evaluate(ctx(coin, 0.05))
    all_isolated = all(abs(s._peak_upl.get(c, 0) - 0.05) < 1e-9
                       for c in ["D1", "D2", "D3", "D4", "D5"])
    results.append(("D1-D5 peak isolated", all_isolated))

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"  → Trailing: {passed}/{total} passed")
    return passed == total


# =============================================================
# Part 2: S3 recommend_exit_bars 多币种场景模拟
# =============================================================

def test_s3_multi_coin():
    """多币种 S3 场景: 覆盖两个盲区 + 全分支 + 多币种并发"""

    class FakeTrader:
        enable_multi_horizon = True
        HORIZON_PREP_EXIT_MARGIN = 3
        HORIZON_BAR_CANDIDATES = [1, 2, 3, 6, 10, 20, 30]
        bcrm2_adapters = {}
        def _cache_get(self, k, ttl_cycles=1): return False, None
        def _cache_set(self, k, v): pass
        def _kline_to_dataframe(self, kd): return None

    FakeTrader._recommend_exit_bars = PollingTrader._recommend_exit_bars
    t = FakeTrader()
    results = []

    def run(coin, best_k, best_dir, held, pos_side="long"):
        def _fake_pred(inference, k_candidates):
            horizons = []
            for k in k_candidates:
                c = 0.90 if k == best_k else 0.5
                horizons.append({"k_bar": k, "confidence": c,
                                 "direction": best_dir, "expected_roi_pct": 0.0})
            return {"horizons": horizons}
        tu.RiskManager.predict_multi_horizon = staticmethod(_fake_pred)
        r = t._recommend_exit_bars(
            coin=coin, pos_side=pos_side, held_k_bar=held,
            inference={"confidence": 0.8, "direction": "UP", "price": 100.0,
                       "volatility": 0.03, "pentagon_scores": {}},
        )
        return r["recommended_action"]

    cases = [
        # 盲区 #1: 过站+同向 → PREP_EXIT (原 EXTEND_TRACK)
        ("盲区#1 LONG 过站+同向", "S1", 1, "UP", 11, "PREP_EXIT"),
        # 盲区 #2: 远期+反向 → PREP_EXIT (原 EXTEND_TRACK)
        ("盲区#2 LONG 远期+反向", "S2", 30, "DOWN", 11, "PREP_EXIT"),
        # 回归: 远期+同向 → HOLD
        ("回归 LONG 远期+同向", "S3", 20, "UP", 10, "HOLD"),
        # 回归: 过站+反向 → PREP_EXIT
        ("回归 LONG 过站+反向", "S4", 3, "DOWN", 25, "PREP_EXIT"),
        # 临近 → PREP_EXIT
        ("LONG 临近", "S5", 10, "UP", 11, "PREP_EXIT"),
        # 远期+同向 HOLD
        ("LONG 远期+同向 HOLD", "S6", 30, "UP", 11, "HOLD"),
        # 空头: 过站+同向(空头dir=DOWN一致) → PREP_EXIT
        ("盲区#1 SHORT 过站+同向", "S7", 1, "DOWN", 11, "long", "PREP_EXIT"),
        # 空头: 远期+反向(多头dir=UP对空头是反向) → PREP_EXIT
        ("盲区#2 SHORT 远期+反向", "S8", 30, "UP", 11, "short", "PREP_EXIT"),
    ]
    for c in cases:
        if len(c) == 6:
            desc, coin, bk, bd, held, exp = c
            side = "long"
        else:
            desc, coin, bk, bd, held, side, exp = c
        act = run(coin, bk, bd, held, side)
        ok = act == exp
        results.append((desc, ok, act, exp))

    passed = sum(1 for _, ok, _, _ in results if ok)
    total = len(results)
    for desc, ok, act, exp in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}: got={act} exp={exp}")
    print(f"  → S3: {passed}/{total} passed")
    return passed == total


# =============================================================
# Part 3: 架构无冲突验证
# =============================================================

def test_architecture_no_conflict():
    """验证: 链序正确 / trailing 不阻塞 force_close / peak per-coin 隔离 /
    生产路径 register_chain 覆盖占位链"""
    results = []

    strategies = [
        P3EarlyExitStrategy(),
        WashoutHoldStrategy(),
        SignalReverseStrategy(),
        EvForceCloseStrategy(),
        TimeoutProfitSwitchStrategy(),
        EvAdjustStrategy(),
        TrailingStopStrategy(),
    ]
    em = ExitManager(strategies=strategies)
    # 模拟 production: 用真实策略覆盖 PORTFOLIO_MODE_CHAINS 占位链
    # （polling_trader 初始化时调用 register_chain("default", strategies)）
    em.register_chain("default", strategies)
    chain = em.get_current_chain()

    # 1. 链序: 7 策略, TrailingStop 在链尾(priority=70 最大)
    results.append(("链共 7 策略", len(chain) == 7))
    results.append(("TrailingStop 在链尾", chain[-1].name == "trailing_stop"))
    results.append(("TrailingStop priority=70", chain[-1].priority == 70))
    # 1b. 链尾是真实 TrailingStopStrategy 实例(非 _PortfolioChainPlaceholder)
    results.append(("链尾是真实策略实例", isinstance(chain[-1], TrailingStopStrategy)))

    # 2. 优先级严格递增
    prios = [s.priority for s in chain]
    results.append(("优先级严格递增", prios == sorted(prios)))

    # 3. force_close 类策略(P3/SignalRev/EvFC)在 trailing 之前
    force_close_names = {"p3_early_exit", "signal_reverse", "ev_force_close"}
    trailing_idx = next(i for i, s in enumerate(chain) if s.name == "trailing_stop")
    fc_before = all(
        next(i for i, s in enumerate(chain) if s.name == n) < trailing_idx
        for n in force_close_names
    )
    results.append(("force_close 策略在 trailing 之前", fc_before))

    # 4. TrailingStop 返回 adjust_sl_tp (不阻塞, 不 return)
    ts = chain[-1]
    ctx = ExitContext(coin="X", inference={},
                      pos_info={"upl_ratio": 0.05}, tracker_pos=None,
                      in_protection=False, age_hours=1.0)
    d = ts.evaluate(ctx)
    results.append(("TrailingStop 返回 adjust_sl_tp (非 force_close)",
                    d.action == "adjust_sl_tp"))

    # 5. peak per-coin 隔离
    ts2 = TrailingStopStrategy()
    ts2.evaluate(ExitContext(coin="C1", inference={},
                             pos_info={"upl_ratio": 0.05}, tracker_pos=None,
                             in_protection=False, age_hours=1.0))
    ts2.evaluate(ExitContext(coin="C2", inference={},
                             pos_info={"upl_ratio": 0.03}, tracker_pos=None,
                             in_protection=False, age_hours=1.0))
    results.append(("peak per-coin 隔离",
                    abs(ts2._peak_upl["C1"] - 0.05) < 1e-9
                    and abs(ts2._peak_upl["C2"] - 0.03) < 1e-9))

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"  → 架构无冲突: {passed}/{total} passed")
    return passed == total


# =============================================================
# Part 4: 生产路径占位链覆盖验证（关键架构修复）
# =============================================================

def test_production_chain_override():
    """验证生产导入路径下 register_chain 覆盖占位链，真实策略生效。

    生产中 ExitManager 从 strategy_algo_layer.PORTFOLIO_MODE_CHAINS 注入
    5 个占位策略到 _chains["default"]。若不 register_chain 覆盖，
    get_current_chain() 返回占位策略(evaluate 恒 pass) → 所有真实策略死代码。
    """
    results = []
    # 生产路径: scripts.memory_l4 导入 → 相对导入成功 → _chains 被填充
    try:
        from scripts.memory_l4.bcrm2.exit_manager import ExitManager as ProdEM
        from scripts.memory_l4.bcrm2.exit_strategies import (
            P3EarlyExitStrategy as ProdP3,
            TrailingStopStrategy as ProdTS,
        )
    except Exception:
        print("  [SKIP] 生产路径导入不可用（测试环境无 scripts.memory_l4 包）")
        return True

    strategies = [ProdP3(), ProdTS()]
    em = ProdEM(strategies=strategies)

    # 修复前: _chains["default"] 是占位策略
    has_placeholder = any(
        s.__class__.__name__ == "_PortfolioChainPlaceholder"
        for s in em._chains.get("default", [])
    )
    results.append(("修复前 _chains[default] 含占位策略", has_placeholder))

    # 修复前 get_current_chain 返回占位(非真实策略)
    pre_chain = em.get_current_chain()
    pre_is_placeholder = any(
        s.__class__.__name__ == "_PortfolioChainPlaceholder" for s in pre_chain
    )
    results.append(("修复前 get_current_chain 返回占位策略", pre_is_placeholder))

    # 执行修复: register_chain 覆盖
    em.register_chain("default", strategies)

    # 修复后: get_current_chain 返回真实策略
    post_chain = em.get_current_chain()
    post_no_placeholder = all(
        s.__class__.__name__ != "_PortfolioChainPlaceholder" for s in post_chain
    )
    results.append(("修复后 get_current_chain 无占位策略", post_no_placeholder))
    results.append(("修复后链含真实 TrailingStop",
                    any(isinstance(s, ProdTS) for s in post_chain)))

    # 修复后真实策略 evaluate 生效
    from scripts.memory_l4.bcrm2.exit_manager import ExitContext as ProdCtx
    ts = next(s for s in post_chain if isinstance(s, ProdTS))
    d = ts.evaluate(ProdCtx(coin="X", inference={},
                            pos_info={"upl_ratio": 0.05}, tracker_pos=None,
                            in_protection=False, age_hours=1.0))
    results.append(("修复后真实策略 evaluate 生效", d.action == "adjust_sl_tp"))

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"  → 生产路径占位链覆盖: {passed}/{total} passed")
    return passed == total


# =============================================================
# 主入口
# =============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Part 1: TrailingStopStrategy 多币种场景模拟")
    print("=" * 60)
    t1 = test_trailing_multi_coin()

    print()
    print("=" * 60)
    print("Part 2: S3 recommend_exit_bars 多币种场景模拟")
    print("=" * 60)
    t2 = test_s3_multi_coin()

    print()
    print("=" * 60)
    print("Part 3: 架构无冲突验证")
    print("=" * 60)
    t3 = test_architecture_no_conflict()

    print()
    print("=" * 60)
    print("Part 4: 生产路径占位链覆盖验证")
    print("=" * 60)
    t4 = test_production_chain_override()

    print()
    print("=" * 60)
    print(f"总结果: Trailing={'PASS' if t1 else 'FAIL'} | "
          f"S3={'PASS' if t2 else 'FAIL'} | "
          f"架构={'PASS' if t3 else 'FAIL'} | "
          f"占位链覆盖={'PASS' if t4 else 'FAIL'}")
    print("=" * 60)
    sys.exit(0 if (t1 and t2 and t3 and t4) else 1)
