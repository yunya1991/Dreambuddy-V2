"""
K线级事件触发器 (Facade) — P1-2 拆分后

P1-2 拆分委托给:
  - EngineRouter: AGI增强 + 懒加载 getters + 路径发现层
  - EventReceiver: L1 R向量 + AGI-A签名 + 事件驱动状态
  - ResultAggregator: 建仓回调 + 宏观过滤 + L3/L4反馈

频率分层:
- L1/RippleEngine/Level0 = 每K线收盘 (1h/4h/1d)
- L2 = 6h 批 (ESS 更新后)
- L3/ReflectionEngine = 每笔 close + 6h 批
- L4 = 每笔 close + 6h 批

FAIL-OPEN: crash → 返回 WAIT + 不崩溃
"""
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Phase 1: 事件驱动策略模块级导入（支持测试 monkeypatch）
try:
    from event_driven import EventDrivenStrategy  # type: ignore[import]
except ImportError:  # event_driven 包不在 sys.path 时
    EventDrivenStrategy = None  # type: ignore[assignment]


class KlineEventHandler:
    """K线收盘事件处理器 — Phase 2 连续在线更新 (Facade)"""

    def __init__(
        self,
        mode: str = "MVP",
        build_position_callback: Any = None,
        settlement_bridge: Any = None,
        ripple_kwargs: dict | None = None,
        reflection_scanner: Any = None,
        project_root: str | None = None,
        pipeline: Any = None,
    ):
        """
        mode: "MVP" = 松耦合(Lark人工), "Phase2" = 紧耦合(自动推断+小仓)

        P2-S4b 参数:
        - build_position_callback: auto_execute=True 时调用的建仓回调
        - settlement_bridge: TradeSettlementBridge 实例
        - ripple_kwargs: 透传给 RippleEngine 的门槛参数
        - reflection_scanner: ReflectionScanner 实例
        - project_root: 项目根目录
        - pipeline: Phase 4 P0-2 DI 注入
        """
        self.mode = mode
        self._build_position_callback = build_position_callback
        self._bridge = settlement_bridge
        self._pipeline = pipeline
        self._project_root = project_root

        from dreambuddy_evolution.core.resistance_vector import ResistanceVector
        from dreambuddy_evolution.core.level0_path_cost import compute_d_star
        from dreambuddy_evolution.engines.ripple_engine import RippleEngine
        from dreambuddy_evolution.engines.engine_router import EngineRouter
        from dreambuddy_evolution.engines.event_receiver import EventReceiver
        from dreambuddy_evolution.engines.result_aggregator import ResultAggregator

        self._rv = ResistanceVector()
        self._compute_d_star = compute_d_star
        self._ripple = RippleEngine(**(ripple_kwargs or {}))

        # P1-2: 创建拆分组件（共享同一个 EngineRouter）
        self._router = EngineRouter()
        self._router._project_root = project_root
        self._router._reflection_scanner = reflection_scanner
        self._receiver = EventReceiver(mode=mode, router=self._router)
        self._aggregator = ResultAggregator(
            build_position_callback=build_position_callback,
            settlement_bridge=settlement_bridge,
            pipeline=pipeline,
            router=self._router,
        )

        # 向后兼容实例变量（旧测试引用）
        self._reflection_scanner = reflection_scanner
        self._trader: Any = None
        self._last_agi_pattern: dict | None = None
        self._last_dimension_predictions: dict = {}
        self._sig_engine: Any = None
        self._pattern_detector: Any = None
        self._regime_classifier: Any = None
        self._path_integral_engine: Any = None
        self._uncertainty_quant: Any = None
        self._meta_cognition_gate: Any = None
        self._evolution_pipeline: Any = None
        self._subsystem_bridge: Any = None
        self._event_driven_strategy: Any = None
        self._path_layer_enabled: bool = False

    # ==================================================================
    # 委托方法 — EngineRouter
    # ==================================================================

    def _agi_enhance(self, switch: str, fn: Any, fallback: Any, **kw: Any) -> Any:
        return self._router.agi_enhance(switch, fn, fallback, **kw)

    def _get_sig_engine(self) -> Any:
        return self._router.get_sig_engine()

    def _get_pattern_detector(self) -> Any:
        return self._router.get_pattern_detector()

    def _get_regime_classifier(self) -> Any:
        return self._router.get_regime_classifier()

    def _get_path_integral_engine(self) -> Any:
        return self._router.get_path_integral_engine()

    def _get_uncertainty_quant(self) -> Any:
        return self._router.get_uncertainty_quant()

    def _get_meta_cognition_gate(self) -> Any:
        return self._router.get_meta_cognition_gate()

    def _get_evolution_pipeline(self) -> Any:
        return self._router.get_evolution_pipeline()

    def _get_event_driven_strategy(self) -> Any:
        return self._router.get_event_driven_strategy()

    def _get_subsystem_bridge(self) -> Any:
        return self._router.get_subsystem_bridge()

    def _get_reflection_scanner(self) -> Any:
        return self._router.get_reflection_scanner()

    def _get_bridge(self) -> Any:
        return self._aggregator._get_bridge()

    # ==================================================================
    # 委托方法 — EventReceiver
    # ==================================================================

    def _write_event_driven_state(self, kline_data: dict, result: dict) -> None:
        self._receiver.write_event_driven_state(kline_data, result)

    # ==================================================================
    # 委托方法 — ResultAggregator
    # ==================================================================

    def attach_trader(self, trader: Any) -> None:
        self._trader = trader
        self._router.attach_trader(trader)
        self._aggregator.attach_trader(trader)

    def _store_pre_trade_snapshot(self, symbol: str, action: str, d_star: str,
                                  ess_dir: str, ri: float,
                                  position_mult: float = 1.0) -> None:
        self._aggregator.store_pre_trade_snapshot(
            symbol, action, d_star, ess_dir, ri, position_mult
        )

    def _trigger_build_position(self, symbol: str, action: str, d_star: str,
                                ri: float, position_mult: float = 1.0,
                                tier: str = "standard",
                                source_tag: str | None = None) -> None:
        self._aggregator.trigger_build_position(
            symbol, action, d_star, ri, position_mult, tier, source_tag
        )

    def _apply_macro_event_filter(
        self, kline_data: dict[str, Any], d_star: str, ri: float
    ) -> tuple[str | None, float, dict[str, Any]]:
        # 旧签名: (kline_data, d_star, ri) → 委托 aggregator 保持兼容
        return self._aggregator.apply_macro_event_filter(
            kline_data=kline_data, action=d_star, d_star=d_star, ri=ri
        )

    def get_evolution_feedback(self) -> dict[str, Any]:
        return self._aggregator.get_evolution_feedback()

    def _run_path_discovery(
        self, symbol: str, r_vector: dict[str, Any],
        d_star: str, ri: float, kline_data: dict[str, Any],
    ) -> tuple[str, float, dict[str, Any]]:
        """路径发现层 — 委托给 EngineRouter 并适配返回格式."""
        # 转发 handler 级状态到 router（测试兼容：测试直接设 handler._evolution_pipeline）
        if self._evolution_pipeline is not None:
            self._router._evolution_pipeline = self._evolution_pipeline
        if self._path_layer_enabled:
            self._router._path_layer_enabled = self._path_layer_enabled
        self._router._trader = self._trader

        result = self._router.run_path_discovery(
            symbol=symbol, d_star=d_star, r_vector=r_vector,
            kline_data=kline_data, mode=self.mode, ri=ri,
            event_driven_strategy_cls=EventDrivenStrategy,  # 模块级变量（支持测试 monkeypatch）
        )
        self._last_dimension_predictions = self._router._last_dimension_predictions
        return (
            result.get("d_star_adjusted", d_star),
            result.get("ri_adjusted", ri),
            result,
        )

    # ==================================================================
    # 主链路
    # ==================================================================

    def on_kline_close(
        self,
        kline_data: dict[str, Any],
        alpha: float = 0.0,
        beta: float = 0.0,
        gamma: float = 0.0,
    ) -> dict[str, Any]:
        """K线收盘 → L1 R 向量 → 修饰子 → Level0 d* → RippleEngine RI."""
        try:
            # 同步 handler 级 AGI 状态到 router（测试兼容：测试直接设 handler._sig_engine 等）
            for _a in ("_sig_engine", "_pattern_detector", "_regime_classifier",
                       "_path_integral_engine", "_uncertainty_quant", "_meta_cognition_gate"):
                _v = getattr(self, _a, None)
                if _v is not None:
                    setattr(self._router, _a, _v)

            symbol = str(kline_data.get("symbol", "UNKNOWN"))

            # ============ 1. L1 R 向量 + AGI-A 签名 ============
            recv = self._receiver.receive_kline(kline_data, self._rv)
            r_vector = recv["r_vector"]
            agi_signature = recv["agi_signature"]

            # ============ AGI 增强点 B: PathIntegralEngine 蒙特卡洛路径复核 ============
            agi_path_integral = None
            try:
                closes_raw = kline_data.get("close", [])
                if isinstance(closes_raw, (list, np.ndarray)) and len(closes_raw) >= 10:
                    pi_engine = self._get_path_integral_engine()
                    if pi_engine is not None:
                        closes_arr = np.array(closes_raw, dtype=float)
                        start_price = float(closes_arr[-1])
                        rets = np.diff(closes_arr) / np.maximum(closes_arr[:-1], 1e-9)
                        vol = max(float(np.std(rets)) if len(rets) >= 2 else 0.02, 0.001)
                        horizon = min(len(closes_arr), 20)

                        def _run_path_integral():
                            paths = pi_engine.sample_paths(
                                start_price=start_price, horizon=horizon,
                                volatility=vol, drift=0.0,
                            )
                            best_idx, best_action = pi_engine.find_least_resistance_path(paths)
                            exp_path = pi_engine.expected_path(paths, temperature=1.0)
                            return {
                                "n_paths": len(paths), "horizon": horizon,
                                "volatility": round(vol, 6),
                                "min_resistance_action": round(float(best_action), 6),
                                "expected_end_price": round(float(exp_path[-1]), 6),
                                "start_price": round(start_price, 6),
                            }
                        agi_path_integral = self._agi_enhance(
                            "enable_path_integral", fn=_run_path_integral, fallback=None,
                        )
            except Exception as e:
                logger.debug("[FO-AGI-B] path_integral fail: %s", e)

            # ============ 2. 三修饰子应用 ============
            modifiers_applied = False
            if alpha > 0 or beta > 0 or gamma > 0:
                from dreambuddy_evolution.engines.modifiers import apply_all_modifiers
                sentiment = kline_data.get("sentiment")
                capital_flow = kline_data.get("capital_flow")
                narrative = kline_data.get("narrative")
                if any(v is not None for v in [sentiment, capital_flow, narrative]):
                    r_vector_mod = apply_all_modifiers(
                        {"R_up": r_vector["R_up"], "R_down": r_vector["R_down"],
                         "R_smooth": r_vector["R_smooth"], "R_flow": r_vector["R_flow"],
                         "R_reflexivity": r_vector["R_reflexivity"]},
                        sentiment=sentiment, capital_flow=capital_flow, narrative=narrative,
                        alpha=alpha, beta=beta, gamma=gamma,
                    )
                    r_vector = {**r_vector, **r_vector_mod}
                    modifiers_applied = True

            # ============ 3. Level0 d* 计算 ============
            d_star_result = self._compute_d_star(r_vector)
            d_star = d_star_result["d_star"]

            # ============ 3b. 路径发现层 ============
            path_info: dict[str, Any] = {
                "path_count": 0, "optimal_source": None, "optimal_score": 0.0,
                "validated": False, "low_conviction": False,
                "d_star_original": d_star, "d_star_adjusted": d_star,
                "primary_contradiction": None,
            }
            try:
                if (r_vector and r_vector.get("R_up") is not None
                        and r_vector.get("R_down") is not None):
                    if d_star in ("long", "short"):
                        d_star, ri_path_adjusted, path_info = self._run_path_discovery(
                            symbol, r_vector, d_star, 0.5, kline_data
                        )
                    elif d_star == "WAIT":
                        _, _, _ = self._run_path_discovery(
                            symbol, r_vector, "neutral", 0.5, kline_data
                        )
            except Exception as e:
                logger.debug("[PathLayer] %s outer crash: %s", symbol, e)

            # ============ 4. RippleEngine RI 检测 ============
            ess_dir = str(kline_data.get("ess_top_direction", "")).lower()
            source = {
                "symbol": symbol, "r_vector": r_vector,
                "ess_top_direction": ess_dir,
                "vol_5": kline_data.get("vol_5", 0),
                "vol_20": kline_data.get("vol_20", 1e-9),
                "liq_index_change": kline_data.get("liq_index_change", 0),
                "scale_class": kline_data.get("scale_class", ""),
            }
            is_source = self._ripple.detect_ripple_source(source)
            ripple_ri = self._ripple.compute_ri(kline_data.get("ripples", {})) if is_source else 0.50

            # ============ 4b. ReflectionScanner ============
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

            ri = max(ripple_ri, reflection_ri)
            signal_source = "ripple" if ripple_ri >= reflection_ri else "reflection"

            # ============ AGI 增强点 C: UncertaintyQuantifier ============
            agi_uncertainty = None
            try:
                uq_inst = self._get_uncertainty_quant()
                if uq_inst is not None:
                    ensemble_std = abs(ripple_ri - reflection_ri)
                    feature_noise = max(0.0, 1.0 - ri)
                    agi_uncertainty = self._agi_enhance(
                        "enable_uncertainty_quant", fn=uq_inst.quantify_uncertainty,
                        fallback=None, prediction=ri, ensemble_std=ensemble_std,
                        conformal_width=None, feature_noise=feature_noise,
                    )
            except Exception as e:
                logger.debug("[FO-AGI-C] uncertainty fail: %s", e)

            # ============ AGI 增强点 D: MetaCognitionGate ============
            agi_gate_decision = None
            try:
                mcg_inst = self._get_meta_cognition_gate()
                if mcg_inst is not None and agi_uncertainty is not None:
                    unc_score = agi_uncertainty.get("uncertainty_score", 0.5)
                    agi_gate_decision = self._agi_enhance(
                        "enable_meta_cognition", fn=mcg_inst.gate_decision,
                        fallback=None, uncertainty_score=unc_score,
                        base_confidence=ri, strategy_sharpe=None, position_size=1.0,
                    )
            except Exception as e:
                logger.debug("[FO-AGI-D] gate_decision fail: %s", e)

            # ============ 5. 推断 + 动作（三层仓位分级） ============
            regime = str(kline_data.get("regime", "")).upper()
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

            PROBE_THRESHOLD = 0.50
            STANDARD_THRESHOLD = 0.60
            TREND_THRESHOLD = 0.70

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

            position_mult = base_position_mult * _regime_position_mult

            # ============ AGI 增强点 E: PatternDetector + RegimeClassifier ============
            agi_pattern = None
            agi_btc_regime = None
            try:
                closes_raw = kline_data.get("close", [])
                if isinstance(closes_raw, (list, np.ndarray)) and len(closes_raw) >= 30:
                    pd_inst = self._get_pattern_detector()
                    if pd_inst is not None:
                        klines_for_pattern = [{"close": float(c)} for c in closes_raw]
                        agi_pattern = self._agi_enhance(
                            "enable_pattern_detection",
                            fn=pd_inst.bcrm_technical_assessment,
                            fallback=None, klines=klines_for_pattern,
                        )
                        if agi_pattern and agi_pattern.get("is_reversal_signal"):
                            logger.info(
                                "[AGI-E] %s pattern=%s dir=%s conf=%.2f factor=%.2f",
                                symbol, agi_pattern.get("pattern"),
                                agi_pattern.get("direction"),
                                agi_pattern.get("confidence", 0),
                                agi_pattern.get("pattern_factor", 0),
                            )
                btc_rets = kline_data.get("btc_returns", [])
                spy_rets = kline_data.get("spy_returns", [])
                if btc_rets and spy_rets:
                    rc_inst = self._get_regime_classifier()
                    if rc_inst is not None:
                        agi_btc_regime = self._agi_enhance(
                            "enable_btc_regime_classifier", fn=rc_inst.classify,
                            fallback="NEUTRAL", btc_returns=btc_rets, spy_returns=spy_rets,
                        )
                        if agi_btc_regime and agi_btc_regime != "NEUTRAL":
                            _bridge = self._get_subsystem_bridge()
                            if _bridge is not None:
                                _bridge.set_btc_regime(agi_btc_regime)
            except Exception as e:
                logger.debug("[FO-AGI-E] pattern/regime fail: %s", e)

            self._last_agi_pattern = agi_pattern
            inference_formed = ri >= PROBE_THRESHOLD
            action = "WAIT"
            auto_execute = False

            # ============ 宏观事件过滤器 ============
            _macro_source_tag: str | None = None
            _macro_dir, _macro_conv, _macro_info = self._apply_macro_event_filter(
                kline_data, d_star, ri
            )
            if _macro_info.get("active"):
                try:
                    from dreambuddy_evolution.agi_config import is_enabled as _is_en
                    if _is_en("enable_conviction_position_mapper"):
                        _pp = _macro_info.get("position_params") or {}
                        _macro_tier = str(_pp.get("tier", "") or "").lower()
                        if _macro_tier in ("trend_set", "trend"):
                            tier = "trend"
                            base_position_mult = 1.0
                        elif _macro_tier == "standard":
                            tier = "standard"
                            base_position_mult = 0.7
                        position_mult = base_position_mult * _regime_position_mult
                except Exception as _e:
                    logger.debug("[FO-MacroFilter] conviction tier remap fail: %s", _e)
                if _macro_info.get("direction") == d_star and d_star in ("long", "short"):
                    _macro_source_tag = "event_arbitrage"

            if inference_formed and d_star in ("long", "short"):
                aligned = (d_star == ess_dir) if ess_dir else True
                if aligned:
                    action = d_star
                    if self.mode == "Phase2":
                        auto_execute = True
                        self._store_pre_trade_snapshot(symbol, action, d_star, ess_dir, ri, position_mult)
                        self._trigger_build_position(
                            symbol, action, d_star, ri, position_mult, tier,
                            source_tag=_macro_source_tag,
                        )
                    if self.mode == "MVP" and ri >= 0.75:
                        pass

            # ============ L3/L4/AGI-H/I ============
            agi_transfer = None
            agi_counterfactual = None
            l3_sample_count = 0
            l4_v = 0.0
            try:
                _pipeline = self._get_evolution_pipeline()
                if _pipeline is not None:
                    _l3_state = {
                        "R_up": r_vector.get("R_up"), "R_down": r_vector.get("R_down"),
                        "R_smooth": r_vector.get("R_smooth"), "R_flow": r_vector.get("R_flow"),
                        "R_reflexivity": r_vector.get("R_reflexivity"),
                        "quality_score": r_vector.get("quality_score"),
                    }
                    _pipeline.shadow_rl.record(
                        symbol=symbol, state=_l3_state, action=action,
                        reward=0.0, next_state={},
                    )
                    l3_sample_count = _pipeline.shadow_rl.sample_count()
                    try:
                        _last_pc = getattr(_pipeline, "_last_primary_contradiction", None)
                        _dir_map = {"bull": "long", "bear": "short", "long": "long", "short": "short"}
                        _pc_dir = _dir_map.get((_last_pc or {}).get("direction", ""), "")
                        if _last_pc and _pc_dir in ("long", "short"):
                            _open_raw = kline_data.get("open", 0)
                            _close_raw = kline_data.get("close", 0)
                            if isinstance(_open_raw, (list, tuple)):
                                _open_px = float(_open_raw[-1]) if _open_raw else 0.0
                            elif hasattr(_open_raw, "size") and hasattr(_open_raw, "__getitem__"):
                                _open_px = float(_open_raw[-1]) if len(_open_raw) > 0 else 0.0
                            else:
                                _open_px = float(_open_raw or 0)
                            if isinstance(_close_raw, (list, tuple)):
                                _close_px = float(_close_raw[-1]) if _close_raw else 0.0
                            elif hasattr(_close_raw, "size") and hasattr(_close_raw, "__getitem__"):
                                _close_px = float(_close_raw[-1]) if len(_close_raw) > 0 else 0.0
                            else:
                                _close_px = float(_close_raw or 0)
                            if _open_px > 0:
                                _pct = (_close_px - _open_px) / _open_px
                                _aligned = (_pct > 0 and _pc_dir == "long") or \
                                           (_pct < 0 and _pc_dir == "short")
                                _pipeline._incremental_feedback(_last_pc, _aligned, _pct)
                    except Exception:
                        pass
                    try:
                        _tl = _pipeline._get_transfer_learner()
                        if _tl is not None:
                            _s_rets = kline_data.get("source_returns", [])
                            _t_rets = kline_data.get("target_returns", [])
                            _c_rets = kline_data.get("control_returns", [])
                            if _s_rets and _t_rets and _c_rets:
                                agi_transfer = self._agi_enhance(
                                    "enable_transfer_learning", fn=_tl.transfer_pattern,
                                    fallback=None, source_asset=kline_data.get("source_asset", "BTC"),
                                    target_asset=symbol,
                                    source_returns=np.array(_s_rets, dtype=float),
                                    target_returns=np.array(_t_rets, dtype=float),
                                    control_returns=np.array(_c_rets, dtype=float),
                                )
                    except Exception as _h:
                        logger.debug("[FO-AGI-H] transfer fail: %s", _h)
                    try:
                        _cf = _pipeline._get_counterfactual()
                        if _cf is not None:
                            _t_rets = kline_data.get("target_returns", [])
                            _c_rets = kline_data.get("control_returns", [])
                            if _t_rets and _c_rets:
                                agi_counterfactual = self._agi_enhance(
                                    "enable_counterfactual", fn=_cf.what_if_no_trade,
                                    fallback=None,
                                    target_returns=np.array(_t_rets, dtype=float),
                                    control_returns=np.array(_c_rets, dtype=float),
                                    actual_pnl=kline_data.get("actual_pnl", 0.0),
                                )
                    except Exception as _i:
                        logger.debug("[FO-AGI-I] counterfactual fail: %s", _i)
                    _bellman_r = float(r_vector.get("quality_score", 0.5)) - 0.5
                    _pipeline.bellman.td_update(symbol, reward=_bellman_r, next_symbol=symbol)
                    l4_v = _pipeline.bellman.get_v(symbol)
            except Exception as _e:
                logger.warning("[FO] L3/L4/AGI-H/I record crash(FAIL-OPEN): %s", _e)

            # ===== 事件驱动策略 · 影子模式 =====
            try:
                _shadow_result = {"d_star": d_star, "action": action, "ri": ri, "regime": regime}
                self._write_event_driven_state(kline_data, _shadow_result)
            except Exception as _e:
                logger.warning("[EventDriven] shadow integration crash (FAIL-OPEN): %s", _e)

            return {
                "symbol": symbol, "r_vector": r_vector, "d_star": d_star,
                "action": action, "ri": ri, "ripple_ri": ripple_ri,
                "reflection_ri": reflection_ri, "reflection_eligible": reflection_eligible,
                "signal_source": signal_source, "tier": tier,
                "position_mult": round(position_mult, 4), "regime": regime,
                "regime_position_mult": round(_regime_position_mult, 4),
                "modifiers_applied": modifiers_applied,
                "auto_execute": auto_execute, "inference_formed": inference_formed,
                "is_ripple_source": is_source, "agi_signature": agi_signature,
                "agi_pattern": agi_pattern, "agi_btc_regime": agi_btc_regime,
                "agi_path_integral": agi_path_integral, "agi_uncertainty": agi_uncertainty,
                "agi_gate_decision": agi_gate_decision, "path_info": path_info,
                "l3_sample_count": l3_sample_count, "l4_v": round(l4_v, 6),
                "agi_transfer": agi_transfer, "agi_counterfactual": agi_counterfactual,
                "elastic_position_mult": path_info.get("elastic_position_mult"),
                "structural_break": path_info.get("structural_break"),
                "shift_result": path_info.get("shift_result"),
            }
        except Exception as e:
            logger.warning("[FO] on_kline_close crash: %s", e)
            return {
                "symbol": str(kline_data.get("symbol", "UNKNOWN")),
                "r_vector": {}, "d_star": "WAIT", "action": "WAIT", "ri": 0.50,
                "ripple_ri": 0.50, "reflection_ri": 0.50, "reflection_eligible": False,
                "signal_source": "none", "modifiers_applied": False,
                "auto_execute": False, "inference_formed": False,
                "is_ripple_source": False, "agi_signature": None,
                "agi_pattern": None, "agi_btc_regime": None,
                "agi_path_integral": None, "agi_uncertainty": None,
                "agi_gate_decision": None, "path_info": {},
                "l3_sample_count": 0, "l4_v": 0.0,
                "agi_transfer": None, "agi_counterfactual": None,
                "elastic_position_mult": None, "structural_break": None,
                "shift_result": None,
            }
