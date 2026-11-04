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
import time
from pathlib import Path
from typing import Any, Dict

# 壳进程 import 规约（SPEC §3.4）：PYTHONPATH=<repo root> 由宿主注入
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shadow_hook import observe_envelope  # noqa: E402

SHELL_SOURCE = "l0.data.mcp"

# 写面 Ban 开关（SPEC §3.3：写工具默认禁用；宿主 Mandate 经 env 授权）
_WRITE_ENABLED = os.environ.get("L0_DATA_WRITE_ENABLED", "0") == "1"

# DAL 显式路径声明（与 l0_store_admin 一致；中文目录名无法直接 import）
_DAL_ROOT = _REPO_ROOT / "19-数据访问层"

# data_store_read 表白名单（禁任意表，仅映射 DAL repo 方法）
_MM_TABLE = "mm_metrics"


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
    from dreambuddy_l0.facade import get_l0

    return get_l0()


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
        return json.dumps(wrap(result, SHELL_SOURCE), ensure_ascii=False)
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
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": f"unsupported table: {table!r} (whitelist: {_MM_TABLE})"},
            ),
            ensure_ascii=False,
        )
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


TOOL_HANDLERS = {
    "data_fetch": _handle_data_fetch,
    "data_collect_once": _handle_data_collect_once,
    "data_store_read": _handle_data_store_read,
    "data_store_write": _handle_data_store_write,
}


def _handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    method = req.get("method", "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
        }
    if method == "tools/list":
        tools = [
            {
                "name": "data_fetch",
                "description": "Fetch data context by scope (Collector, read-only)",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
            {
                "name": "data_collect_once",
                "description": "List available data scopes (Collector, read-only)",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
            {
                "name": "data_store_read",
                "description": "Read-only store query via DAL (Store, read-only)",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
            {
                "name": "data_store_write",
                "description": "Store write (BANNED by default, requires Mandate)",
                "annotations": {"readOnlyHint": False, "destructiveHint": True},
            },
        ]
        return {"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": tools}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        started = time.perf_counter()
        result_text = handler(params.get("arguments", {}))
        # COMM-SHADOW 旁路观察（默认关闭，FAIL-OPEN）：实测耗时 + 工具名补齐轨迹信号
        observe_envelope(
            result_text,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            action=name,
        )
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"content": [{"type": "text", "text": result_text}], "isError": False},
        }
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    """stdio 主循环：逐行读取 JSON-RPC 请求。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
