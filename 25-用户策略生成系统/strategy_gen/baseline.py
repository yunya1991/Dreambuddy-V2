"""
25-用户策略生成系统 - 基线策略库

内置基线策略集合（classic_10_strategies + 注册表 tier≥B），
作为策略知识库供 AI 参考和用户对比。基线策略只读。

通过 HTTP 调用 M26 策略管理模块的 registry API 获取策略数据。
FAIL-OPEN：M26 不可用时返回空列表，不阻断 M25 其他功能。
"""
import json
import os
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

# M26 策略管理模块地址
_STRATEGY_LIB_BASE = os.environ.get("STRATEGY_LIB_BASE", "http://127.0.0.1:8093")

# 基线策略来源
_BASELINE_SOURCES = [
    "classic_10_strategies",  # 内置经典10策略
    "registry_tier_ab",        # 注册表中 tier>=B 的策略
]

# 内存缓存（60 秒）
_CACHE_TTL = 60.0
_cache: Dict[str, Any] = {"ts": 0.0, "data": []}


def _http_get_json(url: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """发送 GET 请求并解析 JSON。失败返回 None（FAIL-OPEN）。"""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, ValueError):
        return None


def _fetch_from_registry() -> List[Dict[str, Any]]:
    """从 M26 registry 拉取 tier≥B 的策略列表。"""
    url = f"{_STRATEGY_LIB_BASE}/api/v1/lib/strategies?tier=A,B"
    data = _http_get_json(url)
    if not data or not data.get("ok"):
        return []
    entries = data.get("entries") or []
    items: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        items.append({
            "strategy_id": entry.get("strategy_id"),
            "source_zip": entry.get("source_zip"),
            "family": entry.get("family"),
            "stage": entry.get("stage"),
            "tier": entry.get("tier"),
            "tags": entry.get("tags", []),
            "updated_at": entry.get("updated_at"),
            "metrics_summary": None,  # list 接口不含 metrics，get 时再取
        })
    return items


def baseline_list() -> List[Dict[str, Any]]:
    """列出所有基线策略（tier≥B），带 60 秒内存缓存。"""
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]
    items = _fetch_from_registry()
    _cache["ts"] = now
    _cache["data"] = items
    return items


def baseline_get(strategy_id: str, source_zip: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """获取单个基线策略详情（含 metrics_summary）。"""
    params = []
    if source_zip:
        params.append(f"source_zip={urllib.request.quote(source_zip)}")
    qs = f"?{'&'.join(params)}" if params else ""
    url = f"{_STRATEGY_LIB_BASE}/api/v1/lib/strategies/{urllib.request.quote(strategy_id)}{qs}"
    data = _http_get_json(url)
    if not data or not data.get("ok"):
        return None
    entry = data.get("entry")
    if not isinstance(entry, dict):
        return None
    return {
        "strategy_id": entry.get("strategy_id"),
        "source_zip": entry.get("source_zip"),
        "family": entry.get("family"),
        "stage": entry.get("stage"),
        "tier": entry.get("tier"),
        "tags": entry.get("tags", []),
        "updated_at": entry.get("updated_at"),
        "metrics_summary": entry.get("metrics_summary"),
    }


def baseline_metrics(strategy_id: str, source_zip: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """获取基线策略的回测指标。"""
    entry = baseline_get(strategy_id, source_zip)
    if entry:
        return entry.get("metrics_summary")
    return None
