"""P1-2 拆分组件: ResultAggregator

从 kline_event_handler.py 拆出的结果聚合 + bridge回调 + L3/L4反馈职责。

来源: SPEC v0.3 §2.B — kline_event_handler 多职责缝合体拆分
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ResultAggregator:
    """结果聚合器 — 从 KlineEventHandler 拆出的内聚组件.

    职责:
      1. trigger_build_position: 建仓回调（FAIL-OPEN）
      2. apply_macro_event_filter: 宏观事件过滤器（双层门控）
      3. store_pre_trade_snapshot: 交易前快照存储
      4. get_evolution_feedback: L3/L4 反馈摘要
      5. attach_trader: trader 注入
    """

    def __init__(
        self,
        build_position_callback: Any = None,
        settlement_bridge: Any = None,
        pipeline: Any = None,
        router: Any = None,
    ) -> None:
        self._build_position_callback = build_position_callback
        self._bridge = settlement_bridge
        self._pipeline = pipeline
        # 延迟创建 EngineRouter
        if router is not None:
            self._router = router
        else:
            from dreambuddy_evolution.engines.engine_router import EngineRouter
            self._router = EngineRouter()
        self._trader: Any = None
        # 方向预测透传（从 store_pre_trade_snapshot 读取）
        self._last_dimension_predictions: dict = {}

    def attach_trader(self, trader: Any) -> None:
        """注入 trader 引用。"""
        self._trader = trader

    def _get_bridge(self) -> Any:
        """延迟初始化 TradeSettlementBridge"""
        if self._bridge is None:
            from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
            self._bridge = TradeSettlementBridge(pipeline=self._pipeline)
        return self._bridge

    # ------------------------------------------------------------------
    # 建仓回调
    # ------------------------------------------------------------------
    def trigger_build_position(
        self,
        symbol: str,
        action: str,
        d_star: str,
        ri: float,
        position_mult: float = 1.0,
        tier: str = "standard",
        source_tag: str | None = None,
    ) -> None:
        """调用建仓回调（FAIL-OPEN）"""
        if self._build_position_callback is None:
            return
        try:
            cb_kwargs = dict(
                symbol=symbol,
                action=action,
                u_open=position_mult,
                d_star=d_star,
                confidence=ri,
                tier=tier,
            )
            if source_tag is not None:
                cb_kwargs["source_tag"] = source_tag
            self._build_position_callback(**cb_kwargs)
        except Exception as e:
            logger.warning("[FO] build_position_callback crash: %s", e)

    # ------------------------------------------------------------------
    # 交易前快照
    # ------------------------------------------------------------------
    def store_pre_trade_snapshot(
        self,
        symbol: str,
        action: str,
        d_star: str,
        ess_dir: str,
        ri: float,
        position_mult: float = 1.0,
    ) -> None:
        """存储 pre_trade_snapshot（FAIL-OPEN）"""
        try:
            from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
            dim_predictions = getattr(self._router, "_last_dimension_predictions", {}) or {}
            snapshot = ReflectionEngine().create_snapshot(
                symbol=symbol,
                u_open=position_mult,
                action=action,
                level0_dstar=d_star,
                ess_id="",
                ess_dir=ess_dir,
                cbr_sim=0.5,
                cbr_top1_outcome="TP",
                cluster_id="",
                dimension_predictions=dim_predictions,
            )
            self._get_bridge().store_snapshot(symbol, snapshot)
        except Exception as e:
            logger.warning("[FO] store_pre_trade_snapshot crash: %s", e)

    # ------------------------------------------------------------------
    # 宏观事件过滤器
    # ------------------------------------------------------------------
    def apply_macro_event_filter(
        self,
        kline_data: dict[str, Any],
        action: str,
        d_star: str,
        ri: float,
    ) -> tuple[str | None, float, dict[str, Any]]:
        """宏观事件过滤器（断点1b/3）— 事件驱动层 + conviction-based tier 双层门控.

        Returns:
            (macro_dir, conviction, macro_info) 三元组
            - macro_dir: 宏观方向（long/short/None）
            - conviction: 宏观置信度 [0,1]
            - macro_info: 详细信息字典
        """
        inactive = ("", 0.0, {
            "active": False, "filter_level": "soft",
            "direction": "", "conviction": 0.0,
            "position_params": None, "adjusted_params": None,
        })
        try:
            from dreambuddy_evolution.agi_config import is_enabled
            if not is_enabled("enable_contradiction_driven_layer"):
                return inactive
            ec = kline_data.get("event_context") or {}
            if not isinstance(ec, dict):
                return inactive
            if not ec.get("in_fomc_cycle", False):
                return inactive
            if not ec.get("post_event", False):
                return inactive
            priced_in = float(ec.get("priced_in_score", 0.0) or 0.0)
            if priced_in < 0.75:
                return inactive
            macro_dir = str(ec.get("macro_direction", "") or "").lower()
            if macro_dir not in ("long", "short"):
                macro_dir = str(kline_data.get("ess_top_direction", "") or "").lower()
            if macro_dir not in ("long", "short"):
                return inactive
            conviction = max(0.5, min(1.0, priced_in))
            if conviction >= 0.75:
                macro_tier = "trend_set"
                position_scale = 1.20
            elif conviction >= 0.65:
                macro_tier = "standard"
                position_scale = 1.00
            else:
                macro_tier = "probe"
                position_scale = 0.80
            macro_info = {
                "active": True,
                "filter_level": "soft",
                "direction": macro_dir,
                "conviction": conviction,
                "priced_in_score": priced_in,
                "position_params": {
                    "position_scale": position_scale,
                    "tier": macro_tier,
                },
                "adjusted_params": None,
            }
            logger.debug(
                "[MacroFilter] %s active dir=%s conf=%.2f priced_in=%.2f tier=%s",
                kline_data.get("symbol", "?"), macro_dir, conviction, priced_in, macro_tier,
            )
            return macro_dir, conviction, macro_info
        except Exception as e:
            logger.warning("[FO] apply_macro_event_filter crash: %s", e)
            return inactive

    # ------------------------------------------------------------------
    # L3/L4 反馈
    # ------------------------------------------------------------------
    def get_evolution_feedback(self) -> dict[str, Any]:
        """L3/L4 回馈摘要（委托 EvolutionPipeline.get_feedback）.

        FAIL-OPEN: pipeline 不可用时返回空摘要。
        """
        try:
            _pipeline = self._router.get_evolution_pipeline()
            if _pipeline is not None and hasattr(_pipeline, "get_feedback"):
                return _pipeline.get_feedback()
        except Exception as _e:
            logger.warning("[FO] get_evolution_feedback crash: %s", _e)
        return {"l3_stats": {}, "l4_v_all": {}, "l4_ess_adjustments": {}}
