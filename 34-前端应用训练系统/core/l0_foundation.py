# -*- coding: utf-8 -*-
"""L0 数据访问抽象层 — FoundationLayer.fetchContext 实现（P1）。

依据: `L0-接口规范-fetchContext.md` v0.1 + `PLAN-L0L1L2-implementation.md` P1。

职责:
  - 十意图的数据访问（sqlite/日志/JSON/公开 API/认知系统）统一收敛到 fetch_context；
  - 数据源路径集中登记（scope 注册表），为 18 中心直查 → 19 DAL 切换预留无缝迁移点；
  - 只返回**原始数据**（data），答案格式化与业务语义留在 L1 exec_*；
  - FAIL-OPEN: 任一数据源不可用只返回 degraded 信封，绝不抛错阻塞主流程。

信封契约:
  fetch_context(scope, params) -> {ok, data, source, timestamp, degraded, meta}
    ok=True/degraded=False + data=None 表示「源可达但无数据」（区别于源不可用）；
    degraded=True 时 meta.reason ∈
      {unknown_scope, invalid_params, source_missing, read_error,
       upstream_unavailable, cognitive_unavailable, fetch_error}。

settle(result, context) 复用已落地分流（案例库 jsonl + 认知价值 record），FAIL-OPEN。
可选 `gate=callable(context) -> (allowed, info)` 注入 45 门禁卡点（P3-3）：无有效凭证拒绝沉淀；
门禁自身异常按 fail-closed 处理（不沉淀），与数据源 FAIL-OPEN 语义区分。
"""

from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

SettleGate = Callable[[Dict[str, Any]], Tuple[bool, Dict[str, Any]]]

# ============================================================
# 路径注册表（相对项目根；core/l0_foundation.py 位于 <root>/34-前端应用训练系统/core/）
# ============================================================

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# 18 中心已迁移 PostgreSQL，复用 39 模块统一 PG 辅助模块（FAIL-OPEN）
# G0-3：禁用模块级 sys.path.insert，dc_pg 改为按文件路径延迟加载（importlib）
_DC_PG_PATH = os.path.join(_PROJECT_ROOT, "39-金融语义蒸馏系统", "scripts", "dc_pg.py")
_dc_pg_module = None


def _load_dc_pg():
    """延迟加载 dc_pg（仅依赖标准库，按文件路径加载，不污染 sys.path）。"""
    global _dc_pg_module
    if _dc_pg_module is None:
        import importlib.util as _ilu

        _spec = _ilu.spec_from_file_location("dreambuddy_dc_pg", _DC_PG_PATH)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _dc_pg_module = _mod
    return _dc_pg_module


# G0-2：41 外部部署路径外置为配置（环境变量 FIS_P0_HOME，本地/云端差异只在配置）
_FIS_P0_HOME = os.environ.get("FIS_P0_HOME", "/home/ubuntu/fis-p0")
_EVOLUTION_LOG = (
    "23-四层闭环自进化交易架构",
    "dreambuddy_evolution",
    "logs",
    "evolution_pipeline.log",
)
_EVOLUTION_SNAPSHOT = (
    "23-四层闭环自进化交易架构",
    "dreambuddy_evolution",
    "gene_data",
    "evolution_snapshots.json",
)
_BCRM2_SUMMARY = ("11-易经推理系统", "data", "bcrm2", "bcrm2_hourly_summary.json")
_BDSM_DIR = ("11-易经推理系统", ".workbuddy", "bdsm")
_TRADER_DIR = ("11-易经推理系统", "data", "polling_trader")
_EVENT_STATE = ("11-易经推理系统", "data", "event_driven_state.json")
_RISK_LOG_DIR = ("16-调控系统", "logs")
_COG_ENTRY = ("4-MEMORY", "9-工具与接口")
_CASE_STORE = ("34-前端应用训练系统", "l1_case_store.jsonl")

# OKX 公开行情（主/备双源）
OKX_BASE = "https://www.okx.com"
OKX_BACKUP = "https://aws.okx.com"

# 战略层三资产类别键（与 L1 _YJ_ASSET_DESC 对齐）
_ASSET_KEYS = ("crypto_usdt", "us_stock", "precious_metal")

# datacenter.series（S1）：mm_metrics 区间序列查询
_SERIES_DB_ENV = "DREAMBUDDY_CORE_DB"
_SERIES_MAX_DAYS = 1825  # 5 年上限，防止全表扫描
_SERIES_AGGS = ("raw", "daily", "weekly", "monthly")
# 标识符白名单：sub_category / metric_name 仅允许字母数字与有限符号，防御注入与误查
_SERIES_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/%+=\-]{0,63}$")

# datacenter.events（经济日历）：未来日程最多查 3 年（FOMC 官网仅公布到次年）
_EVENTS_MAX_DAYS = 1095

# ============================================================
# 信封构造
# ============================================================


def _envelope(
    data: Any, source: str, *, degraded: bool = False, meta: Optional[Dict] = None
) -> Dict[str, Any]:
    return {
        "ok": not degraded,
        "data": data,
        "source": source,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "degraded": degraded,
        "meta": meta or {},
    }


def _degraded(source: str, reason: str, error: str = "", data: Any = None) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"reason": reason}
    if error:
        meta["error"] = str(error)
    return _envelope(data, source, degraded=True, meta=meta)


def _iso_utc(ts: int) -> str:
    """UNIX 秒 → ISO8601 UTC（`2026-11-14T00:00:00Z`）。"""
    return (
        datetime.fromtimestamp(int(ts), tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _iso_cst(ts: int) -> str:
    """UNIX 秒 → 北京时间 `2026-12-10 03:00`（经济日历展示用，不带时区后缀）。"""
    return datetime.fromtimestamp(int(ts) + 8 * 3600, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _bucket_key(ts: int, agg: str) -> str:
    """按聚合粒度生成分桶键（UTC；周用 ISO 年周）。"""
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    if agg == "daily":
        return dt.strftime("%Y-%m-%d")
    if agg == "weekly":
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    if agg == "monthly":
        return dt.strftime("%Y-%m")
    return str(int(ts))


def _aggregate_series(rows: List[Tuple[str, float, int]], agg: str) -> List[Dict[str, Any]]:
    """同桶取最后一个点（降采样口径见 SPEC §六：统一降采样到日频）。"""
    buckets: Dict[str, Tuple[int, float]] = {}
    for _source, value, ts in rows:
        buckets[_bucket_key(ts, agg)] = (int(ts), float(value))
    return [
        {"timestamp": _iso_utc(ts), "ts": int(ts), "value": round(value, 6)}
        for ts, value in sorted(buckets.values())
    ]


# ============================================================
# L0Foundation
# ============================================================


class L0Foundation:
    """L0 数据访问抽象（scope → 数据源 fetcher 注册表）。"""

    # scope → fetcher 方法名
    _SCOPE_REGISTRY = {
        "datacenter.record": "_fetch_datacenter_record",
        "datacenter.series": "_fetch_datacenter_series",
        "datacenter.events": "_fetch_datacenter_events",
        "evolution.contradiction": "_fetch_evolution_contradiction",
        "evolution.snapshot": "_fetch_evolution_snapshot",
        "yijing.bcrm2": "_fetch_yijing_bcrm2",
        "yijing.bdsm": "_fetch_yijing_bdsm",
        "yijing.strategic": "_fetch_yijing_strategic",
        "event.state": "_fetch_event_state",
        "riskcontrol.trailing": "_fetch_riskcontrol_trailing",
        "market.ticker": "_fetch_market_ticker",
        "cognitive.recall": "_fetch_cognitive_recall",
        "docs.search": "_fetch_docs_search",  # B1（41 SPEC §13.2）：41 recall 文档上下文供给
    }

    def __init__(
        self,
        root: Optional[str] = None,
        *,
        okx_base: str = OKX_BASE,
        okx_backup: str = OKX_BACKUP,
        http_timeout: float = 5.0,
    ):
        self.root = root or _PROJECT_ROOT
        self.okx_base = okx_base
        self.okx_backup = okx_backup
        self.http_timeout = http_timeout

    # -------- 公共 API --------

    def list_scopes(self) -> List[str]:
        return list(self._SCOPE_REGISTRY.keys())

    def fetch_context(self, scope: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """按 scope 取原始数据。任何异常均收敛为 degraded 信封（FAIL-OPEN）。"""
        handler_name = self._SCOPE_REGISTRY.get(scope)
        if handler_name is None:
            return _degraded(scope, "unknown_scope", f"unknown scope: {scope}")
        handler = getattr(self, handler_name)
        try:
            return handler(params or {})
        except Exception as e:  # 防御纵深：fetcher 内部漏网异常也不得抛给 L1
            return _degraded(scope, "fetch_error", f"{type(e).__name__}: {e}")

    def settle(
        self,
        result: Optional[Dict],
        context: Optional[Dict] = None,
        *,
        gate: Optional[SettleGate] = None,
    ) -> None:
        """工作后沉淀（已落地能力复用）：成功→案例库；有价值发现→认知系统。FAIL-OPEN。

        gate（P3-3 45 门禁）：返回 (allowed, info)；未通过则不沉淀。
        门禁异常按 fail-closed（拒绝沉淀），避免无凭证沉淀。
        """
        context = context or {}
        if gate is not None:
            try:
                allowed, _info = gate(context)
            except Exception:
                allowed = False
            if not allowed:
                return
        intent = context.get("intent", "")
        message = context.get("message", "")
        try:
            self._settle_case(intent, message, result, context)
        except Exception:
            pass
        try:
            self._settle_cognitive_valuable(intent, message, result)
        except Exception:
            pass

    # -------- scope: docs.search（B1，41 SPEC §13.2/§7.10） --------
    def _fetch_docs_search(self, params: Dict) -> Dict[str, Any]:
        """41 recall() 文档上下文供给：L1/L2 工作前按 query 召回相关文档片段。
        spawn 41 search_cli recall 命令（chunk 级 BM25 候选），FAIL-OPEN 降级空结果。
        params: query（必填）、limit（默认 5）
        """
        import json as _json
        import subprocess as _sp

        src_tag = "fis_docs_search"
        query = params.get("query")
        if not query:
            return _degraded(src_tag, "invalid_params", "missing param: query")
        limit = int(params.get("limit", 5))
        try:
            proc = _sp.run(
                [
                    os.path.join(_FIS_P0_HOME, ".venv/bin/python"),
                    os.path.join(_FIS_P0_HOME, "scripts/search_cli.py"),
                ],
                input=_json.dumps({"cmd": "recall", "query": str(query), "limit": limit}),
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "FIS_PG_PASSWORD": os.environ.get("FIS_PG_PASSWORD")},
            )
            res = _json.loads(proc.stdout or "{}")
            hits = res.get("hits", []) if res.get("success") else []
            return _envelope(hits, src_tag)
        except Exception as e:
            return _degraded(src_tag, "fetch_error", f"{type(e).__name__}: {e}")

    # -------- 路径 --------

    def _path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    # -------- scope: datacenter.record --------

    def _fetch_datacenter_record(self, params: Dict) -> Dict[str, Any]:
        src = params.get("source")
        src_tag = "data_center_pg"
        if not src:
            return _degraded(src_tag, "invalid_params", "missing param: source")
        # PostgreSQL 查询（dc_pg 统一接口，FAIL-OPEN：异常/无记录返回 None）
        row = _load_dc_pg().fetch_latest_by_source(src, params.get("sub_category"))
        if row is None:
            return _envelope(None, src_tag)
        return _envelope(
            {
                "source": row["source"],
                "category": row["category"],
                "sub_category": row["sub_category"],
                "timestamp": row["timestamp"],
                "metrics": row["metrics"],
            },
            src_tag,
        )

    # -------- scope: datacenter.series（S1：真实历史序列） --------

    def _resolve_series_db(self) -> str:
        """mm_metrics 所在库：环境变量优先（云端/快照副本），默认 19-DAL 生产库。"""
        env_path = os.environ.get(_SERIES_DB_ENV)
        if env_path:
            return env_path
        return self._path("19-数据访问层", "data", "dreambuddy_core.db")

    def _query_series_rows(
        self,
        db_path: str,
        sub_category: str,
        metric_name: str,
        start_ts: int,
        end_ts: int,
        source: Optional[str] = None,
    ) -> List[Tuple[str, float, int]]:
        """只读区间查询（命中 idx_mm_metrics_lookup），跨源同 ts 去重保留 source 字典序最小。"""
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            sql = (
                "SELECT source, metric_value, timestamp FROM mm_metrics "
                "WHERE sub_category = ? AND metric_name = ? "
                "AND timestamp >= ? AND timestamp < ? AND metric_value IS NOT NULL"
            )
            args: List[Any] = [sub_category, metric_name, start_ts, end_ts]
            if source:
                sql += " AND source = ?"
                args.append(source)
            sql += " ORDER BY timestamp ASC, source ASC"
            rows = conn.execute(sql, args).fetchall()
        finally:
            conn.close()
        seen: set = set()
        out: List[Tuple[str, float, int]] = []
        for src, value, ts in rows:
            if ts in seen:  # 跨源重复（如 funding_rate 双写）按 source ASC 去重
                continue
            seen.add(ts)
            out.append((src, float(value), int(ts)))
        return out

    def _fetch_datacenter_series(self, params: Dict) -> Dict[str, Any]:
        """mm_metrics 区间序列 + 降采样。返回 {points, sample_n} 与 meta.quality。"""
        src_tag = "dal_mm_metrics"
        sub = str(params.get("sub_category") or "").strip()
        metric = str(params.get("metric_name") or "").strip()
        if not sub or not metric:
            return _degraded(src_tag, "invalid_params", "missing param: sub_category/metric_name")
        if not _SERIES_IDENT_RE.match(sub) or not _SERIES_IDENT_RE.match(metric):
            return _degraded(src_tag, "invalid_params", f"illegal identifier: {sub}/{metric}")
        try:
            days = int(params.get("days", 30))
        except (TypeError, ValueError):
            return _degraded(src_tag, "invalid_params", "days must be int")
        if days < 1 or days > _SERIES_MAX_DAYS:
            return _degraded(src_tag, "invalid_params", f"days out of range 1..{_SERIES_MAX_DAYS}")
        agg = str(params.get("agg") or "daily").lower()
        if agg not in _SERIES_AGGS:
            return _degraded(src_tag, "invalid_params", f"unsupported agg: {agg}")
        source = params.get("source")
        if source and not _SERIES_IDENT_RE.match(str(source)):
            return _degraded(src_tag, "invalid_params", f"illegal source: {source}")

        db_path = self._resolve_series_db()
        if not os.path.isfile(db_path):
            return _degraded(src_tag, "source_missing", db_path)
        end_ts = int(datetime.now(tz=timezone.utc).timestamp()) + 86400  # 含当日已落库点
        start_ts = end_ts - days * 86400
        try:
            rows = self._query_series_rows(
                db_path, sub, metric, start_ts, end_ts, str(source) if source else None
            )
        except Exception as e:
            return _degraded(src_tag, "read_error", f"{type(e).__name__}: {e}")

        points = _aggregate_series(rows, agg)
        sample_n = len(points)
        quality = "empty" if sample_n == 0 else ("partial" if sample_n < 30 else "good")
        meta: Dict[str, Any] = {
            "quality": quality,
            "sample_n": sample_n,
            "agg": agg,
            "days": days,
            "raw_n": len(rows),
            "sources": sorted({r[0] for r in rows}),
            "window_start": _iso_utc(start_ts),
            "window_end": _iso_utc(end_ts),
            "db": db_path,
        }
        if sample_n == 0:
            meta["reason"] = "no_history"
        return _envelope(
            {
                "sub_category": sub,
                "metric_name": metric,
                "agg": agg,
                "days": days,
                "points": points,
                "sample_n": sample_n,
            },
            src_tag,
            meta=meta,
        )

    # -------- scope: datacenter.events（经济日历：mm_events） --------

    def _fetch_datacenter_events(self, params: Dict) -> Dict[str, Any]:
        """mm_events 按时序取事件（默认未来 400 天内最近 5 条）。

        params: kinds（事件类型过滤，如 ["fomc"]）、limit（默认 5）、
                future_days（默认 400）、past_days（默认 0，>0 时含近期已发生事件）
        返回按 event_time 升序的事件列表；data=[] 表示源可达但窗口内无事件。
        """
        src_tag = "dal_mm_events"
        try:
            limit = int(params.get("limit", 5))
            future_days = int(params.get("future_days", 400))
            past_days = int(params.get("past_days", 0))
        except (TypeError, ValueError):
            return _degraded(src_tag, "invalid_params", "limit/future_days/past_days must be int")
        if not (1 <= limit <= 50) or not (0 <= future_days <= _EVENTS_MAX_DAYS) or past_days < 0:
            return _degraded(src_tag, "invalid_params", "limit/future_days/past_days out of range")
        kinds = params.get("kinds") or []
        if isinstance(kinds, str):
            kinds = [kinds]
        kinds = {str(k) for k in kinds if k}

        db_path = self._resolve_series_db()
        if not os.path.isfile(db_path):
            return _degraded(src_tag, "source_missing", db_path)
        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        start_ts = now_ts - past_days * 86400
        end_ts = now_ts + future_days * 86400
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            try:
                rows = conn.execute(
                    "SELECT event_time, event_type, subtype, source, title, confidence, quality "
                    "FROM mm_events WHERE event_time >= ? AND event_time < ? "
                    "ORDER BY event_time ASC",
                    (start_ts, end_ts),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as e:
            return _degraded(src_tag, "read_error", f"{type(e).__name__}: {e}")

        events: List[Dict[str, Any]] = []
        for et, etype, subtype, source, title, confidence, quality in rows:
            if kinds and (etype or "") not in kinds:
                continue
            events.append(
                {
                    "event_time": _iso_utc(int(et)),
                    "ts": int(et),
                    "event_time_cst": _iso_cst(int(et)),
                    "event_type": etype or "",
                    "subtype": subtype or "",
                    "source": source or "",
                    "title": title or "",
                    "confidence": confidence,
                    "quality": quality or "",
                }
            )
            if len(events) >= limit:
                break
        return _envelope(
            events,
            src_tag,
            meta={"window_start": _iso_utc(start_ts), "window_end": _iso_utc(end_ts)},
        )

    # -------- scope: evolution.contradiction --------

    def _fetch_evolution_contradiction(self, params: Dict) -> Dict[str, Any]:
        log_path = self._path(*_EVOLUTION_LOG)
        if not os.path.exists(log_path):
            return _degraded(log_path, "source_missing")
        try:
            with open(log_path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-3000:]
        except Exception as e:
            return _degraded(log_path, "read_error", e)
        pat = re.compile(r"\[Contradiction\] dim=(C\d) dir=(\w+) strength=([0-9.]+)")
        dims: Dict[str, Dict[str, Any]] = {}
        for line in lines:
            m = pat.search(line)
            if m:
                dims[m.group(1)] = {"direction": m.group(2), "strength": float(m.group(3))}
        if not dims:
            return _envelope(None, log_path)
        return _envelope({"dims": dims}, log_path)

    # -------- scope: evolution.snapshot --------

    def _fetch_evolution_snapshot(self, params: Dict) -> Dict[str, Any]:
        snap_path = self._path(*_EVOLUTION_SNAPSHOT)
        if not os.path.exists(snap_path):
            return _degraded(snap_path, "source_missing")
        try:
            with open(snap_path, encoding="utf-8") as f:
                snap = json.load(f)
        except Exception as e:
            return _degraded(snap_path, "read_error", e)
        if not isinstance(snap, dict) or not snap:
            return _envelope(None, snap_path)
        return _envelope(snap, snap_path)

    # -------- scope: yijing.bcrm2 --------

    def _fetch_yijing_bcrm2(self, params: Dict) -> Dict[str, Any]:
        path = self._path(*_BCRM2_SUMMARY)
        if not os.path.exists(path):
            return _degraded(path, "source_missing")
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            return _degraded(path, "read_error", e)
        results = (d or {}).get("results") or {}
        if not results:
            return _envelope(None, path)
        return _envelope(results, path)

    # -------- scope: yijing.bdsm --------

    def _fetch_yijing_bdsm(self, params: Dict) -> Dict[str, Any]:
        dir_path = self._path(*_BDSM_DIR)
        if not os.path.isdir(dir_path):
            return _degraded(dir_path, "source_missing")
        files = sorted(glob.glob(os.path.join(dir_path, "bdsm_snapshot_*.json")))
        if not files:
            return _envelope(None, dir_path)
        snapshot_file = files[-1]
        try:
            with open(snapshot_file, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            return _degraded(snapshot_file, "read_error", e)
        return _envelope(d, snapshot_file, meta={"snapshot_file": snapshot_file})

    # -------- scope: yijing.strategic --------

    def _fetch_yijing_strategic(self, params: Dict) -> Dict[str, Any]:
        dir_path = self._path(*_TRADER_DIR)
        if not os.path.isdir(dir_path):
            return _degraded(dir_path, "source_missing")
        files = sorted(glob.glob(os.path.join(dir_path, "trader_*.jsonl")))
        if not files:
            return _envelope(None, dir_path)
        log_file = files[-1]
        try:
            with open(log_file, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-2000:]
        except Exception as e:
            return _degraded(log_file, "read_error", e)
        asset_state: Dict[str, str] = {}
        veto_pat = re.compile(r"dimension_veto \| (.+?)$")
        for line in lines:
            if "[战略层影子]" not in line or "dimension_veto" not in line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            m = veto_pat.search(rec.get("msg", ""))
            if not m:
                continue
            for part in m.group(1).split("|"):
                kv = part.strip().split("=", 1)
                if len(kv) == 2 and kv[0] in _ASSET_KEYS:
                    asset_state[kv[0]] = kv[1].strip()
        if not asset_state:
            return _envelope(None, log_file, meta={"log_file": log_file})
        return _envelope({"assets": asset_state}, log_file, meta={"log_file": log_file})

    # -------- scope: event.state --------

    def _fetch_event_state(self, params: Dict) -> Dict[str, Any]:
        path = self._path(*_EVENT_STATE)
        if not os.path.exists(path):
            return _degraded(path, "source_missing")
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            return _degraded(path, "read_error", e)
        if not (state or {}).get("signal"):
            return _envelope(None, path)
        return _envelope(state, path)

    # -------- scope: riskcontrol.trailing --------

    def _fetch_riskcontrol_trailing(self, params: Dict) -> Dict[str, Any]:
        dir_path = self._path(*_RISK_LOG_DIR)
        if not os.path.isdir(dir_path):
            return _degraded(dir_path, "source_missing")
        files = sorted(glob.glob(os.path.join(dir_path, "trailing_runner_*.log")))
        if not files:
            return _envelope(None, dir_path)
        log_file = files[-1]
        try:
            with open(log_file, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-500:]
        except Exception as e:
            return _degraded(log_file, "read_error", e)
        pat = re.compile(
            r"评估完成: 总持仓=(\d+) IDLE=(\d+) ARMED=(\d+) TRIGGERED=(\d+) CLOSED=(\d+) 历史触发累计=(\d+)"
        )
        latest = None
        for line in lines:
            m = pat.search(line)
            if m:
                latest = {
                    "total": int(m.group(1)),
                    "IDLE": int(m.group(2)),
                    "ARMED": int(m.group(3)),
                    "TRIGGERED": int(m.group(4)),
                    "CLOSED": int(m.group(5)),
                    "history_triggered": int(m.group(6)),
                }
        if not latest:
            return _envelope(None, log_file, meta={"log_file": log_file})
        return _envelope({"positions": latest}, log_file, meta={"log_file": log_file})

    # -------- scope: market.ticker --------

    def _http_get_json(self, url: str, timeout: float = 5.0) -> Dict[str, Any]:
        """HTTP GET JSON（独立方法，便于测试 monkeypatch；生产走 urllib）。"""
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _fetch_market_ticker(self, params: Dict) -> Dict[str, Any]:
        symbol = params.get("symbol") or "BTC"
        inst_id = f"{symbol}-USDT"
        last_error = ""
        for base in (self.okx_base, self.okx_backup):
            try:
                body = self._http_get_json(
                    f"{base}/api/v5/market/ticker?instId={inst_id}",
                    timeout=self.http_timeout,
                )
                if body.get("code") == "0" and body.get("data"):
                    return _envelope(body["data"][0], base, meta={"inst_id": inst_id})
                last_error = body.get("msg") or "empty ticker data"
            except Exception as e:
                last_error = str(e)
                continue
        return _degraded(f"{self.okx_base}/{self.okx_backup}", "upstream_unavailable", last_error)

    # -------- scope: cognitive.recall --------

    def _load_cle(self):
        """加载认知系统入口单例（独立方法，便于测试 monkeypatch）。"""
        cog_path = self._path(*_COG_ENTRY)
        if cog_path not in os.sys.path:
            os.sys.path.insert(0, cog_path)
        from cognitive_loop_entry import get_cle

        return get_cle()

    def _fetch_cognitive_recall(self, params: Dict) -> Dict[str, Any]:
        context = params.get("context")
        if not context:
            return _degraded("cognitive-loop-entry", "invalid_params", "missing param: context")
        top_k = int(params.get("top_k", 5))
        min_quality = params.get("min_quality", "C")
        # L1 是确定性能力直达（意图→检索→直答），PoE 信任门禁属 L2 语义层，
        # 调用方可显式按次关闭，结束后恢复原值。
        poe = params.get("poe_enforcement")
        try:
            cle = self._load_cle()
            prev_poe = getattr(cle, "poe_enforcement", None)
            if poe:
                cle.poe_enforcement = str(poe)
            try:
                memories = cle.recall(context, top_k=top_k, min_quality=min_quality)
            finally:
                if poe and prev_poe is not None:
                    cle.poe_enforcement = prev_poe
        except Exception as e:
            return _degraded(
                "cognitive-loop-entry", "cognitive_unavailable", f"{type(e).__name__}: {e}", data=[]
            )
        return _envelope(list(memories or []), "cognitive-loop-entry")

    # -------- settle 分流（从 L1 执行器上收，行为保持一致，FAIL-OPEN） --------

    def _settle_case(
        self, intent: str, message: str, result: Optional[Dict], context: Optional[Dict] = None
    ) -> None:
        """成功执行的 query→answer 对写入案例库（统计学习回路）。"""
        if not result or not result.get("success") or result.get("degraded"):
            return
        case = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "schema_version": "v2",  # P1.5：案例结构版本化（与 38 records 表对齐）
            "intent": intent,
            "message": message,
            "answer": str(result.get("answer", ""))[:300],
            "data": result.get("data"),
        }
        # P1.5 扩展字段（spec §9.1）：意图系统域 complexity/entities 透传
        # T-DSH-P2: trace_id(ADR-7 观测主轴)/evidence_bundle(45 裁决凭证)透传
        context = context or {}
        for _k in ("complexity", "entities", "trace_id", "evidence_bundle"):
            if context.get(_k) is not None:
                case[_k] = context[_k]
        self._append_case(case)

    def _append_case(self, case: Dict) -> None:
        case_path = self._path(*_CASE_STORE)
        os.makedirs(os.path.dirname(case_path), exist_ok=True)
        with open(case_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    @staticmethod
    def _detect_valuable_finding(result: Optional[Dict]) -> Optional[str]:
        """价值判断: 数据源的坑/降级环境/异常模式；正常数据返回 None。"""
        if not result:
            return None
        answer = str(result.get("answer", ""))
        data = result.get("data")
        if result.get("degraded") or "executor_failed" in answer or "执行异常" in answer:
            return f"发现: {answer[:150]}"
        if isinstance(data, dict):
            metrics = data.get("metrics")
            if metrics is None or metrics == "" or metrics == {}:
                return f"数据源的坑: {data.get('source', '?')} 的 metrics 为空（category={data.get('category', '?')}）"
            if isinstance(metrics, dict):
                numeric = [v for v in metrics.values() if isinstance(v, (int, float))]
                if numeric and all(v == 0 for v in numeric):
                    return (
                        f"数据源的坑: {data.get('source', '?')} 数值字段全为 0"
                        f"（sub_category={data.get('sub_category', '?')}），数据质量存疑"
                    )
        return None

    def _settle_cognitive_valuable(self, intent: str, message: str, result: Optional[Dict]) -> None:
        finding = self._detect_valuable_finding(result)
        if not finding:
            return
        self._record_cognitive(f"[L1探索发现] intent={intent} | 问法: {message} | {finding}")

    def _record_cognitive(self, content: str, intent: str = "") -> None:
        cle = self._load_cle()
        cle.record(
            content=content,
            quality_level="B",
            confidence=0.6,
            tags=["l1-router", "settle-finding", intent],
            source="l1_router",
            memory_type="experience",
        )


# ============================================================
# 进程内单例
# ============================================================

_default_l0: Optional[L0Foundation] = None


def get_l0() -> L0Foundation:
    global _default_l0
    if _default_l0 is None:
        _default_l0 = L0Foundation()
    return _default_l0
