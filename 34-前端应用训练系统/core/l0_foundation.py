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
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

# ============================================================
# 路径注册表（相对项目根；core/l0_foundation.py 位于 <root>/34-前端应用训练系统/core/）
# ============================================================

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

# 18 中心已迁移 PostgreSQL，复用 39 模块统一 PG 辅助模块（FAIL-OPEN）
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "39-金融语义蒸馏系统", "scripts"))
import dc_pg
_EVOLUTION_LOG = ("23-四层闭环自进化交易架构", "dreambuddy_evolution",
                  "logs", "evolution_pipeline.log")
_EVOLUTION_SNAPSHOT = ("23-四层闭环自进化交易架构", "dreambuddy_evolution",
                       "gene_data", "evolution_snapshots.json")
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

# ============================================================
# 信封构造
# ============================================================


def _envelope(data: Any, source: str, *, degraded: bool = False,
              meta: Optional[Dict] = None) -> Dict[str, Any]:
    return {
        "ok": not degraded,
        "data": data,
        "source": source,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "degraded": degraded,
        "meta": meta or {},
    }


def _degraded(source: str, reason: str, error: str = "",
              data: Any = None) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"reason": reason}
    if error:
        meta["error"] = str(error)
    return _envelope(data, source, degraded=True, meta=meta)


# ============================================================
# L0Foundation
# ============================================================

class L0Foundation:
    """L0 数据访问抽象（scope → 数据源 fetcher 注册表）。"""

    # scope → fetcher 方法名
    _SCOPE_REGISTRY = {
        "datacenter.record": "_fetch_datacenter_record",
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

    def __init__(self, root: Optional[str] = None, *,
                 okx_base: str = OKX_BASE, okx_backup: str = OKX_BACKUP,
                 http_timeout: float = 5.0):
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

    def settle(self, result: Optional[Dict], context: Optional[Dict] = None) -> None:
        """工作后沉淀（已落地能力复用）：成功→案例库；有价值发现→认知系统。FAIL-OPEN。"""
        context = context or {}
        intent = context.get("intent", "")
        message = context.get("message", "")
        try:
            self._settle_case(intent, message, result)
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
                ["/home/ubuntu/fis-p0/.venv/bin/python", "/home/ubuntu/fis-p0/scripts/search_cli.py"],
                input=_json.dumps({"cmd": "recall", "query": str(query), "limit": limit}),
                capture_output=True, text=True, timeout=10,
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
        row = dc_pg.fetch_latest_by_source(src, params.get("sub_category"))
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
                    "total": int(m.group(1)), "IDLE": int(m.group(2)), "ARMED": int(m.group(3)),
                    "TRIGGERED": int(m.group(4)), "CLOSED": int(m.group(5)),
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
        return _degraded(f"{self.okx_base}/{self.okx_backup}",
                         "upstream_unavailable", last_error)

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
            return _degraded("cognitive-loop-entry", "invalid_params",
                             "missing param: context")
        top_k = int(params.get("top_k", 5))
        min_quality = params.get("min_quality", "C")
        try:
            cle = self._load_cle()
            memories = cle.recall(context, top_k=top_k, min_quality=min_quality)
        except Exception as e:
            return _degraded("cognitive-loop-entry", "cognitive_unavailable",
                             f"{type(e).__name__}: {e}", data=[])
        return _envelope(list(memories or []), "cognitive-loop-entry")

    # -------- settle 分流（从 L1 执行器上收，行为保持一致，FAIL-OPEN） --------

    def _settle_case(self, intent: str, message: str, result: Optional[Dict]) -> None:
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
        for _k in ("complexity", "entities"):
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
                    return (f"数据源的坑: {data.get('source', '?')} 数值字段全为 0"
                            f"（sub_category={data.get('sub_category', '?')}），数据质量存疑")
        return None

    def _settle_cognitive_valuable(self, intent: str, message: str,
                                   result: Optional[Dict]) -> None:
        finding = self._detect_valuable_finding(result)
        if not finding:
            return
        self._record_cognitive(
            f"[L1探索发现] intent={intent} | 问法: {message} | {finding}")

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
