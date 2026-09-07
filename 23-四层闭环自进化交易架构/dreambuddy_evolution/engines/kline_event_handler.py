"""
K线级事件触发器 (§1.8 频率分层硬约束)
替代每日 UTC 00:05 cron → K线收盘事件触发 L1/RippleEngine/Level0

频率分层:
- L1/RippleEngine/Level0 = 每K线收盘 (1h/4h/1d)
- L2 = 6h 批 (ESS 更新后)
- L3/ReflectionEngine = 每笔 close + 6h 批
- L4 = 每笔 close + 6h 批

FAIL-OPEN: crash → 返回 WAIT + 不崩溃
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class KlineEventHandler:
    """K线收盘事件处理器 — Phase 2 连续在线更新"""

    def __init__(
        self,
        mode: str = "MVP",
        build_position_callback: Any = None,
        settlement_bridge: Any = None,
        ripple_kwargs: dict | None = None,
        reflection_scanner: Any = None,
        project_root: str | None = None,
    ):
        """
        mode: "MVP" = 松耦合(Lark人工), "Phase2" = 紧耦合(自动推断+小仓)

        P2-S4b 参数:
        - build_position_callback: auto_execute=True 时调用的建仓回调
            签名: callback(symbol=, action=, u_open=, d_star=, confidence=)
        - settlement_bridge: TradeSettlementBridge 实例，用于持久化 pre_trade_snapshot
            None 时延迟创建默认实例
        - ripple_kwargs: 透传给 RippleEngine 的门槛参数
            如 {"vol_ratio_threshold": 1.3} 用于训练期放宽放量门槛
        - reflection_scanner: ReflectionScanner 实例（反思学习第二条起点）
            None 时根据 project_root 自动创建
        - project_root: 项目根目录，用于定位 all_trades.jsonl
        """
        self.mode = mode
        self._build_position_callback = build_position_callback
        self._bridge = settlement_bridge  # 延迟初始化
        self._reflection_scanner = reflection_scanner  # 反思学习起点
        self._project_root = project_root
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        from dreambuddy_evolution.core.level0_path_cost import compute_d_star
        from dreambuddy_evolution.engines.ripple_engine import RippleEngine
        self._rv = ResistanceVector()
        self._compute_d_star = compute_d_star
        self._ripple = RippleEngine(**(ripple_kwargs or {}))

    def _get_reflection_scanner(self):
        """延迟初始化 ReflectionScanner"""
        if self._reflection_scanner is None:
            try:
                from dreambuddy_evolution.engines.reflection_scanner import ReflectionScanner
                self._reflection_scanner = ReflectionScanner(project_root=self._project_root)
            except Exception as e:
                logger.warning("[FO] ReflectionScanner init fail: %s", e)
                self._reflection_scanner = False  # 标记为不可用，避免重复尝试
        return self._reflection_scanner or None

    def _get_bridge(self):
        """延迟初始化 TradeSettlementBridge（避免循环依赖 + 文件系统延迟）"""
        if self._bridge is None:
            from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
            self._bridge = TradeSettlementBridge()
        return self._bridge

    def _store_pre_trade_snapshot(self, symbol: str, action: str, d_star: str, ess_dir: str, ri: float, position_mult: float = 1.0) -> None:
        """P2-S4b: auto_execute 时存储 pre_trade_snapshot（FAIL-OPEN）"""
        try:
            from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
            snapshot = ReflectionEngine().create_snapshot(
                symbol=symbol,
                u_open=position_mult,  # 仓位乘数（而非固定 0.1）
                action=action,
                level0_dstar=d_star,
                ess_id="",
                ess_dir=ess_dir,
                cbr_sim=0.5,
                cbr_top1_outcome="TP",
                cluster_id="",
            )
            self._get_bridge().store_snapshot(symbol, snapshot)
        except Exception as e:
            logger.warning("[FO] store_pre_trade_snapshot crash: %s", e)

    def _trigger_build_position(self, symbol: str, action: str, d_star: str, ri: float, position_mult: float = 1.0, tier: str = "standard") -> None:
        """P2-S4b: 调用建仓回调（FAIL-OPEN）"""
        if self._build_position_callback is None:
            return
        try:
            self._build_position_callback(
                symbol=symbol,
                action=action,
                u_open=position_mult,  # 仓位乘数，由 tier 决定
                d_star=d_star,
                confidence=ri,
                tier=tier,  # 仓位层级：probe / standard / trend
            )
        except Exception as e:
            logger.warning("[FO] build_position_callback crash: %s", e)

    def on_kline_close(
        self,
        kline_data: dict[str, Any],
        alpha: float = 0.0,
        beta: float = 0.0,
        gamma: float = 0.0,
    ) -> dict[str, Any]:
        """
        K线收盘 → L1 R 向量 → 修饰子 → Level0 d* → RippleEngine RI

        输出:
        {
            "symbol": str,
            "r_vector": dict (9 字段),
            "d_star": "long"|"short"|"WAIT",
            "action": "long"|"short"|"WAIT",
            "ri": float [0,1],
            "modifiers_applied": bool,
            "auto_execute": bool (Phase2 only),
            "inference_formed": bool,
        }
        """
        try:
            symbol = str(kline_data.get("symbol", "UNKNOWN"))

            # ============ 1. L1 R 向量计算 ============
            r_vector = self._rv.calculate(symbol, kline_data)

            # ============ 2. 三修饰子应用 ============
            modifiers_applied = False
            if alpha > 0 or beta > 0 or gamma > 0:
                from dreambuddy_evolution.engines.modifiers import apply_all_modifiers
                sentiment = kline_data.get("sentiment")
                capital_flow = kline_data.get("capital_flow")
                narrative = kline_data.get("narrative")
                if any(v is not None for v in [sentiment, capital_flow, narrative]):
                    r_vector_mod = apply_all_modifiers(
                        {
                            "R_up": r_vector["R_up"],
                            "R_down": r_vector["R_down"],
                            "R_smooth": r_vector["R_smooth"],
                            "R_flow": r_vector["R_flow"],
                            "R_reflexivity": r_vector["R_reflexivity"],
                        },
                        sentiment=sentiment,
                        capital_flow=capital_flow,
                        narrative=narrative,
                        alpha=alpha,
                        beta=beta,
                        gamma=gamma,
                    )
                    # 覆盖原始值（保留 quality_score 等其他字段）
                    r_vector = {**r_vector, **r_vector_mod}
                    modifiers_applied = True

            # ============ 3. Level0 d* 计算 ============
            d_star_result = self._compute_d_star(r_vector)
            d_star = d_star_result["d_star"]

            # ============ 4. RippleEngine RI 检测（起点1：涟漪） ============
            ess_dir = str(kline_data.get("ess_top_direction", "")).lower()
            source = {
                "symbol": symbol,
                "r_vector": r_vector,
                "ess_top_direction": ess_dir,
                "vol_5": kline_data.get("vol_5", 0),
                "vol_20": kline_data.get("vol_20", 1e-9),
                "liq_index_change": kline_data.get("liq_index_change", 0),
                "scale_class": kline_data.get("scale_class", ""),
            }
            is_source = self._ripple.detect_ripple_source(source)
            ripple_ri = self._ripple.compute_ri(kline_data.get("ripples", {})) if is_source else 0.50

            # ============ 4b. ReflectionScanner（起点2：反思学习） ============
            # 从交易记录库统计该币种历史胜率，高胜率币种降低涟漪门槛
            reflection_ri = 0.50
            reflection_eligible = False
            try:
                scanner = self._get_reflection_scanner()
                if scanner is not None:
                    stats = scanner.get_coin_stats(symbol)
                    reflection_eligible = stats.get("eligible", False)
                    reflection_ri = stats.get("reflection_ri", 0.50)
            except Exception as e:
                logger.debug("[FO] reflection_scan fail: %s", e)

            # 双起点取 max：涟漪 OR 反思学习
            ri = max(ripple_ri, reflection_ri)
            signal_source = "ripple" if ripple_ri >= reflection_ri else "reflection"

            # ============ 5. 推断 + 动作（三层仓位分级） ============
            # 层级1: 轻仓试探  0.40 ≤ ri < 0.55  → position_mult=0.4（类似 WEAK 档）
            # 层级2: 标准仓      0.55 ≤ ri < 0.70  → position_mult=0.7（类似 NORMAL 档）
            # 层级3: 趋势加仓    ri ≥ 0.70         → position_mult=1.0（类似 STRONG 档）
            # 对齐易经系统弹簧力场分层，适配震荡（小仓试探）/趋势（标准+加仓）多种形态

            # 获取 regime 仓位乘数（来自 DataPipeline 装配的市场状态）
            regime = str(kline_data.get("regime", "")).upper()
            # regime → position_mult 映射（对齐易经 REGIME_MULTIPLIERS）
            _regime_position_mult = 1.0
            if regime in ("TREND_UP_STRONG", "STRONG_TREND_BULL"):
                _regime_position_mult = 1.20
            elif regime in ("TREND_UP_MILD", "TREND_BULL"):
                _regime_position_mult = 1.05
            elif regime in ("BREAKOUT",):
                _regime_position_mult = 1.10
            elif regime in ("RANGE_BOUND", "RANGING"):
                _regime_position_mult = 0.80
            elif regime in ("CONSOLIDATION", "MEAN_REVERTING"):
                _regime_position_mult = 0.70
            elif regime in ("VOLATILE_DROP", "STRONG_TREND_BEAR"):
                _regime_position_mult = 0.35
            elif regime in ("REVERSAL", "TREND_BEAR"):
                _regime_position_mult = 0.50

            # 三层仓位分级
            PROBE_THRESHOLD = 0.40   # 轻仓试探门槛
            STANDARD_THRESHOLD = 0.55  # 标准仓门槛
            TREND_THRESHOLD = 0.70    # 趋势加仓门槛

            if ri >= TREND_THRESHOLD:
                tier = "trend"
                base_position_mult = 1.0
            elif ri >= STANDARD_THRESHOLD:
                tier = "standard"
                base_position_mult = 0.7
            elif ri >= PROBE_THRESHOLD:
                tier = "probe"
                base_position_mult = 0.4
            else:
                tier = "none"
                base_position_mult = 0.0

            # 最终仓位乘数 = 基础层级 × regime 乘数
            position_mult = base_position_mult * _regime_position_mult

            inference_formed = ri >= PROBE_THRESHOLD  # 轻仓试探也视为推断形成
            action = "WAIT"
            auto_execute = False

            if inference_formed and d_star in ("long", "short"):
                aligned = (d_star == ess_dir) if ess_dir else True
                if aligned:
                    action = d_star
                    if self.mode == "Phase2":
                        auto_execute = True
                        # P2-S4b: 存储 pre_trade_snapshot + 触发真实建仓回调
                        self._store_pre_trade_snapshot(symbol, action, d_star, ess_dir, ri, position_mult)
                        self._trigger_build_position(symbol, action, d_star, ri, position_mult, tier)
                    # MVP 模式: 不自动执行 (Lark 人工中转)
                    if self.mode == "MVP" and ri >= 0.75:
                        pass

            return {
                "symbol": symbol,
                "r_vector": r_vector,
                "d_star": d_star,
                "action": action,
                "ri": ri,
                "ripple_ri": ripple_ri,
                "reflection_ri": reflection_ri,
                "reflection_eligible": reflection_eligible,
                "signal_source": signal_source,
                "tier": tier,
                "position_mult": round(position_mult, 4),
                "regime": regime,
                "regime_position_mult": round(_regime_position_mult, 4),
                "modifiers_applied": modifiers_applied,
                "auto_execute": auto_execute,
                "inference_formed": inference_formed,
                "is_ripple_source": is_source,
            }

        except Exception as e:
            logger.warning("[FO] on_kline_close crash: %s", e)
            return {
                "symbol": str(kline_data.get("symbol", "UNKNOWN")),
                "r_vector": {},
                "d_star": "WAIT",
                "action": "WAIT",
                "ri": 0.50,
                "ripple_ri": 0.50,
                "reflection_ri": 0.50,
                "reflection_eligible": False,
                "signal_source": "none",
                "modifiers_applied": False,
                "auto_execute": False,
                "inference_formed": False,
                "is_ripple_source": False,
            }
