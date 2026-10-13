"""
26-策略管理模块 - 产品中台数据同步

将 M26 registry 中的策略元数据（含回测结果）同步到 7-产物中台（Prisma 策略库），
消除数据孤岛。

设计原则：
- 单向推送（M26 → 产品中台），M26 为策略元数据 source of truth
- FAIL-OPEN：产品中台不可用时不阻断 M26 主流程
- 字段映射：M26 registry entry → 产品中台 RecommendedStrategyWrite
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from . import registry as reg

# 产品中台地址
_PRODUCT_HUB_BASE = os.environ.get("PRODUCT_HUB_BASE", "http://127.0.0.1:3456")
# 产品中台内部 API Key（未设置时开发环境放行）
_PRODUCT_HUB_API_KEY = os.environ.get("PRODUCT_HUB_API_KEY", "")

# tier → library_score 映射
_TIER_SCORE = {"S": 100, "A": 90, "B": 75, "C": 50, "D": 30}


def _tier_to_library_score(tier: Optional[str]) -> int:
    return _TIER_SCORE.get(str(tier or "").strip().upper(), 0)


def _map_entry_to_product_hub_strategy(entry: Dict[str, Any]) -> Dict[str, Any]:
    """将 M26 registry entry 映射为产品中台 RecommendedStrategyWrite 格式。"""
    strategy_id = str(entry.get("strategy_id") or "").strip()
    backtest_spec = entry.get("backtest_spec") if isinstance(entry.get("backtest_spec"), dict) else {}
    metrics = backtest_spec.get("metrics_summary") if isinstance(backtest_spec.get("metrics_summary"), dict) else {}
    tier = str(entry.get("tier") or "").strip().upper()

    is_in_library = tier in ("S", "A", "B")

    return {
        "name": strategy_id,
        "description": str(entry.get("description") or f"M26 registry strategy {strategy_id}"),
        "direction": "LONG" if "long" in str(entry.get("family") or "").lower() else "SHORT",
        "symbol": "BTC/USDT",
        "tradeType": "MARTINGALE",
        "leverage": 1,
        "positionSize": 60,
        "confidence": None,
        "status": "APPROVED" if is_in_library else "PENDING",
        "regime": str(entry.get("family") or "trend"),
        "source": "m26-registry",
        # 回测性能
        "backtestSharpe": float(metrics.get("sharpe_ratio", 0) or 0),
        "backtestMaxDrawdown": float(metrics.get("max_drawdown_pct", 0) or 0),
        "backtestWinRate": float(metrics.get("winrate", 0) or 0),
        "backtestProfitFactor": float(metrics.get("profit_factor", 0) or 0),
        "backtestTotalReturn": float(metrics.get("profit_total_pct", 0) or 0),
        "backtestPeriod": "20260422-20260721",
        "backtestDate": str(backtest_spec.get("backtest_ts") or ""),
        # 基线对比（暂用默认值，后续接入 baseline 对比）
        "baselineVersion": "v15",
        "baselineSharpe": 0.67,
        "baselineMaxDrawdown": 4.62,
        "baselineTotalReturn": 23.80,
        "isBetterThanBaseline": float(metrics.get("sharpe_ratio", 0) or 0) >= 0.67,
        # 策略库
        "isInLibrary": is_in_library,
        "libraryScore": _tier_to_library_score(tier) if is_in_library else 0,
        "libraryActive": is_in_library,
        # 来源
        "sourceEngine": "m26-registry",
        "sourceReportIds": None,
        # 迭代
        "generation": 1,
        "parentStrategyId": None,
        # 推荐天数
        "recommendedDays": 0,
    }


def _http_post_json(url: str, payload: Dict[str, Any], timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """发送 POST JSON 请求。失败返回 None（FAIL-OPEN）。"""
    try:
        headers = {"Content-Type": "application/json"}
        if _PRODUCT_HUB_API_KEY:
            headers["X-Internal-Api-Key"] = _PRODUCT_HUB_API_KEY
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, ValueError, Exception):
        return None


def sync_strategies_to_product_hub() -> Dict[str, Any]:
    """将 M26 registry 中 tier>=C 的策略同步到产品中台。

    Returns:
        {"ok": bool, "synced": int, "skipped": int, "errors": [...]}
    """
    data = reg._strategy_registry_load()
    entries = data.get("entries") if isinstance(data.get("entries"), dict) else {}

    synced = 0
    skipped = 0
    errors: List[str] = []

    for key, entry in entries.items():
        if not isinstance(entry, dict):
            skipped += 1
            continue
        strategy_id = str(entry.get("strategy_id") or "").strip()
        if not strategy_id:
            skipped += 1
            continue
        tier = str(entry.get("tier") or "").strip().upper()
        if tier not in ("S", "A", "B", "C"):
            skipped += 1
            continue

        # 映射字段
        strategy = _map_entry_to_product_hub_strategy(entry)
        payload = {"action": "create_strategy", "strategy": strategy}
        result = _http_post_json(f"{_PRODUCT_HUB_BASE}/api/recommendation-engine/internal/strategy", payload)
        if result and result.get("success"):
            synced += 1
        else:
            errors.append(f"{strategy_id}: sync_failed")

    return {
        "ok": len(errors) == 0,
        "synced": synced,
        "skipped": skipped,
        "total": len(entries),
        "errors": errors[:20],
    }
