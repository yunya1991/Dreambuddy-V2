#!/usr/bin/env python3
"""mcp_shells/l0_store_admin/server.py — L0 库管壳只读（M4⑩）

SPEC-L0-MCP-PACKAGING §3.3 + registry mcp_capabilities.yaml（l0.store-admin.mcp）
工具面（2 个，注册表登记，全部只读）：
  - store_admin_status  (read)  库管健康状态（19-DAL 6 repo 工厂可用性枚举）
  - store_admin_query   (read)  只读查询（按 repo 分派：trade/position/risk）

硬约束：
  - 壳内零业务逻辑：协议解析 → DAL 工厂/只读方法调用 → 信封映射 三段
  - 库管只读（D2）：本壳不提供任何写工具；写治理走 l0_data 壳 Ban+Mandate 通道
  - 数据访问一律经 19-DAL Repository 协议（消费方唯一导入入口 __init__.py），壳不感知后端
  - stdio JSON-RPC 2.0，按需拉起，不常驻
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

# 壳进程 import 规约（SPEC §3.4）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l0.store-admin.mcp"

# 19-DAL 消费方唯一导入入口（dreambuddy_dal/__init__.py 对外 6 工厂）
_DAL_ROOT = _REPO_ROOT / "19-数据访问层"

# repo 名 → 工厂函数名（19-DAL __init__.py 导出）
_REPO_FACTORIES = {
    "trade": "get_trade_repo",
    "position": "get_position_repo",
    "market_macro": "get_market_macro_repo",
    "risk": "get_risk_repo",
    "config": "get_config_repo",
    "kg": "get_kg_repo",
}

# query 工具支持的只读分派（repo → 只读方法）
_QUERY_REPOS = {"trade", "position", "risk"}


def _get_dal():
    """导入 19-DAL 包（消费方唯一导入入口），返回模块。"""
    if str(_DAL_ROOT) not in sys.path:
        sys.path.insert(0, str(_DAL_ROOT))
    import dreambuddy_dal

    return dreambuddy_dal


def _handle_status(args: Dict[str, Any]) -> str:
    """store_admin_status：库管健康状态（19-DAL 6 repo 工厂可用性枚举）。"""
    repos = {}
    try:
        dal = _get_dal()
        for name, factory in _REPO_FACTORIES.items():
            try:
                getattr(dal, factory)()
                repos[name] = "ok"
            except Exception as e:
                repos[name] = f"error: {e}"
        return json.dumps(
            wrap({"shell": SHELL_SOURCE, "mode": "read-only", "repos": repos}, SHELL_SOURCE),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            wrap(
                {"shell": SHELL_SOURCE, "mode": "read-only", "repos": repos},
                SHELL_SOURCE,
                degraded=True,
                error_code="unavailable",
                meta={"reason": str(e)},
            ),
            ensure_ascii=False,
        )


def _handle_query(args: Dict[str, Any]) -> str:
    """store_admin_query：只读查询（按 repo 分派，经 19-DAL Repository 协议）。"""
    repo = str(args.get("repo") or "").strip()
    if not repo:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": "repo is required (trade/position/risk)"},
            ),
            ensure_ascii=False,
        )
    if repo not in _QUERY_REPOS:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": f"unsupported repo: {repo}; supported: {sorted(_QUERY_REPOS)}"},
            ),
            ensure_ascii=False,
        )
    try:
        limit = min(int(args.get("limit", 100)), 1000)
    except (TypeError, ValueError):
        limit = 100
    symbol = args.get("symbol") or None
    try:
        dal = _get_dal()
        if repo == "trade":
            rows = dal.get_trade_repo().query_trades(symbol=symbol, limit=limit)
        elif repo == "position":
            rows = dal.get_position_repo().list_positions(symbol=symbol)
        else:  # risk
            rows = dal.get_risk_repo().query_cases(symbol=symbol, limit=limit)
        # 统一模型 dataclass → dict（信封 JSON 序列化）
        items = []
        for r in rows:
            if hasattr(r, "__dict__"):
                items.append(vars(r))
            else:
                items.append(r)
        return json.dumps(
            wrap({"repo": repo, "count": len(items), "items": items}, SHELL_SOURCE),
            ensure_ascii=False,
            default=str,
        )
    except Exception as e:
        return json.dumps(
            wrap(
                None, SHELL_SOURCE, degraded=True, error_code="unavailable", meta={"reason": str(e)}
            ),
            ensure_ascii=False,
        )


TOOL_DEFS = {
    "store_admin_status": {
        "description": "Store admin health status (19-DAL repo factory availability)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "store_admin_query": {
        "description": (
            "Read-only query via 19-DAL Repository protocol (repo: trade/position/risk)"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "enum": ["trade", "position", "risk"]},
                "limit": {"type": "integer"},
            },
            "required": ["repo"],
        },
    },
}

TOOL_HANDLERS = {
    "store_admin_status": _handle_status,
    "store_admin_query": _handle_query,
}


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, TOOL_DEFS, TOOL_HANDLERS)
