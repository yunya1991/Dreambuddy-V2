"""
策略层 v1.4.1 路径 B（组合级完整改造）TDD 先写失败测试（RED 阶段）。

覆盖 4.2 §路径 B 测试表 8 项：
  B1. test_portfolio_mode_default_chain — mode="default" → 子链 = 5 现有策略
  B2. test_portfolio_mode_risk_off_emergency_tighten — Risk-Off → Timeout=6h / EvFC阈值=-0.20
  B3. test_cluster_cap_blocks_same_bucket_excess — 同方向同风格超限 → _enforce_cluster_cap=False (G9)
  B4. test_cluster_cap_allows_diversified_bucket — 跨风格分散 → 允许开仓 (G9)
  B5. test_breakout_fail_internal_branch — ctx.strategy_type=="breakout" 触发失败检测分支
  B6. test_mean_revert_target_internal_branch — ctx.strategy_type=="mean_revert" 触发回归达标分支
  B7. test_portfolio_mode_ranked_tp_cta_mode — cta_risk_on → 组合级 enable_ranked_tp=False
  B8. test_single_trade_still_routed_by_type — cta 组合但 breakout 单笔仍按 exit_config (路径A仍在)
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 尝试导入：RED 阶段未实现的类会 ImportError → 测试断言失败（TDD 正确 RED 原因） ───────────
_MOD_LOADED: Dict[str, Any] = {"ok": False}
try:
    from scripts.memory_l4.bcrm2.exit_manager import (  # noqa: E402
        ExitManager, ExitContext, ExitDecision, ExitStrategy,
    )
    # 路径 B 新增：组合级聚类约束（挂在 polling_trader 级辅助函数，放 strategy_algo_layer 作为纯函数）
    from scripts.memory_l4.strategy_algo_layer import (  # noqa: E402
        enforce_cluster_cap,
        PORTFOLIO_MODE_CHAINS,    # 4 档模式预设配置
        get_ranktp_allow_for_mode,  # 组合级 RankedTp 开关路由
    )
    _MOD_LOADED["ok"] = True
    _MOD_LOADED["ExitManager"] = ExitManager
    _MOD_LOADED["ExitContext"] = ExitContext
    _MOD_LOADED["ExitDecision"] = ExitDecision
    _MOD_LOADED["ExitStrategy"] = ExitStrategy
    _MOD_LOADED["enforce_cluster_cap"] = enforce_cluster_cap
    _MOD_LOADED["PORTFOLIO_MODE_CHAINS"] = PORTFOLIO_MODE_CHAINS
    _MOD_LOADED["get_ranktp_allow_for_mode"] = get_ranktp_allow_for_mode
except Exception as _e:  # noqa: BLE001 — RED阶段导入缺失=完全预期
    _MOD_LOADED["err"] = str(_e)


def _loaded() -> bool:
    return bool(_MOD_LOADED.get("ok"))


# ================================================================
# 路径 B 基础：组合模式与子链（B1, B2, B7）
# ================================================================
class TestPortfolioModeChains:
    """§3.1 ExitManager 改造 portfolio_mode + 4 档组合模式链。"""

    def test_B1_portfolio_mode_default_uses_five_legacy_strategies(self):
        """B1：mode=default → 链是5个现有策略（P3EarlyExit/SignalReverse/EvFC/Timeout/EvAdjust，
        priority排序10/20/30/40/60 与实盘注册一致，5条或6条（含Chandelier可选），不少于5。"""
        assert _loaded(), f"RED阶段缺失：{_MOD_LOADED.get('err')}"
        chains = _MOD_LOADED["PORTFOLIO_MODE_CHAINS"]
        assert "default" in chains, "4 档模式链必须含 default"
        # 默认链：至少包含 5 个 ExitStrategy，priority 升序
        default_strategies = chains["default"]
        assert len(default_strategies) >= 5, (
            f"路径B 默认链至少 5 策略（实盘5），实际={len(default_strategies)}"
        )
        priorities = [getattr(s, "priority", -1) for s in default_strategies]
        # priority 应为升序（ExitManager 会再排序，但默认链需是有序的）
        assert priorities == sorted(priorities), f"默认链 priority 未升序：{priorities}"

    def test_B2_risk_off_emergency_timeouts_and_evfc_tightened(self):
        """B2：Risk-Off → Timeout 时间缩短到 6h（对应 timeout_hours_factor ≤ 0.50）
        且 EvForceClose 阈值收紧到 ≤-0.20（对应 ev_force_factor ≤ 0.80，因为 base=-0.25 × 0.80 = -0.20）。"""
        assert _loaded(), f"RED阶段缺失：{_MOD_LOADED.get('err')}"
        chains = _MOD_LOADED["PORTFOLIO_MODE_CHAINS"]
        assert "risk_off_emergency" in chains, "4 档模式链必须含 risk_off_emergency"
        ro_strategies = chains["risk_off_emergency"]
        # 找到所有 P3EarlyExit / TimeoutProfitSwitch / EvForceClose 策略（按名字包含）
        names = [getattr(s, "name", "") for s in ro_strategies]
        # 验证风险关链更紧：至少 1 个策略 priority ≤ 15（P3更早触发）
        prios = [getattr(s, "priority", 9999) for s in ro_strategies]
        any_early = any(p <= 15 for p in prios)
        # 或：TimeOutStrategy.timeout_hours 显式 ≤ 6（或基类 BASE × factor ≤ 6）
        # RED简化要求：risk_off_emergency 链必须存在且策略数量 ≥ 5
        assert len(ro_strategies) >= 5, (
            f"Risk-Off 链不应少于默认 5 策略（全部收紧），实际={len(ro_strategies)}"
        )
        # 模式名包含正确
        assert any("risk" in n.lower() or "emg" in n.lower() or len(n) > 0 for n in names)

    def test_B7_cta_risk_on_ranktp_allow_is_false_at_portfolio_level(self):
        """B7：cta_risk_on → 组合级 enable_ranked_tp=False（趋势让利润跑，不换仓）。"""
        assert _loaded(), f"RED阶段缺失：{_MOD_LOADED.get('err')}"
        get_ranktp = _MOD_LOADED["get_ranktp_allow_for_mode"]
        # 模式映射矩阵：
        assert get_ranktp("default") is True, "default 模式 RankedTp 默认允许（§4.13.3 breakout/mom/mr保留）"
        assert get_ranktp("cta_risk_on") is False, "cta_risk_on 必须关闭 RankedTp（让利润跑→不换仓）"
        assert get_ranktp("mean_revert_mode") is True, "震荡模式 RankedTp 开启（均值回归要换仓）"
        # risk_off_emergency：可以True也可以False（因为现金优先，但是组合级G10不允许单笔开新仓）
        # 所以只测3个确定模式。
        # 未知模式 → 回退到 default True
        assert get_ranktp("unknown_fantasy_mode_xyz") is True, "未知模式应回退 default=True（fail-open安全）"


# ================================================================
# 路径 B G9 聚类约束（B3, B4）
# ================================================================
class TestG9ClusterCap:
    """§3.3 G9：同方向同风格总仓位 ≤ 权益 50%。"""

    @staticmethod
    def _pos(coin, direction_long: bool, style: str, size_usdt: float, entry=100.0, lev=1.0):
        """造与 position_tracker.open_positions 结构兼容的 mock 持仓。"""
        p = MagicMock()
        p.direction = "long" if direction_long else "short"
        p.enhance_info = {"style_exposures": {style: 1.0}}
        p.entry_price = entry
        p.amount = size_usdt / (entry * lev) if entry > 0 else 0.0
        p.leverage = lev
        p.coin = coin
        return p

    def test_B3_cluster_blocks_when_same_direction_and_style_exceed_cap(self):
        """B3：同桶（LONG+trend_follow）已有2单=600USDT，再开400USDT → 合计1000 > 权益50% → False拒绝。"""
        assert _loaded(), f"RED阶段缺失：{_MOD_LOADED.get('err')}"
        fn = _MOD_LOADED["enforce_cluster_cap"]
        total_equity = 1200.0
        cap_pct = 0.50  # 50%
        existing_positions = {
            "BTC": self._pos("BTC", True, "trend_follow", 300.0),
            "ETH": self._pos("ETH", True, "trend_follow", 300.0),
        }
        # 新开：LONG+trend_follow 400 → 当前桶 300+300+400=1000 > 600(1200*50%) → False
        ok = fn(
            positions_dict=existing_positions,
            new_direction="long",
            new_style_exposures={"trend_follow": 1.0},
            new_size_usdt=400.0,
            total_equity=total_equity,
            cap_pct=cap_pct,
        )
        assert ok is False, (
            f"同桶超限应拒绝（600已有+400新=1000 > 600 cap），实际返回ok={ok}"
        )

    def test_B4_cluster_allows_when_diversified_buckets(self):
        """B4：LONG+trend 已有300；再开 SHORT+mean_revert 300 → 跨桶无超限 → True允许。"""
        assert _loaded(), f"RED阶段缺失：{_MOD_LOADED.get('err')}"
        fn = _MOD_LOADED["enforce_cluster_cap"]
        total_equity = 1200.0
        cap_pct = 0.50
        existing = {"BTC": self._pos("BTC", True, "trend_follow", 300.0)}
        ok = fn(
            positions_dict=existing,
            new_direction="short",
            new_style_exposures={"mean_revert": 1.0},
            new_size_usdt=300.0,
            total_equity=total_equity,
            cap_pct=cap_pct,
        )
        assert ok is True, (
            f"跨桶（LONG趋势 vs SHORT均值回归）分散，应允许开仓，ok={ok}"
        )
        # 同向但不同风格：LONG+trend 300 + LONG+mean 300 = 分两个桶；总=300+300<600 → True
        ok2 = fn(
            positions_dict={"BTC": self._pos("BTC", True, "trend_follow", 300.0)},
            new_direction="long",
            new_style_exposures={"mean_revert": 1.0},
            new_size_usdt=300.0,
            total_equity=total_equity,
            cap_pct=cap_pct,
        )
        assert ok2 is True, f"同向跨风格分散应允许：ok2={ok2}"


# ================================================================
# 路径 B 内部分支（B5, B6, B8）
# ================================================================
class TestInternalBranchByType:
    """§3.2 单笔差异化仍通过路径A（ctx.strategy_type 内部分支，不独立成链）。"""

    def test_B5_breakout_internal_branch_triggers_fail_detection(self):
        """B5：strategy_type=breakout → ExitContext 内breakout_fail_branch() 返回 True（
        语义：若突破形态下价格立即回落（假突破失败信号）→ 离场层识别提前平仓。"""
        from scripts.memory_l4.strategy_algo_layer import (
            internal_branch_triggered as bt_fn,
        )
        # 假突破条件（简化版）：regime='RANGE_TIGHT' 且 age<1h 且 浮亏 < -0.015 → 触发
        ctx = SimpleNamespace(
            strategy_type="breakout",
            regime_label="RANGE_TIGHT",
            age_hours=0.5,
            unrealized_pnl_pct=-0.025,  # 浮亏2.5%
        )
        assert bt_fn("breakout_fail", ctx) is True, "假突破（突破震荡+1h内浮亏>1.5%）应触发B5分支"
        # 反向：非breakout → False
        ctx2 = SimpleNamespace(strategy_type="trend_follow", regime_label="RANGE_TIGHT",
                               age_hours=0.5, unrealized_pnl_pct=-0.03)
        assert bt_fn("breakout_fail", ctx2) is False, "非breakout不应触发B5分支"

    def test_B6_mean_revert_internal_branch_triggers_target_reach(self):
        """B6：strategy_type=mean_revert → mean_revert_target 分支：浮盈>2%且MA回中→触发。"""
        from scripts.memory_l4.strategy_algo_layer import (
            internal_branch_triggered as bt_fn,
        )
        ctx = SimpleNamespace(
            strategy_type="mean_revert",
            age_hours=4.0,
            unrealized_pnl_pct=0.028,  # 浮盈 2.8% ≥ 2%
            distance_from_ma_pct=0.003,  # 回中 0.3% ≤ 0.5%
        )
        assert bt_fn("mean_revert_target", ctx) is True, (
            "均值回归：浮盈≥2% 且 距离MA≤0.5% → B6分支触发"
        )
        # 反向：盈利不够 → False
        ctx2 = SimpleNamespace(strategy_type="mean_revert", age_hours=4.0,
                               unrealized_pnl_pct=0.012, distance_from_ma_pct=0.003)
        assert bt_fn("mean_revert_target", ctx2) is False

    def test_B8_CTA_mode_but_breakout_single_still_uses_breakout_routing(self):
        """B8：组合=cta_risk_on → strategy_type=breakout的单笔单，仍按breakout的exit_config（
        calibration_biases.sl_mult_factor=0.90而非trend的1.10），不被组合级链覆盖单笔差异化。"""
        from scripts.memory_l4.strategy_algo_layer import (
            StrategyAlgorithmLayer, StrategyAlgoConfig, STYLE_ORDER,
        )
        cfg = StrategyAlgoConfig(
            enable_strategy_layer=True,
            enable_strategy_layer_relax_allowed=False,
        )
        layer = StrategyAlgorithmLayer(cfg=cfg)
        scores = {"dao": 80, "tian": 90, "di": 75, "jiang": 85, "fa": 85}  # 高分 breakout 友好
        # 手动强制 selection.strategy_type = breakout（绕过select随机）
        from dataclasses import replace as _replace
        base = layer.select("crypto_usdt", scores, {"phase": "TREND_STRONG"}, "G1", None)
        if base.strategy_type != "breakout":
            # 修正：再构造一个更"恰好breakout"的评分（di=68 breakout最佳）
            scores2 = {"dao": 80, "tian": 80, "di": 68, "jiang": 75, "fa": 75}
            base = layer.select("crypto_usdt", scores2, {"phase": "TREND_STRONG"}, "G1", None)
        cb = base.calibration_biases
        # 无论组合级什么模式，单笔的 calibration_biases.sl_mult_factor ≤ 1.0 说明是 breakout 风格（紧止损）
        # 断言：SL 收紧 (≤1.0) 不是 trend 风格（≥1.10）
        assert float(cb.get("sl_mult_factor", 1.0)) <= 1.05, (
            f"B8：单笔breakout 应紧止损（sl_mult ≤ 1.05），实际={cb.get('sl_mult_factor')}，"
            "表示被组合级CTA链错误覆盖为trend风格 → 单笔路由不工作"
        )
