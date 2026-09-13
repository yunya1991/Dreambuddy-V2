"""FearGreedChart 增强 F&G 采集器 — 免费 REST API，含链上组件。

数据源: https://crypto.feargreedchart.com/api/?action=crypto
- 无需 Key，CORS 支持
- 综合F&G(0-100) + 链上组件(MVRV/NUPL/SOPR) + funding + stablecoin + altseason + divergence

用于 AGI 蓝图 L1 感知层增强情绪指标，与 alternative.me F&G 交叉验证。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_BASE = "https://crypto.feargreedchart.com/api/"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class FearGreedEnhancedCollector(BaseCollector):
    """增强版 F&G 指数采集器（含链上组件）。"""

    source = "fear_greed_enhanced"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 免费 API

    def fetch(self, params: dict) -> list[DataRecord]:
        action = params.get("action", "crypto")
        try:
            resp = requests.get(_BASE, params={"action": action}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []  # fail-open

        result = data if isinstance(data, dict) else {}

        # 提取扁平 metrics（综合F&G + 各组件）
        metrics: dict[str, float | str] = {}

        # 综合 F&G
        fg_value = result.get("value") or result.get("fear_greed_value")
        if fg_value is not None:
            try:
                metrics["fear_greed_value"] = float(fg_value)
            except (ValueError, TypeError):
                pass

        fg_class = result.get("value_classification") or result.get("classification")
        if fg_class:
            metrics["fear_greed_classification"] = str(fg_class)

        # 链上组件
        components = result.get("components") or {}
        if isinstance(components, dict):
            for comp_name, comp_data in components.items():
                if isinstance(comp_data, dict):
                    val = comp_data.get("value")
                    if val is not None:
                        try:
                            metrics[comp_name] = float(val)
                        except (ValueError, TypeError):
                            pass
                elif isinstance(comp_data, (int, float, str)):
                    try:
                        metrics[comp_name] = float(comp_data)
                    except (ValueError, TypeError):
                        pass

        # 直接字段（非标准嵌套结构）
        for key in ("mvrv", "nupl", "sopr", "funding", "stablecoin", "altseason", "divergence"):
            if key in result:
                val = result[key]
                try:
                    metrics[key] = float(val) if isinstance(val, (int, float, str)) else str(val)[:100]
                except (ValueError, TypeError):
                    metrics[key] = str(val)[:100]

        if not metrics:
            return []

        rec = DataRecord(
            source="fear_greed_enhanced",
            category="chain",
            sub_category="fear_greed_enhanced",
            timestamp=_now_iso(),
            metrics=metrics,
            events=[],
            timeseries=[],
            raw={"source": "crypto.feargreedchart.com", "data": result},
        )
        validate_record(rec)
        return [rec]
