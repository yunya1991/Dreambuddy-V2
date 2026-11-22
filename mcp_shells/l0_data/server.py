#!/usr/bin/env python3
"""mcp_shells/l0_data/server.py — L0 数据壳（M2⑤）

SPEC-L0-MCP-PACKAGING §3.1 + registry mcp_capabilities.yaml（l0.data.mcp）
工具面（4 个，注册表登记）：
  - data_fetch        (read)  Collector 语义：fetch(scope) 映射 L0 facade fetch_context
  - data_collect_once (read)  Collector 语义：单次采集 status
  - data_store_read  (read)  Store 语义：只读查询（经 DAL，禁裸 SQL）
  - data_store_write (write) 写面 Ban 默认禁（SPEC §3.3），Mandate 授权后开放

硬约束：
  - 壳内零业务逻辑：协议解析 → port/域入口调用 → 信封映射 三段
  - 数据访问一律经 L0 facade / DAL，壳内禁止直连 SQLite 文件
  - 壳默认继承宿主 env，禁止改写 DB_BACKEND（SPEC §3.5）
  - stdio JSON-RPC 2.0，按需拉起，不常驻
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# 壳进程 import 规约（SPEC §3.4）：PYTHONPATH=<repo root> 由宿主注入
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l0.data.mcp"

# 写面 Ban 开关（SPEC §3.3：写工具默认禁用；宿主 Mandate 经 env 授权）
_WRITE_ENABLED = os.environ.get("L0_DATA_WRITE_ENABLED", "0") == "1"

# DAL 显式路径声明（与 l0_store_admin 一致；中文目录名无法直接 import）
_DAL_ROOT = _REPO_ROOT / "19-数据访问层"

# data_store_read 表白名单（禁任意表，仅映射 DAL repo 方法）
_MM_TABLE = "mm_metrics"
# 宏观域其余表：表名 → 只读方法（均需时间窗；带 symbol 的表额外要求 symbol）
_MM_TABLE_SPECS = {
    "mm_fear_greed": {"method": "query_fear_greed_by_time", "symbol": False},
    "mm_funding_rate": {"method": "query_funding_by_time", "symbol": True},
    "mm_open_interest": {"method": "query_open_interest_by_time", "symbol": True},
    "mm_liquidation": {"method": "query_liquidation_by_time", "symbol": True},
    "mm_long_short_ratio": {"method": "query_long_short_ratio_by_time", "symbol": True},
    "mm_taker_volume": {"method": "query_taker_volume_by_time", "symbol": True},
}


def table_catalog() -> list:
    """可读表清单（供 data_tables / dal-data tables 展示）。"""
    items = [
        {
            "table": _MM_TABLE,
            "domain": "macro",
            "requires": ["filters.sub_category", "filters.metric_name"],
            "optional": ["filters.start_ts", "filters.end_ts", "limit"],
        }
    ]
    for name, spec in _MM_TABLE_SPECS.items():
        requires = ["filters.start_ts", "filters.end_ts"]
        if spec["symbol"]:
            requires.insert(0, "filters.symbol")
        items.append(
            {"table": name, "domain": "macro", "requires": requires, "optional": ["limit"]}
        )
    return items


def _json_value(value):
    """把 DAL 行里的 Decimal / datetime 转成 JSON 友好值。"""
    if hasattr(value, "timestamp"):
        try:
            return int(value.timestamp())
        except Exception:  # pragma: no cover
            return str(value)
    if isinstance(value, (bytes, memoryview)):
        return None
    if isinstance(value, (int, float, str, type(None))):
        return value
    return str(value)


def _get_market_macro_repo():
    """惰性加载 sqlite_unified MarketMacroRepository；失败返回 None（FAIL-OPEN）。

    为什么绕过 di 工厂：di 默认 backend=json_legacy（迁移过渡后端），
    mm_metrics 只存在于 sqlite_unified 单库（18-数据获取中心 sink 写入的 SSoT）。
    走 di 会得到 legacy 的"假空"结果，掩盖链路真相。
    壳不改写 DB_BACKEND（SPEC §3.5 硬约束），而是显式绑定本表所在的实现类。
    DAL_DB_PATH 未显式配置时指向 DAL 自带数据目录；env 已设则尊重不动。
    """
    if str(_DAL_ROOT) not in sys.path:
        sys.path.insert(0, str(_DAL_ROOT))
    db_path = os.environ.get("DAL_DB_PATH") or str(_DAL_ROOT / "data" / "dreambuddy_core.db")
    try:
        from dreambuddy_dal.implementations.sqlite_unified import (
            SqliteMarketMacroRepository,
        )
    except Exception:
        return None
    try:
        return SqliteMarketMacroRepository(db_path)
    except Exception:
        return None


def _get_l0():
    """L0 数据入口：优先 34 系统的 L0Foundation（14 个真实 scope）。

    dreambuddy_l0.facade 在本机是空壳（list_scopes() == []），直接使用会让
    data_fetch 对所有 scope 返回 unknown_scope。这里先试 34 系统实现，
    只有 list_scopes 为空时才回退 facade（保留旧行为，FAIL-OPEN）。
    """
    try:
        training_root = str(_REPO_ROOT / "34-前端应用训练系统")
        if training_root not in sys.path:
            sys.path.insert(0, training_root)
        from core.l0_foundation import get_l0 as _get_l0_training

        l0 = _get_l0_training()
        if l0.list_scopes():
            return l0
    except Exception:
        pass

    from dreambuddy_l0.facade import get_l0

    return get_l0()


def _emit_l0_result(result: Any) -> str:
    """L0 返回体已是信封时直接透传（避免二次嵌套），并补齐 source。"""
    if isinstance(result, dict) and "ok" in result and "data" in result:
        payload = dict(result)
        payload["source"] = payload.get("source") or SHELL_SOURCE
        return json.dumps(payload, ensure_ascii=False)
    return json.dumps(wrap(result, SHELL_SOURCE), ensure_ascii=False)


def _handle_data_fetch(args: Dict[str, Any]) -> str:
    """Collector 语义：fetch(scope) → L0 facade fetch_context。"""
    scope = args.get("scope", "")
    if not scope:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": "scope is required"},
            ),
            ensure_ascii=False,
        )
    params = args.get("params") or None
    try:
        result = _get_l0().fetch_context(scope, params)
        return _emit_l0_result(result)
    except KeyError:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="not_found",
                meta={"reason": f"unknown scope: {scope}"},
            ),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            wrap(
                None, SHELL_SOURCE, degraded=True, error_code="unavailable", meta={"reason": str(e)}
            ),
            ensure_ascii=False,
        )


def _handle_data_collect_once(args: Dict[str, Any]) -> str:
    """Collector 语义：单次采集状态查询。"""
    source = args.get("source", "")
    try:
        l0 = _get_l0()
        scopes = l0.list_scopes()
        return json.dumps(
            wrap({"scopes": scopes, "requested_source": source}, SHELL_SOURCE),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            wrap(
                None, SHELL_SOURCE, degraded=True, error_code="unavailable", meta={"reason": str(e)}
            ),
            ensure_ascii=False,
        )


def _handle_data_store_read(args: Dict[str, Any]) -> str:
    """Store 语义：只读查询（经 DAL MarketMacroRepository，表白名单，禁裸 SQL）。

    支持表：mm_metrics
      filters 含 sub_category+metric_name+start_ts+end_ts → query_metric_by_time
      filters 含 sub_category+metric_name（无时间窗）      → query_latest_metric
      缺 sub_category/metric_name → invalid（防全表扫描）
    """
    table = str(args.get("table", "") or "").strip()
    if not table:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": "table is required"},
            ),
            ensure_ascii=False,
        )
    if table != _MM_TABLE:
        spec = _MM_TABLE_SPECS.get(table)
        if spec is None:
            return json.dumps(
                wrap(
                    None,
                    SHELL_SOURCE,
                    degraded=True,
                    error_code="invalid",
                    meta={
                        "reason": f"unsupported table: {table!r}",
                        "whitelist": [_MM_TABLE] + sorted(_MM_TABLE_SPECS),
                    },
                ),
                ensure_ascii=False,
            )
        return _read_macro_table(table, spec, args)
    filters = args.get("filters") if isinstance(args.get("filters"), dict) else {}
    sub_category = str(filters.get("sub_category") or "").strip()
    metric_name = str(filters.get("metric_name") or "").strip()
    if not sub_category or not metric_name:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": "filters.sub_category and filters.metric_name are required"},
            ),
            ensure_ascii=False,
        )
    start_ts = filters.get("start_ts")
    end_ts = filters.get("end_ts")
    limit = min(int(args.get("limit", 100)), 100)
    repo = _get_market_macro_repo()
    if repo is None:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="unavailable",
                meta={"reason": "dal market_macro repo unavailable"},
            ),
            ensure_ascii=False,
        )
    try:
        from datetime import datetime, timezone

        if start_ts is not None and end_ts is not None:
            s_dt = datetime.fromtimestamp(int(start_ts), tz=timezone.utc)
            e_dt = datetime.fromtimestamp(int(end_ts), tz=timezone.utc)
            res = repo.query_metric_by_time(sub_category, metric_name, s_dt, e_dt)
            # List[Tuple[source, metric_name, value, datetime]]
            rows = [
                {
                    "source": r[0],
                    "metric_name": r[1],
                    "metric_value": r[2],
                    "timestamp": int(r[3].timestamp()) if hasattr(r[3], "timestamp") else r[3],
                }
                for r in (res or [])
            ][:limit]
            result = {
                "rows": rows,
                "table": table,
                "sub_category": sub_category,
                "metric_name": metric_name,
            }
        else:
            res = repo.query_latest_metric(sub_category, metric_name)
            # Tuple[source, value, datetime] | None
            rows = []
            if res is not None:
                rows = [
                    {
                        "source": res[0],
                        "metric_value": res[1],
                        "timestamp": (
                            int(res[2].timestamp()) if hasattr(res[2], "timestamp") else res[2]
                        ),
                    }
                ]
            result = {
                "rows": rows,
                "table": table,
                "sub_category": sub_category,
                "metric_name": metric_name,
            }
        return json.dumps(wrap(result, SHELL_SOURCE), ensure_ascii=False)
    except Exception as e:
        return json.dumps(
            wrap(
                None, SHELL_SOURCE, degraded=True, error_code="unavailable", meta={"reason": str(e)}
            ),
            ensure_ascii=False,
        )


def _read_macro_table(table: str, spec: Dict[str, Any], args: Dict[str, Any]) -> str:
    """宏观域其余表的只读查询：必须带时间窗，带 symbol 的表必须给 symbol。"""
    filters = args.get("filters") if isinstance(args.get("filters"), dict) else {}
    start_ts = filters.get("start_ts")
    end_ts = filters.get("end_ts")
    if start_ts is None or end_ts is None:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": f"{table} requires filters.start_ts and filters.end_ts"},
            ),
            ensure_ascii=False,
        )
    symbol = str(filters.get("symbol") or "").strip()
    if spec["symbol"] and not symbol:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": f"{table} requires filters.symbol"},
            ),
            ensure_ascii=False,
        )
    limit = min(int(args.get("limit", 100)), 100)
    repo = _get_market_macro_repo()
    if repo is None:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="unavailable",
                meta={"reason": "dal market_macro repo unavailable"},
            ),
            ensure_ascii=False,
        )
    try:
        from datetime import datetime, timezone

        s_dt = datetime.fromtimestamp(int(start_ts), tz=timezone.utc)
        e_dt = datetime.fromtimestamp(int(end_ts), tz=timezone.utc)
        method = getattr(repo, spec["method"])
        res = method(symbol, s_dt, e_dt) if spec["symbol"] else method(s_dt, e_dt)
        rows = []
        for row in list(res or [])[:limit]:
            values = list(row) if isinstance(row, (tuple, list)) else [row]
            rows.append({"values": [_json_value(v) for v in values]})
        return json.dumps(
            wrap({"rows": rows, "table": table, "symbol": symbol or None}, SHELL_SOURCE),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            wrap(
                None, SHELL_SOURCE, degraded=True, error_code="unavailable", meta={"reason": str(e)}
            ),
            ensure_ascii=False,
        )


def _handle_data_tables(args: Dict[str, Any]) -> str:
    """列出可读表与必填过滤参数（read-only）。"""
    return json.dumps(wrap({"tables": table_catalog()}, SHELL_SOURCE), ensure_ascii=False)


def _handle_data_store_write(args: Dict[str, Any]) -> str:
    """Store 写面：Ban 默认禁（SPEC §3.3）。越权调用明确拒绝（非静默降级），审计留痕。"""
    if not _WRITE_ENABLED:
        # 审计留痕：stderr（宿主可采集）
        print(
            json.dumps(
                {
                    "event": "write_denied",
                    "shell": SHELL_SOURCE,
                    "tool": "data_store_write",
                    "reason": "write banned by default (SPEC §3.3)",
                }
            ),
            file=sys.stderr,
        )
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="conflict",
                meta={
                    "reason": "write tool disabled: requires Mandate authorization (L0_DATA_WRITE_ENABLED=1)"
                },
            ),
            ensure_ascii=False,
        )
    table = args.get("table", "")
    data = args.get("data") or {}
    idempotency_key = args.get("idempotency_key", "")
    if not table or not data:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": "table and data are required"},
            ),
            ensure_ascii=False,
        )
    try:
        from dreambuddy_dal.di import get_container

        container = get_container()
        repo = getattr(container, "write_repo", None)
        if repo is None or not hasattr(repo, "write"):
            return json.dumps(
                wrap(
                    None,
                    SHELL_SOURCE,
                    degraded=True,
                    error_code="unavailable",
                    meta={"reason": "no write repository available in DAL container"},
                ),
                ensure_ascii=False,
            )
        ok = repo.write(table, data=data, idempotency_key=idempotency_key)
        return json.dumps(wrap({"written": ok}, SHELL_SOURCE), ensure_ascii=False)
    except Exception as e:
        return json.dumps(
            wrap(
                None, SHELL_SOURCE, degraded=True, error_code="unavailable", meta={"reason": str(e)}
            ),
            ensure_ascii=False,
        )


TOOL_DEFS = {
    "data_fetch": {
        "description": "Fetch data context by scope (Collector, read-only)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["scope"],
        },
    },
    "data_collect_once": {
        "description": "List available data scopes (Collector, read-only)",
        "inputSchema": {
            "type": "object",
            "properties": {"source": {"type": "string"}},
        },
    },
    "data_store_read": {
        "description": "Read-only store query via DAL (Store, read-only)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "filters": {"type": "object"},
                "limit": {"type": "integer"},
            },
            "required": ["table"],
        },
    },
    "data_tables": {
        "description": "List readable DAL tables and required filters (read-only)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "data_store_write": {
        "description": "Store write (BANNED by default, requires Mandate)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "data": {"type": "object"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["table", "data"],
        },
    },
}

TOOL_HANDLERS = {
    "data_fetch": _handle_data_fetch,
    "data_collect_once": _handle_data_collect_once,
    "data_store_read": _handle_data_store_read,
    "data_tables": _handle_data_tables,
    "data_store_write": _handle_data_store_write,
}


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, TOOL_DEFS, TOOL_HANDLERS)
