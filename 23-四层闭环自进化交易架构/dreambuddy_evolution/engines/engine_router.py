"""P1-2 拆分组件: EngineRouter

从 kline_event_handler.py 拆出的 AGI 增强 + 懒加载 getters + 路径发现职责。

来源: SPEC v0.3 §2.B — kline_event_handler 多职责缝合体拆分
"""
from __future__ import annotations

import logging
import traceback
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Phase 1: 事件驱动策略接入路径发现层（模块级导入支持测试 monkeypatch）
try:
    from event_driven import EventDrivenStrategy  # type: ignore[import]
except ImportError:  # event_driven 包不在 sys.path 时
    EventDrivenStrategy = None  # type: ignore[assignment]


class EngineRouter:
    """AGI 增强路由器 — 从 KlineEventHandler 拆出的内聚组件.

    职责:
      1. AGI 增强统一入口（开关检查 + FAIL-OPEN）
      2. 懒加载 getters（SignatureEngine / PatternDetector / etc.）
      3. 路径发现层（多路径竞争 → 寻优 → 覆盖 d*）
    """

    def __init__(self) -> None:
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
        self._trader: Any = None
        self._path_layer_enabled: bool = False
        # 事件驱动策略
        self._event_driven_strategy: Any = None
        # ReflectionScanner（延迟初始化）
        self._reflection_scanner: Any = None
        self._project_root: str | None = None
        # 方向预测透传
        self._last_dimension_predictions: dict = {}

    def attach_trader(self, trader: Any) -> None:
        """注入 trader 引用，用于 SubSystemBridge 写回 regime 状态。"""
        self._trader = trader

    # ------------------------------------------------------------------
    # AGI 增强统一入口（开关检查 + FAIL-OPEN）
    # ------------------------------------------------------------------
    def agi_enhance(self, switch: str, fn: Any, fallback: Any, **kw: Any) -> Any:
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

    # ------------------------------------------------------------------
    # 懒加载 getters
    # ------------------------------------------------------------------
    def get_sig_engine(self) -> Any:
        """懒初始化 SignatureEngine"""
        if self._sig_engine is None:
            try:
                from dreambuddy_evolution.core.signature_engine import SignatureEngine
                self._sig_engine = SignatureEngine(depth=3)
            except Exception as e:
                logger.debug("[FO-AGI] SignatureEngine init fail: %s", e)
                self._sig_engine = False
        return self._sig_engine or None

    def get_pattern_detector(self) -> Any:
        """懒初始化 PatternDetector"""
        if self._pattern_detector is None:
            try:
                from dreambuddy_evolution.engines.pattern_detector import PatternDetector
                self._pattern_detector = PatternDetector()
            except Exception as e:
                logger.debug("[FO-AGI] PatternDetector init fail: %s", e)
                self._pattern_detector = False
        return self._pattern_detector or None

    def get_regime_classifier(self) -> Any:
        """懒初始化 RegimeClassifier"""
        if self._regime_classifier is None:
            try:
                from dreambuddy_evolution.core.regime_classifier import RegimeClassifier
                self._regime_classifier = RegimeClassifier()
            except Exception as e:
                logger.debug("[FO-AGI] RegimeClassifier init fail: %s", e)
                self._regime_classifier = False
        return self._regime_classifier or None

    def get_path_integral_engine(self) -> Any:
        """懒初始化 PathIntegralEngine"""
        if self._path_integral_engine is None:
            try:
                from dreambuddy_evolution.core.path_integral import PathIntegralEngine
                self._path_integral_engine = PathIntegralEngine(n_paths=1000)
            except Exception as e:
                logger.debug("[FO-AGI] PathIntegralEngine init fail: %s", e)
                self._path_integral_engine = False
        return self._path_integral_engine or None

    def get_uncertainty_quant(self) -> Any:
        """懒初始化 UncertaintyQuantifier"""
        if self._uncertainty_quant is None:
            try:
                from dreambuddy_evolution.core.uncertainty_quantifier import UncertaintyQuantifier
                self._uncertainty_quant = UncertaintyQuantifier()
            except Exception as e:
                logger.debug("[FO-AGI] UncertaintyQuantifier init fail: %s", e)
                self._uncertainty_quant = False
        return self._uncertainty_quant or None

    def get_meta_cognition_gate(self) -> Any:
        """懒初始化 MetaCognitionGate"""
        if self._meta_cognition_gate is None:
            try:
                from dreambuddy_evolution.engines.meta_cognition_gate import MetaCognitionGate
                self._meta_cognition_gate = MetaCognitionGate()
            except Exception as e:
                logger.debug("[FO-AGI] MetaCognitionGate init fail: %s", e)
                self._meta_cognition_gate = False
        return self._meta_cognition_gate or None

    def get_evolution_pipeline(self) -> Any:
        """懒初始化 EvolutionPipeline（路径发现层）"""
        if self._evolution_pipeline is None:
            try:
                from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
                self._evolution_pipeline = EvolutionPipeline(trader=getattr(self, "_trader", None))
                self._path_layer_enabled = True
                logger.info("[PathLayer] EvolutionPipeline 初始化成功，路径发现层已启用")
            except Exception as e:
                logger.warning("[PathLayer] EvolutionPipeline init fail: %s", e)
                self._evolution_pipeline = False
                self._path_layer_enabled = False
        return self._evolution_pipeline or None

    def get_event_driven_strategy(self) -> Any:
        """懒初始化 EventDrivenStrategy（影子模式）."""
        if self._event_driven_strategy is None:
            try:
                import sys
                from pathlib import Path
                repo_root = Path(__file__).resolve().parents[3]
                _29_dir = repo_root / "29-事件驱动策略系统"
                if str(_29_dir) not in sys.path:
                    sys.path.insert(0, str(_29_dir))
                from event_driven import EventDrivenStrategy
                self._event_driven_strategy = EventDrivenStrategy()
                logger.info("[EventDriven] EventDrivenStrategy 初始化成功（影子模式）")
            except Exception as e:
                logger.warning("[EventDriven] EventDrivenStrategy init fail: %s", e)
                self._event_driven_strategy = False
        return self._event_driven_strategy or None

    def get_reflection_scanner(self) -> Any:
        """延迟初始化 ReflectionScanner"""
        if self._reflection_scanner is None:
            try:
                from dreambuddy_evolution.engines.reflection_scanner import ReflectionScanner
                self._reflection_scanner = ReflectionScanner(project_root=self._project_root)
            except Exception as e:
                logger.warning("[FO] ReflectionScanner init fail: %s", e)
                self._reflection_scanner = False
        return self._reflection_scanner or None

    def get_subsystem_bridge(self) -> Any:
        """懒初始化 SubSystemBridge（高阶因子阻力调制）"""
        if self._subsystem_bridge is None:
            try:
                from dreambuddy_evolution.adapters.subsystem_bridge import SubSystemBridge
                self._subsystem_bridge = SubSystemBridge()
            except Exception as e:
                logger.debug("[PathLayer] SubSystemBridge init fail: %s", e)
                self._subsystem_bridge = False
        if self._subsystem_bridge and self._trader is not None:
            try:
                self._subsystem_bridge.attach_trader(self._trader)
            except Exception as e:
                logger.debug("[FO] SubSystemBridge attach_trader fail: %s", e)
        return self._subsystem_bridge or None

    # ------------------------------------------------------------------
    # 路径发现层
    # ------------------------------------------------------------------
    def run_path_discovery(
        self,
        symbol: str,
        d_star: str,
        r_vector: dict[str, Any],
        kline_data: dict[str, Any],
        mode: str = "MVP",
        ri: float = 0.5,
        event_driven_strategy_cls: Any = None,
    ) -> dict[str, Any]:
        """路径发现层：多路径竞争 → 寻优 → 依据最优路径覆盖 d* 决策.

        Returns:
            dict 含 d_star_adjusted / ri_adjusted / path_info 字段
        """
        path_info: dict[str, Any] = {
            "path_count": 0,
            "optimal_source": None,
            "optimal_score": 0.0,
            "validated": False,
            "low_conviction": False,
            "d_star_original": d_star,
            "d_star_adjusted": d_star,
            "ri_adjusted": ri,
            "primary_contradiction": None,
        }

        try:
            pipeline = self.get_evolution_pipeline()
            if pipeline is None:
                return path_info

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

            market_data = {**kline_data, "close": closes}
            if hasattr(pipeline, "_discover_paths"):
                paths = pipeline._discover_paths(r_vector, market_data, symbol)
                path_info["path_count"] = len(paths) if isinstance(paths, list) else 0
                if not isinstance(paths, list):
                    paths = []

                # Phase 1: 事件驱动路径注入（支持 Facade 传入 monkeypatch 后的类）
                try:
                    from dreambuddy_evolution.agi_config import is_enabled
                    _eds_cls = event_driven_strategy_cls if event_driven_strategy_cls is not None else EventDrivenStrategy
                    if is_enabled("enable_event_driven_path") and _eds_cls is not None:
                        eds = _eds_cls()
                        event_signal = eds.evaluate(kline_data)
                        if event_signal is not None and \
                           getattr(event_signal, "signal", "neutral") != "neutral" and \
                           float(getattr(event_signal, "strength", 0.0)) >= 0.60:
                            paths.append({
                                "source": "event_driven",
                                "direction": event_signal.signal,
                                "score": float(event_signal.strength),
                                "validated": True,
                                "low_conviction": float(event_signal.strength) < 0.50,
                                "event_phase": getattr(event_signal, "event_phase", None),
                                "reason": getattr(event_signal, "reason", ""),
                            })
                            path_info["path_count"] = len(paths)
                except Exception as e:
                    logger.debug("[PathLayer] event-driven path injection fail (FAIL-OPEN): %s", e)

                if hasattr(pipeline, "_select_optimal_path"):
                    raw_optimal = pipeline._select_optimal_path(paths, r_vector)
                    self._last_dimension_predictions = (
                        raw_optimal.get("dimension_predictions", {})
                        if isinstance(raw_optimal, dict) else {}
                    )
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
                        _pi = raw_optimal.get("path_info") or raw_optimal
                        path_info["primary_contradiction"] = _pi.get(
                            "primary_contradiction"
                        )
                        path_info["structural_break"] = _pi.get("structural_break")
                        path_info["shift_result"] = _pi.get("shift_result")
                        path_info["reflexivity_fuel"] = _pi.get("reflexivity_fuel")
                        path_info["cognition_result"] = _pi.get("cognition_result")
                        _elastic = _pi.get("elastic_result")
                        path_info["elastic_result"] = _elastic
                        if _elastic is not None and _elastic.get("constraint_active"):
                            _mult = float(_elastic.get("position_mult", 1.0))
                            ri = ri * _mult
                            path_info["elastic_position_mult"] = round(_mult, 6)
                            path_info["elastic_t_max"] = _elastic.get("t_max", 0.0)
                            path_info["elastic_rebound_risk"] = _elastic.get("rebound_risk", 0.0)
                        _hjb = _pi.get("hjb_policy") or _pi.get("hjb_result")
                        if _hjb is not None:
                            path_info["hjb_policy"] = _hjb

                        opt_dir = optimal.get("direction", "")
                        if opt_dir in ("long", "short") and optimal.get(
                            "validated", False
                        ):
                            path_info["d_star_adjusted"] = opt_dir
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

            path_info["ri_adjusted"] = ri

        except Exception as e:
            logger.warning("[PathLayer] %s 路径发现层 crash: %s\n%s", symbol, e, traceback.format_exc())

        return path_info
