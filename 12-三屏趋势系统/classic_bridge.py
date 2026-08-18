"""三屏趋势系统 — 经典指标系统桥接器

作为 12-三屏趋势系统 与 10-经典指标系统 之间的桥梁。

职责：
1. 统一封装对经典系统的 API 调用（端口 8092）
2. 提供入场信号服务（Freqtrade 多策略投票）
3. 提供离场决策服务（ClassicExitSystem）
4. 降级处理：经典系统不可用时返回中性/空结果

设计原则：
- 三屏趋势系统（本模块）负责「趋势方向判定 + 置信度评估」
- 经典指标系统负责「入场时机精选 + 离场执行」
- 两者通过 HTTP API 解耦，可独立部署和演进
"""

import os
from typing import Dict, Optional, Any
from dataclasses import dataclass


CLASSIC_SYSTEM_BASE_ENV = "CLASSIC_SYSTEM_BASE_URL"
DEFAULT_CLASSIC_BASE = "http://127.0.0.1:8092"
DEFAULT_TIMEOUT = 5.0


def get_classic_base_url() -> str:
    """获取经典系统基础 URL"""
    return os.environ.get(CLASSIC_SYSTEM_BASE_ENV, DEFAULT_CLASSIC_BASE).rstrip("/")


def _make_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[Dict] = None,
    json_data: Optional[Dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """
    统一的经典系统 API 请求封装

    返回: {"ok": bool, "data": Any, "error": str}
    """
    try:
        import requests
    except ImportError:
        return {"ok": False, "error": "requests_not_installed", "data": None}

    base = get_classic_base_url()
    url = f"{base}{endpoint}"

    try:
        if method.upper() == "GET":
            resp = requests.get(url, params=params, timeout=timeout)
        elif method.upper() == "POST":
            resp = requests.post(url, params=params, json=json_data, timeout=timeout)
        else:
            return {"ok": False, "error": f"unsupported_method:{method}", "data": None}

        if resp.status_code == 200:
            try:
                data = resp.json()
                return {"ok": True, "data": data, "error": None}
            except Exception:
                return {"ok": True, "data": resp.text, "error": None}
        else:
            return {
                "ok": False,
                "error": f"http_{resp.status_code}",
                "data": resp.text[:500] if resp.text else None,
            }
    except Exception as e:
        return {"ok": False, "error": f"request_error:{str(e)[:200]}", "data": None}


def is_classic_system_available() -> bool:
    """检查经典系统是否可用"""
    result = _make_request("/health", timeout=2.0)
    return result["ok"]
