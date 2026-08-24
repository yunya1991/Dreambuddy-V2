#!/usr/bin/env python3
"""token_pool_loader.py — 公共代币池加载器（方案B：运行时读取）

单一数据源: {PROJECT_ROOT}/config/token_registry.json
子系统启动时读取，8h自动刷新内存中的币种列表。
.env / 命令行参数仅作 override（测试/特定运行时覆盖公共池）。

加载优先级: 环境变量(override) > token_registry.json > 硬编码默认
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional

# 项目根目录: lib/ → parent = 14-V15经典马丁策略/ → parent = 项目根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_REGISTRY_PATHS = [
    Path(os.environ.get("TOKEN_REGISTRY_PATH", ""))
    if os.environ.get("TOKEN_REGISTRY_PATH")
    else None,
    _PROJECT_ROOT / "config" / "token_registry.json",
]

REGISTRY_TTL = 28800  # 8小时

_cache: dict = {"symbols": None, "ts": 0.0}


def load_registry_symbols() -> Optional[List[str]]:
    """从 token_registry.json 加载启用的币种列表。文件不存在/损坏时返回 None。"""
    for p in _REGISTRY_PATHS:
        if p is None or not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            tokens = data.get("tokens", [])
            syms: List[str] = []
            for t in tokens:
                if isinstance(t, dict):
                    if not t.get("enabled", True):
                        continue
                    s = str(t.get("symbol", "")).strip().upper()
                    if s:
                        syms.append(s)
                elif isinstance(t, str) and t.strip():
                    syms.append(t.strip().upper())
            if syms:
                return syms
        except Exception:
            continue
    return None


def get_pool_symbols(ttl: float = REGISTRY_TTL) -> Optional[List[str]]:
    """获取币种列表（TTL缓存）。未到 TTL 返回缓存，过期则重读文件。"""
    now = time.time()
    if _cache["symbols"] is not None and (now - _cache["ts"]) < ttl:
        return _cache["symbols"]
    new = load_registry_symbols()
    if new is not None:
        _cache["symbols"] = new
        _cache["ts"] = now
    return _cache["symbols"]


def invalidate_cache() -> None:
    """手动失效缓存（下次 get_pool_symbols 强制重读文件）。"""
    _cache["symbols"] = None
    _cache["ts"] = 0.0


def load_coins_with_override(
    env_var: str,
    hardcoded_default: List[str],
) -> List[str]:
    """加载币种: 环境变量(override) > token_registry.json > 硬编码默认。

    Args:
        env_var: 环境变量名（如 V15_COINS），值为逗号分隔的币种列表
        hardcoded_default: 公共池不存在时的兜底默认列表

    Returns:
        币种列表（大写）
    """
    env_val = os.environ.get(env_var, "")
    if env_val:
        return [c.strip().upper() for c in env_val.split(",") if c.strip()]
    registry = load_registry_symbols()
    if registry:
        return registry
    return [c.upper() for c in hardcoded_default]
