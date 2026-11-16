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
from datetime import datetime, timedelta, timezone
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
# market.candles（S1）：日频价格 → K 线；OHLC 来自 18 中心落库的 `{symbol}/USDT` 高低点
_CANDLE_BARS = ("1h", "1d", "1w", "1m")
_CANDLE_MIN_GOOD = {"1h": 240, "1d": 250, "1w": 52, "1m": 24}
_CANDLE_DEFAULT_SYMBOL = "BTC"
# OHLC 子类映射：18 中心 ccxt ticker 以 `BTC/USDT` 落 high/low（非逐根K线极值）
_CANDLE_OHLC_SUBCATEGORY = {"BTC": "BTC/USDT", "ETH": "ETH/USDT", "SOL": "SOL/USDT"}
_CANDLE_OHLC_NOTE = "ccxt ticker 24h 滚动高低点（非逐根K线极值）"
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


def _day_window(days: int, end_ts: Optional[int] = None) -> tuple:
    """UTC 日历日窗口 (start_ts, end_ts)：end 为「明天 00:00」，含当日已落库点。

    按日对齐而非 now-N*86400，避免查询时刻（时/分）把窗口边界切进某一天，
    导致 days=5 只取到 4 个日频点这类随时钟漂移的结果。

    `end_ts` 显式给出时（回放 as_of），窗口锚定在 As-Of 当天而非 now。
    """
    if end_ts is not None:
        anchor = datetime.fromtimestamp(int(end_ts), tz=timezone.utc)
        day_end = int(anchor.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()) + 86400
        return day_end - days * 86400, day_end
    now = datetime.now(tz=timezone.utc)
    day_end = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()) + 86400
    return day_end - days * 86400, day_end


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


def _daily_last(rows: List[Tuple[str, float, int]]) -> Dict[str, Tuple[int, float]]:
    """同一 UTC 日取最后一个观测（收盘口径），返回 {YYYY-MM-DD: (ts, value)}。"""
    out: Dict[str, Tuple[int, float]] = {}
    for _source, value, ts in rows:
        day = _bucket_key(ts, "daily")
        prev = out.get(day)
        if prev is None or int(ts) >= prev[0]:
            out[day] = (int(ts), float(value))
    return out


def _day_to_dt(day: str) -> datetime:
    """YYYY-MM-DD → UTC 00:00 datetime。"""
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _candle_bar_start(day: str, bar: str) -> str:
    """日键 → 所属 K 线桶键（1d 原样；1w 取 ISO 周一；1m 取月初）。"""
    if bar == "1d":
        return day
    dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if bar == "1m":
        return dt.strftime("%Y-%m-01")
    return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")


def _bucket_extreme(
    rows: List[Tuple[str, float, int]], bar: str, pick: Callable
) -> Dict[str, float]:
    """按 K 线桶取高低点极值（`pick` 为 max/min）；忽略 <=0 的脏值，不填假值。"""
    out: Dict[str, float] = {}
    for _source, value, ts in rows:
        value = float(value)
        if value <= 0:
            continue
        key = _candle_bar_start(_bucket_key(ts, "daily"), bar)
        prev = out.get(key)
        out[key] = value if prev is None else pick(prev, value)
    return out


def _hour_last(rows: List[Tuple[str, float, int]]) -> Dict[int, float]:
    """小时桶取最后一个观测（同一小时多源/多点时按时间升序覆盖）。"""
    out: Dict[int, float] = {}
    for _source, value, ts in rows:
        value = float(value)
        if value <= 0:
            continue
        out[int(ts) // 3600 * 3600] = value
    return out


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
        "market.candles": "_fetch_market_candles",
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

    def _query_series_rows_vintage(
        self,
        db_path: str,
        sub_category: str,
        metric_name: str,
        start_ts: int,
        end_ts: int,
        as_of: int,
        source: Optional[str] = None,
    ) -> List[Tuple[str, float, int]]:
        """按 As-Of 回放：只取 `observed_at <= as_of`，同周期取最晚一次观测（vintage）。

        表不存在时抛 sqlite3.OperationalError，由调用方降级为 `vintage_unavailable`，
        **绝不回落到 mm_metrics**——那会读到修订后的值（前视）。
        """
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            sql = (
                "SELECT source, metric_value, period_ts FROM mm_metric_vintages "
                "WHERE sub_category = ? AND metric_name = ? "
                "AND period_ts >= ? AND period_ts < ? AND observed_at <= ? "
                "AND metric_value IS NOT NULL"
            )
            args: List[Any] = [sub_category, metric_name, start_ts, end_ts, int(as_of)]
            if source:
                sql += " AND source = ?"
                args.append(source)
            # 同 (period_ts) 多版本时保留 observed_at 最大者（该 As-Of 时点已知的最新版本）
            sql += " ORDER BY period_ts ASC, observed_at DESC, source ASC"
            rows = conn.execute(sql, args).fetchall()
        finally:
            conn.close()
        seen: set = set()
        out: List[Tuple[str, float, int]] = []
        for src, value, ts in rows:
            if ts in seen:
                continue
            seen.add(ts)
            out.append((str(src), float(value), int(ts)))
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

        as_of: Optional[int] = None
        as_of_raw = params.get("as_of")
        if as_of_raw not in (None, ""):
            try:
                if isinstance(as_of_raw, (int, float)):
                    as_of = int(as_of_raw)
                else:
                    as_of = int(
                        datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00")).timestamp()
                    )
            except (TypeError, ValueError):
                return _degraded(src_tag, "invalid_params", "as_of must be epoch or ISO8601")

        db_path = self._resolve_series_db()
        if not os.path.isfile(db_path):
            return _degraded(src_tag, "source_missing", db_path)
        start_ts, end_ts = _day_window(days, as_of)
        try:
            if as_of is None:
                rows = self._query_series_rows(
                    db_path, sub, metric, start_ts, end_ts, str(source) if source else None
                )
            else:
                rows = self._query_series_rows_vintage(
                    db_path, sub, metric, start_ts, end_ts, as_of, str(source) if source else None
                )
        except sqlite3.OperationalError as e:
            # 回放请求但 vintage 表缺失：必须暴露缺失，禁止回落到修订后的 mm_metrics
            return _degraded(src_tag, "vintage_unavailable", f"{type(e).__name__}: {e}")
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
        if as_of is not None:
            meta["as_of"] = _iso_utc(as_of)
            meta["vintage"] = True
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

    # -------- scope: market.candles（S1：日频价格 → 1D/1W/1M K 线） --------

    def _resolve_ohlc_sub(self, symbol: str, params: Dict) -> str:
        """解析 OHLC 子类：显式参数 > `{symbol}/USDT` 映射；非法/无映射回空串（不伪造）。"""
        sub = str(params.get("ohlc_sub_category") or "").strip()
        if not sub:
            sub = _CANDLE_OHLC_SUBCATEGORY.get(symbol, "")
        return sub if sub and _SERIES_IDENT_RE.match(sub) else ""

    def _fetch_market_candles(self, params: Dict) -> Dict[str, Any]:
        """从 `mm_metrics` 派生 K 线（close/volume 来自 `{symbol}`，OHLC 来自 `{symbol}/USDT`）。

        参数: symbol（默认 BTC）、days（1..1825，默认 365）、bar ∈ {1h,1d,1w,1m}、
              ohlc_sub_category（可选，覆盖默认高低点子类映射）、
              source_policy ∈ {auto, snapshot, bars}（1d 收盘来源策略）。
        口径:
          - 1d 收盘来源（meta.close_anchor）：
              `bar_close`（18 中心回填的 `*_1d` 真实日线，收盘锚点=UTC 日末）
              / `snapshot_last`（OKX 日频快照，收盘锚点=当日最后一个观测）；
              **跨源比较必须使用同一策略**（不同锚点混用会让同期相关被系统性低估），
              故 `source_policy=snapshot` 强制两侧都走快照、`bars` 强制只走真实日线；
          - 1d 的 `ts` 统一归一到 UTC 日首（日键），真实观测/收盘时刻另存 `close_ts`；
            同一 UTC 日取最后一个观测为收盘；1w 取 ISO 周一、1m 取月初为桶起点，
            桶内 close 取桶末值，volume 取桶内求和；
          - OHLC: 桶内 high 取 max、low 取 min（忽略 <=0 脏值），且收盘须落在 [low, high]
                内才挂 OHLC（跨源不一致的桶不伪造）；**只有全部桶都有高低点**才置
                `has_ohlc=True`，部分覆盖时如实给 `ohlc_coverage` 且不回填假值；
          - 1h: 直接取 OHLC 子类的小时级 `last/high/low`，只输出三腿齐全的小时（无则跳过）；
          - 时效与质量由调用方按 meta 判定（不在此处伪造/外推）。
        局限: 库内 OHLC 为 ccxt ticker 的 24h 滚动高低点，非逐根 K 线真实极值（meta.ohlc_note 标注）。
        """
        src_tag = "dal_mm_metrics"
        symbol = str(params.get("symbol") or _CANDLE_DEFAULT_SYMBOL).strip().upper()
        if not _SERIES_IDENT_RE.match(symbol):
            return _degraded(src_tag, "invalid_params", f"illegal symbol: {symbol}")
        bar = str(params.get("bar") or "1d").lower()
        if bar not in _CANDLE_BARS:
            return _degraded(src_tag, "invalid_params", f"unsupported bar: {bar}")
        policy = str(params.get("source_policy") or "auto").lower()
        if policy not in ("auto", "snapshot", "bars"):
            return _degraded(src_tag, "invalid_params", f"unsupported source_policy: {policy}")
        try:
            days = int(params.get("days", 365))
        except (TypeError, ValueError):
            return _degraded(src_tag, "invalid_params", "days must be int")
        if days < 1 or days > _SERIES_MAX_DAYS:
            return _degraded(src_tag, "invalid_params", f"days out of range 1..{_SERIES_MAX_DAYS}")

        db_path = self._resolve_series_db()
        if not os.path.isfile(db_path):
            return _degraded(src_tag, "source_missing", db_path)
        start_ts, end_ts = _day_window(days)
        if bar == "1h":
            return self._fetch_market_candles_hourly(
                db_path, symbol, days, start_ts, end_ts, params
            )

        # 真实日线 OHLC（18 中心 1h K 线回填的 `*_1d`）优先于 ticker 高低点合并
        # `source_policy=snapshot` 时禁用该路径，保证跨资产比较同一收盘锚点
        ohlc_sub = self._resolve_ohlc_sub(symbol, params)
        true_bars = (
            []
            if policy == "snapshot"
            else self._load_daily_ohlc_bars(db_path, ohlc_sub, start_ts, end_ts)
        )
        if true_bars:
            return self._candles_from_bars(true_bars, symbol, bar, days, ohlc_sub, db_path)
        if policy == "bars":
            return _envelope(
                {
                    "symbol": symbol,
                    "bar": bar,
                    "points": [],
                    "sample_n": 0,
                    "has_ohlc": False,
                },
                src_tag,
                meta={
                    "quality": "empty",
                    "sample_n": 0,
                    "reason": "no_true_bars",
                    "bar": bar,
                    "days": days,
                    "timezone": "UTC",
                    "align_method": "daily_last",
                    "close_anchor": "bar_close",
                    "has_ohlc": False,
                    "ohlc_coverage": 0.0,
                    "ohlc_source": "",
                    "db": db_path,
                },
            )

        try:
            close_rows = self._query_series_rows(db_path, symbol, "close_usd", start_ts, end_ts)
            volume_rows = self._query_series_rows(db_path, symbol, "volume_usd", start_ts, end_ts)
        except Exception as e:
            return _degraded(src_tag, "read_error", f"{type(e).__name__}: {e}")

        # OHLC 合并：有映射且查询失败时回退为 close-only（FAIL-OPEN，不阻塞收盘序列）
        highs: Dict[str, float] = {}
        lows: Dict[str, float] = {}
        ohlc_source = ""
        if ohlc_sub:
            try:
                high_rows = self._query_series_rows(db_path, ohlc_sub, "high", start_ts, end_ts)
                low_rows = self._query_series_rows(db_path, ohlc_sub, "low", start_ts, end_ts)
                highs = _bucket_extreme(high_rows, bar, max)
                lows = _bucket_extreme(low_rows, bar, min)
                ohlc_source = f"mm_metrics:{ohlc_sub}"
            except Exception:
                highs, lows, ohlc_source = {}, {}, ""

        closes = _daily_last(close_rows)
        volumes = _daily_last(volume_rows)
        if not closes:
            return _envelope(
                {
                    "symbol": symbol,
                    "bar": bar,
                    "points": [],
                    "sample_n": 0,
                    "has_ohlc": False,
                },
                src_tag,
                meta={
                    "quality": "empty",
                    "sample_n": 0,
                    "reason": "no_history",
                    "bar": bar,
                    "days": days,
                    "timezone": "UTC",
                    "align_method": "daily_last",
                    "close_anchor": "snapshot_last",
                    "has_ohlc": False,
                    "ohlc_coverage": 0.0,
                    "ohlc_source": ohlc_source,
                    "db": db_path,
                },
            )

        # 桶内：收盘取桶末值，成交量取桶内求和；1w/1m 的 timestamp 记为桶起点（K 线惯例）
        buckets: Dict[str, Dict[str, Any]] = {}
        for day in sorted(closes):
            key = _candle_bar_start(day, bar)
            ts, close = closes[day]
            slot = buckets.setdefault(key, {"ts": ts, "close": close, "volume": None})
            if ts >= slot["ts"]:
                slot["ts"], slot["close"] = ts, close
            vol = volumes.get(day)
            if vol is not None:
                slot["volume"] = round((slot["volume"] or 0.0) + vol[1], 6)

        points = []
        for key, v in sorted(buckets.items(), key=lambda kv: kv[1]["ts"]):
            # 1d 统一归一到 UTC 日首（日键），真实观测时刻保留在 close_ts
            bar_ts = int(_day_to_dt(key).timestamp())
            point = {
                "timestamp": _iso_utc(bar_ts),
                "ts": bar_ts,
                "close": round(float(v["close"]), 6),
                "volume": v["volume"],
                "close_ts": _iso_utc(v["ts"]),
            }
            high, low = highs.get(key), lows.get(key)
            # 跨源一致性校验：收盘必须落在 [low, high] 内，否则该桶不挂 OHLC（不伪造 K 线）
            if high is not None and low is not None and high >= low and low <= v["close"] <= high:
                point["high"] = round(high, 6)
                point["low"] = round(low, 6)
            points.append(point)
        sample_n = len(points)
        calendar_days = max(1, (points[-1]["ts"] - points[0]["ts"]) // 86400 + 1)
        missing_rate = round(max(0.0, 1.0 - sample_n / calendar_days), 4) if bar == "1d" else 0.0
        ohlc_n = sum(1 for p in points if "high" in p)
        ohlc_coverage = round(ohlc_n / sample_n, 4) if sample_n else 0.0
        has_ohlc = sample_n > 0 and ohlc_n == sample_n
        quality = (
            "empty"
            if sample_n == 0
            else ("partial" if sample_n < _CANDLE_MIN_GOOD[bar] else "good")
        )
        meta = {
            "quality": quality,
            "sample_n": sample_n,
            "bar": bar,
            "days": days,
            "span": f"{points[0]['timestamp'][:10]}~{points[-1]['timestamp'][:10]}",
            "missing_rate": missing_rate,
            "timezone": "UTC",
            "align_method": "daily_last",
            "close_anchor": "snapshot_last",
            "has_ohlc": has_ohlc,
            "ohlc_coverage": ohlc_coverage,
            "ohlc_source": ohlc_source,
            "ohlc_note": _CANDLE_OHLC_NOTE if ohlc_source else "",
            "db": db_path,
            "sources": sorted({r[0] for r in close_rows}),
        }
        return _envelope(
            {
                "symbol": symbol,
                "bar": bar,
                "points": points,
                "sample_n": sample_n,
                "has_ohlc": has_ohlc,
            },
            src_tag,
            meta=meta,
        )

    def _load_daily_ohlc_bars(
        self, db_path: str, ohlc_sub: str, start_ts: int, end_ts: int
    ) -> List[Dict[str, Any]]:
        """读 18 中心回填的真实日线 OHLC（`open_1d/high_1d/low_1d/close_1d/volume_1d`）。

        四腿齐全且自洽（high>=max(open,close)、low<=min(open,close)）的交易日才返回；
        读取失败或无数据返回 []（交由 ticker 合并路径降级，不阻塞）。
        """
        if not ohlc_sub or not _SERIES_IDENT_RE.match(ohlc_sub):
            return []
        try:
            maps = {
                name: {
                    _bucket_key(ts, "daily"): float(value)
                    for _src, value, ts in self._query_series_rows(
                        db_path, ohlc_sub, f"{name}_1d", start_ts, end_ts
                    )
                    if float(value) > 0
                }
                for name in ("open", "high", "low", "close")
            }
            volumes = {
                _bucket_key(ts, "daily"): float(value)
                for _src, value, ts in self._query_series_rows(
                    db_path, ohlc_sub, "volume_1d", start_ts, end_ts
                )
                if float(value) >= 0
            }
        except Exception:
            return []
        days = sorted(set(maps["open"]) & set(maps["high"]) & set(maps["low"]) & set(maps["close"]))
        bars: List[Dict[str, Any]] = []
        for day in days:
            o, h, lo, c = (maps[k][day] for k in ("open", "high", "low", "close"))
            if not (h >= max(o, c) and lo <= min(o, c) and h >= lo):
                continue
            bars.append(
                {
                    "day": day,
                    "ts": int(_day_to_dt(day).timestamp()),
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": c,
                    "volume": volumes.get(day),
                }
            )
        return bars

    def _candles_from_bars(
        self,
        bars: List[Dict[str, Any]],
        symbol: str,
        bar: str,
        days: int,
        ohlc_sub: str,
        db_path: str,
    ) -> Dict[str, Any]:
        """真实日线 OHLC → 目标 bar（1d 原样；1w/1m 聚合 open首/high max/low min/close末/volume和）。"""
        src_tag = "dal_mm_metrics"
        buckets: Dict[str, Dict[str, Any]] = {}
        for item in bars:
            key = _candle_bar_start(item["day"], bar)
            slot = buckets.get(key)
            if slot is None:
                buckets[key] = dict(item)
                continue
            slot["high"] = max(slot["high"], item["high"])
            slot["low"] = min(slot["low"], item["low"])
            slot["close"] = item["close"]
            if slot["volume"] is not None and item["volume"] is not None:
                slot["volume"] = slot["volume"] + item["volume"]

        points = []
        for key, v in sorted(buckets.items(), key=lambda kv: kv[1]["ts"]):
            bar_ts = v["ts"] if bar == "1d" else int(_day_to_dt(key).timestamp())
            points.append(
                {
                    "timestamp": _iso_utc(bar_ts),
                    "ts": bar_ts,
                    "open": round(float(v["open"]), 6),
                    "high": round(float(v["high"]), 6),
                    "low": round(float(v["low"]), 6),
                    "close": round(float(v["close"]), 6),
                    "volume": None if v["volume"] is None else round(float(v["volume"]), 6),
                    "close_ts": _iso_utc(v["ts"]),
                }
            )
        sample_n = len(points)
        calendar_days = max(1, (points[-1]["ts"] - points[0]["ts"]) // 86400 + 1)
        quality = (
            "empty"
            if sample_n == 0
            else ("partial" if sample_n < _CANDLE_MIN_GOOD[bar] else "good")
        )
        meta = {
            "quality": quality,
            "sample_n": sample_n,
            "bar": bar,
            "days": days,
            "span": f"{points[0]['timestamp'][:10]}~{points[-1]['timestamp'][:10]}",
            "missing_rate": (
                round(max(0.0, 1.0 - sample_n / calendar_days), 4) if bar == "1d" else 0.0
            ),
            "timezone": "UTC",
            "align_method": "binance_1h_agg",
            "close_anchor": "bar_close",
            "has_ohlc": True,
            "ohlc_coverage": 1.0,
            "ohlc_source": f"mm_metrics:{ohlc_sub}#1d",
            "ohlc_note": "18 中心 1h K 线聚合日线（真实 OHLC）",
            "db": db_path,
        }
        return _envelope(
            {
                "symbol": symbol,
                "bar": bar,
                "points": points,
                "sample_n": sample_n,
                "has_ohlc": True,
            },
            src_tag,
            meta=meta,
        )

    def _fetch_market_candles_hourly(
        self,
        db_path: str,
        symbol: str,
        days: int,
        start_ts: int,
        end_ts: int,
        params: Dict,
    ) -> Dict[str, Any]:
        """1h K 线：只用 OHLC 子类的小时级 last/high/low（三腿齐全才输出，缺失小时跳过）。"""
        src_tag = "dal_mm_metrics"
        ohlc_sub = self._resolve_ohlc_sub(symbol, params)
        base_meta = {"bar": "1h", "days": days, "timezone": "UTC", "db": db_path}
        if not ohlc_sub:
            return _envelope(
                {"symbol": symbol, "bar": "1h", "points": [], "sample_n": 0, "has_ohlc": False},
                src_tag,
                meta={**base_meta, "quality": "empty", "sample_n": 0, "reason": "no_ohlc_source"},
            )
        try:
            last_rows = self._query_series_rows(db_path, ohlc_sub, "last", start_ts, end_ts)
            high_rows = self._query_series_rows(db_path, ohlc_sub, "high", start_ts, end_ts)
            low_rows = self._query_series_rows(db_path, ohlc_sub, "low", start_ts, end_ts)
            vol_rows = self._query_series_rows(db_path, ohlc_sub, "volume", start_ts, end_ts)
        except Exception as e:
            return _degraded(src_tag, "read_error", f"{type(e).__name__}: {e}")

        closes = _hour_last(last_rows)
        highs = _hour_last(high_rows)
        lows = _hour_last(low_rows)
        volumes = _hour_last(vol_rows)
        hours = sorted(set(closes) & set(highs) & set(lows))
        points = []
        for ts in hours:
            high, low = highs[ts], lows[ts]
            if high < low:
                continue
            point = {
                "timestamp": _iso_utc(ts),
                "ts": ts,
                "close": round(closes[ts], 6),
                "high": round(high, 6),
                "low": round(low, 6),
            }
            if ts in volumes:
                point["volume"] = round(volumes[ts], 6)
            points.append(point)
        sample_n = len(points)
        if sample_n == 0:
            return _envelope(
                {"symbol": symbol, "bar": "1h", "points": [], "sample_n": 0, "has_ohlc": False},
                src_tag,
                meta={
                    **base_meta,
                    "quality": "empty",
                    "sample_n": 0,
                    "reason": "no_history",
                    "has_ohlc": False,
                    "ohlc_source": f"mm_metrics:{ohlc_sub}",
                },
            )
        calendar_hours = max(1, (points[-1]["ts"] - points[0]["ts"]) // 3600 + 1)
        quality = "partial" if sample_n < _CANDLE_MIN_GOOD["1h"] else "good"
        meta = {
            **base_meta,
            "quality": quality,
            "sample_n": sample_n,
            "span": f"{points[0]['timestamp'][:10]}~{points[-1]['timestamp'][:10]}",
            "missing_rate": round(max(0.0, 1.0 - sample_n / calendar_hours), 4),
            "align_method": "hourly_last",
            "has_ohlc": True,
            "ohlc_coverage": 1.0,
            "ohlc_source": f"mm_metrics:{ohlc_sub}",
            "ohlc_note": _CANDLE_OHLC_NOTE,
            "sources": sorted({r[0] for r in last_rows}),
        }
        return _envelope(
            {
                "symbol": symbol,
                "bar": "1h",
                "points": points,
                "sample_n": sample_n,
                "has_ohlc": True,
            },
            src_tag,
            meta=meta,
        )

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
        # 空命中显式标注 no_hit：route_confidence 的 recall_empty 只说明"没有记忆"，
        # 带上 reason 才能在链路 trace 里区分"检索不可用"与"确实无相关记忆"。
        meta = None if memories else {"reason": "no_hit"}
        return _envelope(list(memories or []), "cognitive-loop-entry", meta=meta)

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
