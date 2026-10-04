"""配置读取函数（从 ml_trade_service.py 抽取）

所有 _cfg_* 函数集中于此。CONFIG 通过 set_config() 在启动时注入，
避免循环导入：ml_trade_service 在定义 CONFIG 后调用 set_config(CONFIG)。
"""

import math
from typing import Any, Dict, Optional

_CONFIG: Dict[str, Any] = {}


def set_config(cfg: Dict[str, Any]) -> None:
    """注入 CONFIG 字典（由 ml_trade_service 在定义 CONFIG 后调用）"""
    global _CONFIG
    _CONFIG = cfg if isinstance(cfg, dict) else {}


def _cfg_key_slug(s: Any) -> str:
    if s is None:
        return ""
    ss = str(s)
    out = []
    for ch in ss:
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_")


def _cfg_float_opt(key: str) -> Optional[float]:
    try:
        v = _CONFIG.get(str(key))
    except Exception:
        v = None
    if v is None:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    if not math.isfinite(float(x)):
        return None
    return float(x)


def _cfg_bool_opt(key: str) -> Optional[bool]:
    try:
        v = _CONFIG.get(str(key))
    except Exception:
        v = None
    if v is None:
        return None
    if isinstance(v, bool):
        return bool(v)
    try:
        s = str(v).strip().lower()
    except Exception:
        return None
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


def _cfg_int_opt(key: str) -> Optional[int]:
    try:
        v = _CONFIG.get(str(key))
    except Exception:
        v = None
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _cfg_str_opt(key: str) -> Optional[str]:
    try:
        v = _CONFIG.get(str(key))
    except Exception:
        v = None
    if v is None:
        return None
    try:
        s = str(v).strip()
    except Exception:
        return None
    return (s if s else None)


def _cfg_loss_limit_pct(system_id: str, kind: str, default: float) -> float:
    s = str(system_id or "").strip().lower() or "strategy"
    k = str(kind or "").strip().lower()
    if k not in ("daily", "weekly"):
        return float(default)
    key0 = f"{s}_max_{k}_loss"
    v = _CONFIG.get(key0)
    if v is None:
        v = _CONFIG.get(f"max_{k}_loss")
    try:
        vv = float(v) if v is not None else float(default)
        return vv if math.isfinite(vv) else float(default)
    except Exception:
        return float(default)


def _cfg_account_loss_limit_pct(kind: str, default: float) -> float:
    k = str(kind or "").strip().lower()
    if k not in ("daily", "weekly"):
        return float(default)
    v = _CONFIG.get(f"account_max_{k}_loss")
    if v is None:
        v = _CONFIG.get(f"max_{k}_loss")
    try:
        vv = float(v) if v is not None else float(default)
        return vv if math.isfinite(vv) else float(default)
    except Exception:
        return float(default)


def _cfg_inherit_bool(v: Any, default: bool) -> bool:
    if v is None:
        return bool(default)
    try:
        return bool(v)
    except Exception:
        return bool(default)


__all__ = [
    "set_config",
    "_cfg_key_slug",
    "_cfg_float_opt",
    "_cfg_bool_opt",
    "_cfg_int_opt",
    "_cfg_str_opt",
    "_cfg_loss_limit_pct",
    "_cfg_account_loss_limit_pct",
    "_cfg_inherit_bool",
]
