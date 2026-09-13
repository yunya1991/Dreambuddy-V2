"""
K线级事件触发器 (§1.8 频率分层硬约束)
替代每日 UTC 00:05 cron → K线收盘事件触发 L1/RippleEngine/Level0

频率分层:
- L1/RippleEngine/Level0 = 每K线收盘 (1h/4h/1d)
- L2 = 6h 批 (ESS 更新后)
- L3/ReflectionEngine = 每笔 close + 6h 批
- L4 = 每笔 close + 6h 批

AGI 增强点（阶段1只读增强）:
- A: L1 R向量后 → SignatureEngine 路径签名
- B: L1 R向量后 → PathIntegralEngine 蒙特卡洛路径复核
- C: RI计算后 → UncertaintyQuantifier 不确定性量化
- D: RI计算后 → MetaCognitionGate 元认知门禁决策
- E: 建仓前 → PatternDetector 形态检测 + RegimeClassifier regime 分类

路径发现层（多路径竞争 → 寻优 → argmin 最小阻力）:
- 在 Level0 d* 计算后接入路径发现层
- 6 种路径来源：L2基因库/BCRM/BDSM/战略层/DeepReasoning/StrategySynthesizer
- 路径寻优：score = expected_return × confidence × (1 - resistance)
- 统计验证：score > 0.05 才验证通过，gap < 0.02 降仓
- 依据最优路径方向覆盖 d* 决策

FAIL-OPEN: crash → 返回 WAIT + 不崩溃
"""
import logging
from typing import Any

import numpy as np

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
        # AGI 模块懒初始化标志（None=未初始化, False=不可用, 实例=可用）
        self._sig_engine: Any = None
        self._pattern_detector: Any = None
        self._regime_classifier: Any = None
        self._path_integral_engine: Any = None
        self._uncertainty_quant: Any = None
        self._meta_cognition_gate: Any = None
        # 路径发现层懒初始化标志
        self._evolution_pipeline: Any = None
        self._subsystem_bridge: Any = None
        self._trader: Any = None  # Phase 4.2: trader 引用，注入到 bridge
        self._last_agi_pattern: dict | None = None  # Phase 4.1: 最近一次形态检测结果
        self._path_layer_enabled: bool = False  # 延迟检测是否可用

    # ==================================================================
    # AGI 增强统一入口（开关检查 + FAIL-OPEN）
    # ==================================================================

    def _agi_enhance(self, switch: str, fn: Any, fallback: Any, **kw: Any) -> Any:
        """AGI 增强统一入口：开关检查 + FAIL-OPEN.

        Args:
            switch: agi_config 开关名称
            fn: 可调用对象，开关开启时执行
            fallback: 开关关闭或异常时的中性兜底值
            **kw: 传给 fn 的参数
        Returns:
            fn 的返回值或 fallback
        """
        try:
            from dreambuddy_evolution.agi_config import is_enabled
            if not is_enabled(switch):
                return fallback
        except Exception:
            return fallback
        try:
            return fn(**kw)
        except Exception as e:
            logger.warning("[FO-AGI][%s] crash: %s", switch, e)
            return fallback

    def _get_sig_engine(self) -> Any:
        """懒初始化 SignatureEngine"""
        if self._sig_engine is None:
            try:
                from dreambuddy_evolution.core.signature_engine import SignatureEngine
                self._sig_engine = SignatureEngine(depth=3)
            except Exception as e:
                logger.debug("[FO-AGI] SignatureEngine init fail: %s", e)
                self._sig_engine = False
        return self._sig_engine or None

    def _get_pattern_detector(self) -> Any:
        """懒初始化 PatternDetector"""
        if self._pattern_detector is None:
            try:
                from dreambuddy_evolution.engines.pattern_detector import PatternDetector
                self._pattern_detector = PatternDetector()
            except Exception as e:
                logger.debug("[FO-AGI] PatternDetector init fail: %s", e)
                self._pattern_detector = False
        return self._pattern_detector or None

    def _get_regime_classifier(self) -> Any:
        """懒初始化 RegimeClassifier"""
        if self._regime_classifier is None:
            try:
                from dreambuddy_evolution.core.regime_classifier import RegimeClassifier
                self._regime_classifier = RegimeClassifier()
            except Exception as e:
                logger.debug("[FO-AGI] RegimeClassifier init fail: %s", e)
                self._regime_classifier = False
        return self._regime_classifier or None

    def _get_path_integral_engine(self) -> Any:
        """懒初始化 PathIntegralEngine"""
        if self._path_integral_engine is None:
            try:
                from dreambuddy_evolution.core.path_integral import PathIntegralEngine
                self._path_integral_engine = PathIntegralEngine(n_paths=1000)
            except Exception as e:
                logger.debug("[FO-AGI] PathIntegralEngine init fail: %s", e)
                self._path_integral_engine = False
        return self._path_integral_engine or None

    def _get_uncertainty_quant(self) -> Any:
        """懒初始化 UncertaintyQuantifier"""
        if self._uncertainty_quant is None:
            try:
                from dreambuddy_evolution.core.uncertainty_quantifier import UncertaintyQuantifier
                self._uncertainty_quant = UncertaintyQuantifier()
            except Exception as e:
                logger.debug("[FO-AGI] UncertaintyQuantifier init fail: %s", e)
                self._uncertainty_quant = False
        return self._uncertainty_quant or None

    def _get_meta_cognition_gate(self) -> Any:
        """懒初始化 MetaCognitionGate"""
        if self._meta_cognition_gate is None:
            try:
                from dreambuddy_evolution.engines.meta_cognition_gate import MetaCognitionGate
                self._meta_cognition_gate = MetaCognitionGate()
            except Exception as e:
                logger.debug("[FO-AGI] MetaCognitionGate init fail: %s", e)
                self._meta_cognition_gate = False
        return self._meta_cognition_gate or None

    def _get_evolution_pipeline(self) -> Any:
        """懒初始化 EvolutionPipeline（路径发现层）"""
        if self._evolution_pipeline is None:
            try:
                from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
                # Fix A: 传入 trader 以激活 SubSystemBridge → bcrm/bdsm/strategic 路径
                self._evolution_pipeline = EvolutionPipeline(trader=getattr(self, "_trader", None))
                self._path_layer_enabled = True
                logger.info("[PathLayer] EvolutionPipeline 初始化成功，路径发现层已启用")
            except Exception as e:
                logger.warning("[PathLayer] EvolutionPipeline init fail: %s", e)
                self._evolution_pipeline = False
                self._path_layer_enabled = False
        return self._evolution_pipeline or None

    def attach_trader(self, trader: Any) -> None:
        """Phase 4.2: 注入 trader 引用，用于 SubSystemBridge 写回 regime 状态。"""
        self._trader = trader

    def _get_subsystem_bridge(self) -> Any:
        """懒初始化 SubSystemBridge（高阶因子阻力调制）"""
        if self._subsystem_bridge is None:
            try:
                from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge
                self._subsystem_bridge = SubSystemBridge()
            except Exception as e:
                logger.debug("[PathLayer] SubSystemBridge init fail: %s", e)
                self._subsystem_bridge = False
        # Phase 4.2: 注入 trader 到 bridge
        if self._subsystem_bridge and self._trader is not None:
            try:
                self._subsystem_bridge.attach_trader(self._trader)
            except Exception:
                pass
        return self._subsystem_bridge or None

    def _run_path_discovery(
        self,
        symbol: str,
        r_vector: dict[str, Any],
        d_star: str,
        ri: float,
        kline_data: dict[str, Any],
    ) -> tuple[str, float, dict[str, Any]]:
        """路径发现层：多路径竞争 → 寻优 → 依据最优路径覆盖 d* 决策。

        理论框架：
          多路径竞争 → 寻找最优路径（现有/基于现有计算新的/自进化涌现）
          → 依据最优路径计算 argmin 最小阻力 → 统计验证 → 实盘交易 → 进化寻优

        Args:
            symbol: 交易对
            r_vector: L1 R向量（up/down/smooth/flow/reflexivity）
            d_star: Level0 argmin 输出的原始方向（long/short/WAIT）
            ri: 综合推力 RI
            kline_data: 原始K线数据

        Returns:
            (adjusted_d_star, adjusted_ri, path_info_dict)
            - adjusted_d_star: 路径发现层调整后的方向（可能覆盖 d_star）
            - adjusted_ri: 调整后的 RI（可能因低确信度降仓）
            - path_info_dict: 路径发现详情
        """
        path_info: dict[str, Any] = {
            "path_count": 0,
            "optimal_source": None,
            "optimal_score": 0.0,
            "validated": False,
            "low_conviction": False,
            "d_star_original": d_star,
            "d_star_adjusted": d_star,
            "primary_contradiction": None,
        }

        try:
            pipeline = self._get_evolution_pipeline()
            if pipeline is None:
                return d_star, ri, path_info

            # 提取 close 序列给路径发现层
            closes = r_vector.get("_close_series") or []
            if not closes:
                raw_close = kline_data.get("close", 0.0)
                if isinstance(raw_close, (list, tuple)):
                    closes = [float(c) for c in raw_close if c is not None]
                elif isinstance(raw_close, np.ndarray):
                    closes = [float(x) for x in raw_close.ravel().tolist() if x is not None]
                else:
                    closes = [float(raw_close)]

            # 调用 EvolutionPipeline 的路径发现方法
            # 签名: _discover_paths(r_out, market_data, symbol)
            market_data = {**kline_data, "close": closes}
            if hasattr(pipeline, "_discover_paths"):
                paths = pipeline._discover_paths(r_vector, market_data, symbol)
                path_info["path_count"] = len(paths) if isinstance(paths, list) else 0

                if hasattr(pipeline, "_select_optimal_path"):
                    raw_optimal = pipeline._select_optimal_path(paths, r_vector)
                    # 适配 EvolutionPipeline 返回的嵌套结构
                    if raw_optimal and raw_optimal.get("optimal_path"):
                        op = raw_optimal["optimal_path"]
                        sv = raw_optimal.get("statistical_validation", {})
                        optimal = {
                            "source": op.get("source"),
                            "direction": op.get("direction"),
                            "score": op.get("score", 0.0),
                            "validated": sv.get("validated", False),
                            "low_conviction": sv.get("low_conviction", False),
                        }
                    else:
                        optimal = None
                    if optimal:
                        path_info["optimal_source"] = optimal.get("source")
                        path_info["optimal_score"] = round(
                            float(optimal.get("score", 0.0)), 6
                        )
                        path_info["validated"] = optimal.get("validated", False)
                        path_info["low_conviction"] = optimal.get(
                            "low_conviction", False
                        )
                        # 透传矛盾论识别结果（从 path_info 中取）
                        _pi = raw_optimal.get("path_info") or raw_optimal  # 兼容两种格式
                        path_info["primary_contradiction"] = _pi.get(
                            "primary_contradiction"
                        )
                        # Phase 1-3 透传
                        path_info["structural_break"] = _pi.get("structural_break")
                        path_info["shift_result"] = _pi.get("shift_result")
                        # §14+§19 透传：反身性燃料+认知函数
                        path_info["reflexivity_fuel"] = _pi.get("reflexivity_fuel")
                        path_info["cognition_result"] = _pi.get("cognition_result")
                        _elastic = _pi.get("elastic_result")
                        # 完整 elastic_result 透传（dashboard 用）
                        path_info["elastic_result"] = _elastic
                        if _elastic is not None and _elastic.get("constraint_active"):
                            _mult = float(_elastic.get("position_mult", 1.0))
                            ri = ri * _mult  # 弹性约束调整仓位
                            path_info["elastic_position_mult"] = round(_mult, 6)
                            path_info["elastic_t_max"] = _elastic.get("t_max", 0.0)
                            path_info["elastic_rebound_risk"] = _elastic.get("rebound_risk", 0.0)
                        # HJB 结果透传（dashboard 用）
                        _hjb = _pi.get("hjb_policy") or _pi.get("hjb_result")
                        if _hjb is not None:
                            path_info["hjb_policy"] = _hjb

                        # 依据最优路径覆盖 d* 决策
                        opt_dir = optimal.get("direction", "")
                        if opt_dir in ("long", "short") and optimal.get(
                            "validated", False
                        ):
                            path_info["d_star_adjusted"] = opt_dir
                            # 低确信度降仓
                            if optimal.get("low_conviction", False):
                                ri = ri * 0.7
                                logger.info(
                                    "[PathLayer] %s 低确信度降仓 RI %.3f→%.3f",
                                    symbol,
                                    ri / 0.7,
                                    ri,
                                )
                            logger.info(
                                "[PathLayer] %s 路径发现覆盖 d*: %s→%s "
                                "source=%s score=%.4f",
                                symbol,
                                d_star,
                                opt_dir,
                                optimal.get("source"),
                                float(optimal.get("score", 0.0)),
                            )
                            return opt_dir, ri, path_info

        except Exception as e:
            import traceback
            logger.warning("[PathLayer] %s 路径发现层 crash: %s\n%s", symbol, e, traceback.format_exc())

        return d_star, ri, path_info

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

            # ============ AGI 增强点 A: SignatureEngine 路径签名（只读） ============
            agi_signature = None
            try:
                closes_raw = kline_data.get("close", [])
                if isinstance(closes_raw, (list, np.ndarray)) and len(closes_raw) >= 10:
                    sig_engine = self._get_sig_engine()
                    if sig_engine is not None:
                        path = np.array(closes_raw, dtype=float)
                        sig = self._agi_enhance(
                            "enable_signature_engine",
                            fn=sig_engine.signature,
                            fallback=None,
                            path=path,
                        )
                        if sig is not None and len(sig) > 0:
                            agi_signature = {
                                "dim": int(len(sig)),
                                "norm": round(float(np.linalg.norm(sig)), 6),
                                "first": round(float(sig[0]), 6),
                            }
                            logger.debug(
                                "[AGI-A] %s signature dim=%d norm=%.4f",
                                symbol, agi_signature["dim"], agi_signature["norm"],
                            )
            except Exception as e:
                logger.debug("[FO-AGI-A] signature fail: %s", e)

            # ============ AGI 增强点 B: PathIntegralEngine 蒙特卡洛路径复核（只读） ============
            agi_path_integral = None
            try:
                closes_raw = kline_data.get("close", [])
                if isinstance(closes_raw, (list, np.ndarray)) and len(closes_raw) >= 10:
                    pi_engine = self._get_path_integral_engine()
                    if pi_engine is not None:
                        closes_arr = np.array(closes_raw, dtype=float)
                        start_price = float(closes_arr[-1])
                        # 从近期收盘价估算波动率（日收益率标准差）
                        rets = np.diff(closes_arr) / np.maximum(closes_arr[:-1], 1e-9)
                        vol = float(np.std(rets)) if len(rets) >= 2 else 0.02
                        vol = max(vol, 0.001)  # 下限保护
                        horizon = min(len(closes_arr), 20)  # 路径长度上限20步

                        def _run_path_integral():
                            paths = pi_engine.sample_paths(
                                start_price=start_price,
                                horizon=horizon,
                                volatility=vol,
                                drift=0.0,
                            )
                            best_idx, best_action = pi_engine.find_least_resistance_path(paths)
                            exp_path = pi_engine.expected_path(paths, temperature=1.0)
                            return {
                                "n_paths": len(paths),
                                "horizon": horizon,
                                "volatility": round(vol, 6),
                                "min_resistance_action": round(float(best_action), 6),
                                "expected_end_price": round(float(exp_path[-1]), 6),
                                "start_price": round(start_price, 6),
                            }

                        agi_path_integral = self._agi_enhance(
                            "enable_path_integral",
                            fn=_run_path_integral,
                            fallback=None,
                        )
                        if agi_path_integral is not None:
                            logger.debug(
                                "[AGI-B] %s PI: n=%d vol=%.4f min_S=%.4f exp_end=%.2f",
                                symbol,
                                agi_path_integral["n_paths"],
                                agi_path_integral["volatility"],
                                agi_path_integral["min_resistance_action"],
                                agi_path_integral["expected_end_price"],
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

            # ============ 3b. 路径发现层（多路径竞争 → 寻优 → 覆盖 d*） ============
            # 理论框架：多路径竞争 → 寻找最优路径（现有/基于现有计算新的/自进化涌现）
            #   → 依据最优路径计算 argmin 最小阻力 → 统计验证 → 实盘交易 → 进化寻优
            # 6 种路径来源：L2基因库/BCRM/BDSM/战略层/DeepReasoning/StrategySynthesizer
            path_info: dict[str, Any] = {
                "path_count": 0,
                "optimal_source": None,
                "optimal_score": 0.0,
                "validated": False,
                "low_conviction": False,
                "d_star_original": d_star,
                "d_star_adjusted": d_star,
                "primary_contradiction": None,
            }
            # Fix 5: WAIT 状态仍运行矛盾识别（不改变 d_star，但更新 _last_primary_contradiction）
            try:
                if (r_vector and r_vector.get("R_up") is not None
                        and r_vector.get("R_down") is not None):
                    if d_star in ("long", "short"):
                        d_star, ri_path_adjusted, path_info = self._run_path_discovery(
                            symbol, r_vector, d_star, 0.5, kline_data
                        )
                    elif d_star == "WAIT":
                        # WAIT 时仍运行路径发现以更新矛盾识别，但不改变 d_star
                        _, _, _ = self._run_path_discovery(
                            symbol, r_vector, "neutral", 0.5, kline_data
                        )
            except Exception as e:
                logger.debug("[PathLayer] %s outer crash: %s", symbol, e)

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

            # ============ AGI 增强点 C: UncertaintyQuantifier 不确定性量化（只读） ============
            agi_uncertainty = None
            try:
                uq_inst = self._get_uncertainty_quant()
                if uq_inst is not None:
                    # 用双起点 RI 分歧作为集成方差的代理
                    ensemble_std = abs(ripple_ri - reflection_ri)
                    # 特征噪声 = 1 - RI（RI 低 → 噪声高）
                    feature_noise = max(0.0, 1.0 - ri)
                    agi_uncertainty = self._agi_enhance(
                        "enable_uncertainty_quant",
                        fn=uq_inst.quantify_uncertainty,
                        fallback=None,
                        prediction=ri,
                        ensemble_std=ensemble_std,
                        conformal_width=None,
                        feature_noise=feature_noise,
                    )
                    if agi_uncertainty is not None:
                        logger.debug(
                            "[AGI-C] %s uncertainty=%.4f level=%s",
                            symbol,
                            agi_uncertainty.get("uncertainty_score", 0),
                            agi_uncertainty.get("level", "?"),
                        )
            except Exception as e:
                logger.debug("[FO-AGI-C] uncertainty fail: %s", e)

            # ============ AGI 增强点 D: MetaCognitionGate 元认知门禁（只读） ============
            agi_gate_decision = None
            try:
                mcg_inst = self._get_meta_cognition_gate()
                if mcg_inst is not None and agi_uncertainty is not None:
                    unc_score = agi_uncertainty.get("uncertainty_score", 0.5)
                    agi_gate_decision = self._agi_enhance(
                        "enable_meta_cognition",
                        fn=mcg_inst.gate_decision,
                        fallback=None,
                        uncertainty_score=unc_score,
                        base_confidence=ri,
                        strategy_sharpe=None,
                        position_size=1.0,
                    )
                    if agi_gate_decision is not None:
                        logger.debug(
                            "[AGI-D] %s gate=%s pos_mult=%s",
                            symbol,
                            agi_gate_decision.get("decision", "?"),
                            agi_gate_decision.get("position_multiplier", "?"),
                        )
            except Exception as e:
                logger.debug("[FO-AGI-D] gate_decision fail: %s", e)

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
            PROBE_THRESHOLD = 0.55   # 轻仓试探门槛（2026-09-12 从0.50提高，过滤低确信度试探）
            STANDARD_THRESHOLD = 0.60  # 标准仓门槛
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

            # ============ AGI 增强点 E: PatternDetector + RegimeClassifier（只读） ============
            agi_pattern = None
            agi_btc_regime = None
            try:
                closes_raw = kline_data.get("close", [])
                if isinstance(closes_raw, (list, np.ndarray)) and len(closes_raw) >= 30:
                    # PatternDetector: 价格形态检测（头肩顶/底等）
                    pd_inst = self._get_pattern_detector()
                    if pd_inst is not None:
                        klines_for_pattern = [{"close": float(c)} for c in closes_raw]
                        agi_pattern = self._agi_enhance(
                            "enable_pattern_detector",
                            fn=pd_inst.bcrm_technical_assessment,
                            fallback=None,
                            klines=klines_for_pattern,
                        )
                        if agi_pattern and agi_pattern.get("is_reversal_signal"):
                            logger.info(
                                "[AGI-E] %s pattern=%s dir=%s conf=%.2f factor=%.2f",
                                symbol,
                                agi_pattern.get("pattern"),
                                agi_pattern.get("direction"),
                                agi_pattern.get("confidence", 0),
                                agi_pattern.get("pattern_factor", 0),
                            )

                # RegimeClassifier: BTC-美股 regime 分类（需 btc/spy 收益率）
                btc_rets = kline_data.get("btc_returns", [])
                spy_rets = kline_data.get("spy_returns", [])
                if btc_rets and spy_rets:
                    rc_inst = self._get_regime_classifier()
                    if rc_inst is not None:
                        agi_btc_regime = self._agi_enhance(
                            "enable_btc_regime_classifier",
                            fn=rc_inst.classify,
                            fallback="NEUTRAL",
                            btc_returns=btc_rets,
                            spy_returns=spy_rets,
                        )
                        logger.debug("[AGI-E] %s btc_regime=%s", symbol, agi_btc_regime)
                        # Phase 4.2: 写回战略层 shadow 状态
                        if agi_btc_regime and agi_btc_regime != "NEUTRAL":
                            _bridge = self._get_subsystem_bridge()
                            if _bridge is not None:
                                _bridge.set_btc_regime(agi_btc_regime)
            except Exception as e:
                logger.debug("[FO-AGI-E] pattern/regime fail: %s", e)

            # Phase 4.1: 存储最近一次形态检测结果，供 _evolution_build_position 读取
            self._last_agi_pattern = agi_pattern

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

            # ============ L3/L4/AGI-H/I（迁移自 EvolutionPipeline.run_symbol L817-890）============
            agi_transfer = None
            agi_counterfactual = None
            l3_sample_count = 0
            l4_v = 0.0
            try:
                _pipeline = self._get_evolution_pipeline()
                if _pipeline is not None:
                    # --- L3: ShadowRL record (run_symbol L817-827) ---
                    # Fix 1: 不再用 quality_score 作为 reward（数据质量≠方向正确性）
                    # 真实 PnL reward 由 TradeSettlementBridge._record_real_pnl_reward 在平仓时注入
                    # 此处仅记录 state 快照，reward=0.0 占位
                    _l3_state = {
                        "R_up": r_vector.get("R_up"),
                        "R_down": r_vector.get("R_down"),
                        "R_smooth": r_vector.get("R_smooth"),
                        "R_flow": r_vector.get("R_flow"),
                        "R_reflexivity": r_vector.get("R_reflexivity"),
                        "quality_score": r_vector.get("quality_score"),  # 保留为特征
                    }
                    _pipeline.shadow_rl.record(
                        symbol=symbol,
                        state=_l3_state,
                        action=action,
                        reward=0.0,  # Fix 1: 占位，真实 reward 由平仓事件注入
                        next_state={},
                    )
                    l3_sample_count = _pipeline.shadow_rl.sample_count()

                    # Fix 6: K线级增量反馈 — 用当前K线涨跌验证上次矛盾方向
                    try:
                        _last_pc = getattr(_pipeline, "_last_primary_contradiction", None)
                        # 方向归一化: ExogenousStrengthEvaluator 返回 bull/bear，统一映射为 long/short
                        _dir_map = {"bull": "long", "bear": "short", "long": "long", "short": "short"}
                        _pc_dir = _dir_map.get((_last_pc or {}).get("direction", ""), "")
                        if _last_pc and _pc_dir in ("long", "short"):
                            # open/close 可能是 numpy 数组(OKX返回序列)，取最后一根K线
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
                        pass  # FAIL-OPEN

                    # --- AGI-H: TransferLearner (run_symbol L829-858) ---
                    try:
                        _tl = _pipeline._get_transfer_learner()
                        if _tl is not None:
                            _s_rets = kline_data.get("source_returns", [])
                            _t_rets = kline_data.get("target_returns", [])
                            _c_rets = kline_data.get("control_returns", [])
                            if _s_rets and _t_rets and _c_rets:
                                agi_transfer = self._agi_enhance(
                                    "enable_transfer_learning",
                                    fn=_tl.transfer_pattern,
                                    fallback=None,
                                    source_asset=kline_data.get("source_asset", "BTC"),
                                    target_asset=symbol,
                                    source_returns=np.array(_s_rets, dtype=float),
                                    target_returns=np.array(_t_rets, dtype=float),
                                    control_returns=np.array(_c_rets, dtype=float),
                                )
                    except Exception as _h:
                        logger.debug("[FO-AGI-H] transfer fail: %s", _h)

                    # --- AGI-I: CounterfactualEvaluator (run_symbol L862-887) ---
                    try:
                        _cf = _pipeline._get_counterfactual()
                        if _cf is not None:
                            _t_rets = kline_data.get("target_returns", [])
                            _c_rets = kline_data.get("control_returns", [])
                            if _t_rets and _c_rets:
                                agi_counterfactual = self._agi_enhance(
                                    "enable_counterfactual",
                                    fn=_cf.what_if_no_trade,
                                    fallback=None,
                                    target_returns=np.array(_t_rets, dtype=float),
                                    control_returns=np.array(_c_rets, dtype=float),
                                    actual_pnl=kline_data.get("actual_pnl", 0.0),
                                )
                    except Exception as _i:
                        logger.debug("[FO-AGI-I] counterfactual fail: %s", _i)

                    # --- L4: Bellman TD(0) (run_symbol L890) ---
                    # Fix 1: Bellman V(s) 保留 quality_score 信号（状态价值≠策略反馈）
                    _bellman_r = float(r_vector.get("quality_score", 0.5)) - 0.5
                    _pipeline.bellman.td_update(
                        symbol, reward=_bellman_r, next_symbol=symbol
                    )
                    l4_v = _pipeline.bellman.get_v(symbol)
            except Exception as _e:
                logger.warning("[FO] L3/L4/AGI-H/I record crash(FAIL-OPEN): %s", _e)

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
                "agi_signature": agi_signature,
                "agi_pattern": agi_pattern,
                "agi_btc_regime": agi_btc_regime,
                "agi_path_integral": agi_path_integral,
                "agi_uncertainty": agi_uncertainty,
                "agi_gate_decision": agi_gate_decision,
                "path_info": path_info,
                "l3_sample_count": l3_sample_count,
                "l4_v": round(l4_v, 6),
                "agi_transfer": agi_transfer,
                "agi_counterfactual": agi_counterfactual,
                # Phase 1-3 新增字段
                "elastic_position_mult": path_info.get("elastic_position_mult"),
                "structural_break": path_info.get("structural_break"),
                "shift_result": path_info.get("shift_result"),
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
                "agi_signature": None,
                "agi_pattern": None,
                "agi_btc_regime": None,
                "agi_path_integral": None,
                "agi_uncertainty": None,
                "agi_gate_decision": None,
                "path_info": {},
                "l3_sample_count": 0,
                "l4_v": 0.0,
                "agi_transfer": None,
                "agi_counterfactual": None,
                "elastic_position_mult": None,
                "structural_break": None,
                "shift_result": None,
            }

    def get_evolution_feedback(self) -> dict[str, Any]:
        """L3/L4 回馈摘要（委托 EvolutionPipeline.get_feedback）.

        供 polling_trader 在 6h 批/日复盘周期调用，
        回写 L2 ESS ±0.02 + L1 权重校准。

        FAIL-OPEN: pipeline 不可用时返回空摘要。
        """
        try:
            _pipeline = self._get_evolution_pipeline()
            if _pipeline is not None and hasattr(_pipeline, "get_feedback"):
                return _pipeline.get_feedback()
        except Exception as _e:
            logger.warning("[FO] get_evolution_feedback crash: %s", _e)
        return {"l3_stats": {}, "l4_v_all": {}, "l4_ess_adjustments": {}}
