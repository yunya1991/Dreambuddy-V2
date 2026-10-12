"""P1-2 拆分组件: EventReceiver

从 kline_event_handler.py 拆出的 K线事件接收 + L1 R向量 + AGI-A签名 + 事件驱动状态职责。

来源: SPEC v0.3 §2.B — kline_event_handler 多职责缝合体拆分
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class EventReceiver:
    """K线事件接收器 — 从 KlineEventHandler 拆出的内聚组件.

    职责:
      1. receive_kline: L1 R向量计算 + AGI-A 路径签名
      2. write_event_driven_state: 事件驱动策略影子模式状态写入
    """

    def __init__(self, mode: str = "MVP", router: Any = None) -> None:
        self.mode = mode
        # 延迟创建 EngineRouter，避免循环导入
        if router is not None:
            self._router = router
        else:
            from dreambuddy_evolution.engines.engine_router import EngineRouter
            self._router = EngineRouter()

    def receive_kline(
        self,
        kline_data: dict[str, Any],
        rv: Any = None,
        router: Any = None,
    ) -> dict[str, Any]:
        """接收 K线收盘事件 → L1 R向量 + AGI-A 签名.

        Args:
            kline_data: K线数据 dict
            rv: ResistanceVector 实例
            router: 可选 EngineRouter（覆盖 self._router）

        Returns:
            dict 含 symbol / r_vector / agi_signature
        """
        symbol = str(kline_data.get("symbol", "UNKNOWN"))
        _router = router or self._router

        # ============ 1. L1 R 向量计算 ============
        r_vector = rv.calculate(symbol, kline_data) if rv is not None else {}

        # ============ AGI 增强点 A: SignatureEngine 路径签名（只读） ============
        agi_signature = None
        try:
            closes_raw = kline_data.get("close", [])
            if isinstance(closes_raw, (list, np.ndarray)) and len(closes_raw) >= 10:
                sig_engine = _router.get_sig_engine()
                if sig_engine is not None:
                    path = np.array(closes_raw, dtype=float)
                    sig = _router.agi_enhance(
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

        return {
            "symbol": symbol,
            "r_vector": r_vector,
            "agi_signature": agi_signature,
        }

    def write_event_driven_state(
        self,
        kline_data: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """将 EventSignal 写入 JSON 状态文件（跨进程通信 · 影子模式）.

        供 11-易经推理系统/data_server_fixed.py 的 GET /api/event-driven 接口读取。
        影子模式：仅评估 + 写状态文件，不影响 on_kline_close 主链路的 d* 决策。

        FAIL-OPEN：写入失败不影响主链路。
        """
        try:
            repo_root = Path(__file__).resolve().parents[3]
            state_path = repo_root / "11-易经推理系统" / "data" / "event_driven_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)

            # 影子模式评估 EventSignal
            strategy = self._router.get_event_driven_strategy()
            signal_dict: dict = {}
            if strategy is not None:
                try:
                    signal = strategy.evaluate(kline_data)
                    signal_dict = signal.to_dict() if hasattr(signal, "to_dict") else {}
                except Exception as e:
                    logger.warning("[EventDriven] evaluate() crash (FAIL-OPEN): %s", e)
                    signal_dict = {"signal": "neutral", "reason": f"evaluate_fail: {e}"}

            # 提取 close price
            closes = kline_data.get("close", [])
            close_price = None
            try:
                if closes is None:
                    close_price = None
                elif hasattr(closes, "__len__") and len(closes) > 0:
                    close_price = float(closes[-1])
                else:
                    close_price = float(closes) if closes else None
            except (TypeError, ValueError):
                close_price = None

            # enable_event_dominance 开关
            event_dominance: dict = {}
            try:
                from dreambuddy_evolution.agi_config import get_switch as _gs_ed
                if _gs_ed("enable_event_dominance", False):
                    from event_driven.event_dominance_controller import EventDominanceController
                    _edc = EventDominanceController()
                    _conviction = float(signal_dict.get("conviction", 0.5))
                    _macro_dir = str(signal_dict.get("macro_direction", "neutral"))
                    _data_quality = float(signal_dict.get("data_quality", 1.0))
                    _in_fomc = bool(signal_dict.get("in_fomc_cycle", True))
                    _dd = _edc.decide(
                        conviction=_conviction,
                        macro_direction=_macro_dir,
                        data_quality=_data_quality,
                        in_fomc_cycle=_in_fomc,
                    )
                    event_dominance = _dd.to_dict() if hasattr(_dd, "to_dict") else {
                        "filter_level": getattr(_dd, "filter_level", "none"),
                        "active": getattr(_dd, "active", False),
                    }
            except Exception as _e:
                logger.debug("[EventDominance] FAIL-OPEN: %s", _e)

            state = {
                "updated_at": datetime.now().isoformat(),
                "symbol": str(kline_data.get("symbol", "UNKNOWN")),
                "mode": "shadow",
                "signal": signal_dict,
                "event_dominance": event_dominance,
                "main_chain": {
                    "d_star": result.get("d_star"),
                    "action": result.get("action"),
                    "ri": result.get("ri"),
                    "regime": result.get("regime"),
                },
                "kline": {
                    "close": close_price,
                    "timestamp": kline_data.get("timestamp"),
                },
            }
            # 原子写入：先写临时文件再 os.replace
            tmp_path = state_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp_path, state_path)
            logger.debug(
                "[EventDriven] state written: %s signal=%s",
                state["symbol"],
                signal_dict.get("signal", "n/a"),
            )
        except Exception as e:
            logger.warning("[EventDriven] write_event_driven_state fail (FAIL-OPEN): %s", e)
