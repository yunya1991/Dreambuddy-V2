"""代理模块：S5 NarrativeAnalyzer.build_narratives（ops/nanoclaw/core_task1 深路径薄封装）。

对外统一函数名：build_narratives(news_list: List[Dict], *, event_ledger: Optional[List[Dict]] = None) -> Dict
  · 返回值语义：
      {
        "narratives": [{
            "name": str, "trajectory": float∈[-1,+1],  # 方向/速度合成（+1=上升加速,-1=下降加速）
            "heat_score": float∈[0,1],
            "lifecycle": str,  # birth/growth/maturity/decline
            "top_assets": List[str], "event_count": int,
        }, ...],
        "regulation_policy_traj": float∈[-1,+1],  # 专用于天维度政策项
        "regulation_policy_heat": float∈[0,1],
      }

FAIL-OPEN：任何异常 → 返回 {"narratives": [], "regulation_policy_traj": 0.0, "regulation_policy_heat": 0.0}。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_THIS_DIR = Path(__file__).resolve().parent
_NARR_SCRIPTS = _THIS_DIR.parent / "ops" / "nanoclaw" / "core_task1" / "narrative" / "scripts"
_OP_CORE = _THIS_DIR.parent / "ops" / "nanoclaw" / "core_task1"
_OP_SCRIPTS = _OP_CORE / "scripts"
for _p in (str(_NARR_SCRIPTS), str(_OP_SCRIPTS), str(_OP_CORE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


_DEFAULT_OUT: Dict[str, Any] = {
    "narratives": [],
    "regulation_policy_traj": 0.0,
    "regulation_policy_heat": 0.0,
}


def build_narratives(
    news_list: List[Dict[str, Any]],
    *,
    event_ledger: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not isinstance(news_list, list):
        return dict(_DEFAULT_OUT)
    try:
        from narrative_analyzer import NarrativeAnalyzer  # type: ignore
    except Exception:
        return dict(_DEFAULT_OUT)
    try:
        # NarrativeAnalyzer 构造通常接受 event_list/news_list
        analyzer: Any = None
        # 尝试：1) NarrativeAnalyzer(news_list=..., event_ledger=...)
        for kwargs in (
            {"news_list": list(news_list), "event_ledger": list(event_ledger or [])},
            {"events": list(news_list)},
            {"news_items": list(news_list)},
            {},
        ):
            try:
                analyzer = NarrativeAnalyzer(**kwargs)
                break
            except Exception:
                continue
        if analyzer is None:
            return dict(_DEFAULT_OUT)
        # feed 退化：若构造时未注入，尝试 feed 方法
        if isinstance(news_list, list) and news_list:
            for api_name in ("feed_news", "add_events", "ingest"):
                api = getattr(analyzer, api_name, None)
                if callable(api):
                    try:
                        api(news_list)
                    except Exception:
                        pass
        result: Any = None
        build = getattr(analyzer, "build_narratives", None)
        if callable(build):
            try:
                result = build()
            except Exception:
                result = None
        if result is None:
            analyze = getattr(analyzer, "analyze", None)
            if callable(analyze):
                try:
                    result = analyze()
                except Exception:
                    result = None
        return _coerce(result)
    except Exception:
        return dict(_DEFAULT_OUT)


def _coerce(v: Any) -> Dict[str, Any]:
    out = dict(_DEFAULT_OUT)
    if isinstance(v, list):
        out["narratives"] = [x for x in v if isinstance(x, dict)]
        if not out["narratives"]:
            # 允许列表是叙事对象 dataclass；尝试 asdict
            try:
                from dataclasses import asdict
                out["narratives"] = [asdict(x) for x in v if hasattr(x, "__dataclass_fields__")]
            except Exception:
                pass
    elif isinstance(v, dict):
        narr = v.get("narratives")
        if isinstance(narr, list):
            out["narratives"] = [x for x in narr if isinstance(x, dict)]
        for k_src, k_dst, default in (
            ("regulation_policy_traj", "regulation_policy_traj", 0.0),
            ("regulation_policy_heat", "regulation_policy_heat", 0.0),
            ("traj", "regulation_policy_traj", 0.0),
            ("heat", "regulation_policy_heat", 0.0),
        ):
            if k_src in v and isinstance(v[k_src], (int, float)):
                out[k_dst] = float(v[k_src])
        # 兜底：从第一个 regulation_policy 叙事抽 heat/traj
        if out["regulation_policy_heat"] == 0.0:
            for n in out["narratives"]:
                if not isinstance(n, dict):
                    continue
                nm = str(n.get("id") or n.get("name") or n.get("key") or "").lower()
                if "regul" in nm or "polic" in nm:
                    h = n.get("heat_score") or n.get("heat") or 0.0
                    t = n.get("trajectory") or n.get("traj") or n.get("trend") or 0.0
                    if isinstance(h, (int, float)):
                        out["regulation_policy_heat"] = float(max(0.0, min(1.0, h)))
                    if isinstance(t, (int, float)):
                        out["regulation_policy_traj"] = float(max(-1.0, min(1.0, t)))
                    break
    return out
