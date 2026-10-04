"""策略库查询与管理。

从 ml_trade_service.py 提取的 _strategy_registry_* 函数族。
包含策略注册表的增删改查、SQLite/JSON 双后端、事件流、生命周期管理。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def _user_data_dir() -> Path:
    from ml_trade_service import _user_data_dir as _udd
    return _udd()


def _tail_lines(path: Path, *, max_lines: int = 2000, max_bytes: int = 2_000_000) -> List[str]:
    from ml_trade_service import _tail_lines as _tl
    return _tl(path, max_lines=max_lines, max_bytes=max_bytes)


def _config_get() -> Dict[str, Any]:
    from ml_trade_service import CONFIG
    return CONFIG or {}


# ---------------------------------------------------------------------------
# 路径与后端
# ---------------------------------------------------------------------------

def _strategy_registry_path() -> Path:
    return _user_data_dir() / "strategy_registry.json"


def _strategy_registry_db_path() -> Path:
    return _user_data_dir() / "strategy_registry.db"


def _strategy_registry_backend() -> str:
    try:
        s = str((_config_get() or {}).get("strategy_registry_backend") or "sqlite").strip().lower()
    except Exception:
        s = "sqlite"
    return s if s in ("sqlite", "json") else "sqlite"


def _strategy_registry_sqlite_enabled() -> bool:
    return _strategy_registry_backend() == "sqlite"


def _strategy_registry_db_conn() -> sqlite3.Connection:
    p = _strategy_registry_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _strategy_bundles_dir() -> Path:
    return _user_data_dir() / "strategy_bundles"


# ---------------------------------------------------------------------------
# 数据库初始化
# ---------------------------------------------------------------------------

def _strategy_registry_db_init() -> None:
    with contextlib.closing(_strategy_registry_db_conn()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registry_entries (
                k TEXT PRIMARY KEY,
                strategy_id TEXT,
                source_zip TEXT,
                family TEXT,
                stage TEXT,
                tier TEXT,
                updated_at TEXT,
                bundle_id TEXT,
                cost_profile_id TEXT,
                tags_text TEXT,
                tier_reason TEXT,
                entry_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_family ON registry_entries(family)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_tier ON registry_entries(tier)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_updated ON registry_entries(updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_bundle ON registry_entries(bundle_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_registry_cost ON registry_entries(cost_profile_id)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS registry_events (
                id TEXT PRIMARY KEY,
                ts INTEGER,
                trace_id TEXT,
                actor TEXT,
                kind TEXT,
                strategy_id TEXT,
                source_zip TEXT,
                event_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_key_ts ON registry_events(strategy_id, source_zip, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON registry_events(ts)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_policies (
                ref TEXT,
                policy_hash TEXT,
                policy_json TEXT,
                created_at TEXT,
                PRIMARY KEY (ref, policy_hash)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_policies_ref ON eval_policies(ref)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                ts INTEGER,
                actor TEXT,
                role TEXT,
                bundle_id TEXT,
                strategy_id TEXT,
                source_zip TEXT,
                eval_policy_ref TEXT,
                policy_hash TEXT,
                gate_result_hash TEXT,
                note TEXT,
                record_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_bundle ON approvals(bundle_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_key_ts ON approvals(strategy_id, source_zip, ts)")

    _strategy_registry_db_migrate_from_json()


def _strategy_registry_db_migrate_from_json() -> None:
    try:
        p = _strategy_registry_path()
        if not p.exists() or not p.is_file():
            return
        reg = _strategy_registry_load_json_only()
        entries = reg.get("entries") if isinstance(reg.get("entries"), dict) else {}
        if not entries:
            return
        with contextlib.closing(_strategy_registry_db_conn()) as conn:
            try:
                conn.execute("BEGIN")
            except Exception:
                pass
            for k, e in entries.items():
                if not isinstance(e, dict):
                    continue
                try:
                    _strategy_registry_db_upsert_entry(conn, e)
                except Exception:
                    continue
            try:
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.commit()
                except Exception:
                    pass
    except Exception:
        return

    try:
        evp = _strategy_registry_events_path()
        if not evp.exists() or not evp.is_file():
            return
        lines = _tail_lines(evp, max_lines=20000, max_bytes=10_000_000)
        if not lines:
            return
        with contextlib.closing(_strategy_registry_db_conn()) as conn:
            for ln in lines:
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                evt_id = str(obj.get("id") or "").strip()
                if not evt_id:
                    continue
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO registry_events (id, ts, trace_id, actor, kind, strategy_id, source_zip, event_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            evt_id,
                            int(obj.get("ts") or 0),
                            (None if obj.get("trace_id") is None else str(obj.get("trace_id"))),
                            (None if obj.get("actor") is None else str(obj.get("actor"))),
                            (None if obj.get("kind") is None else str(obj.get("kind"))),
                            (None if obj.get("strategy_id") is None else str(obj.get("strategy_id"))),
                            (None if obj.get("source_zip") is None else str(obj.get("source_zip"))),
                            json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                except Exception:
                    continue
    except Exception:
        return


# ---------------------------------------------------------------------------
# JSON 后端
# ---------------------------------------------------------------------------

def _strategy_registry_load_json_only() -> Dict[str, Any]:
    p = _strategy_registry_path()
    try:
        if p.exists() and p.is_file():
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
            reg = obj if isinstance(obj, dict) else {}
            return _strategy_registry_normalize(reg)
    except Exception:
        return {}
    return _strategy_registry_normalize({})


# ---------------------------------------------------------------------------
# 增删改查
# ---------------------------------------------------------------------------

def _strategy_registry_db_upsert_entry(conn: sqlite3.Connection, entry: Dict[str, Any]) -> None:
    e = dict(entry)
    sid = str(e.get("strategy_id") or "").strip()
    z = str(e.get("source_zip") or "").strip()
    if not sid or not z:
        return
    k = _strategy_registry_key(sid, z)
    fam = _strategy_family_normalize(e.get("family")) or "trend"
    stage = _strategy_stage_normalize(e.get("stage")) or "research"
    tier = str(e.get("tier") or "").strip()
    updated_at = str(e.get("updated_at") or "").strip()
    bundle_id = str(e.get("bundle_id") or "").strip() or None
    cost_profile_id = _strategy_cost_profile_id_from_entry(e)
    tags = e.get("tags")
    tags_text = ""
    if isinstance(tags, list):
        tags_text = ",".join([str(x).strip() for x in tags if str(x or "").strip()])
    tier_reason = str(e.get("tier_reason") or "").strip() or None
    entry_json = json.dumps(e, ensure_ascii=False, separators=(",", ":"))
    conn.execute(
        """
        INSERT INTO registry_entries (k, strategy_id, source_zip, family, stage, tier, updated_at, bundle_id, cost_profile_id, tags_text, tier_reason, entry_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(k) DO UPDATE SET
            strategy_id=excluded.strategy_id,
            source_zip=excluded.source_zip,
            family=excluded.family,
            stage=excluded.stage,
            tier=excluded.tier,
            updated_at=excluded.updated_at,
            bundle_id=excluded.bundle_id,
            cost_profile_id=excluded.cost_profile_id,
            tags_text=excluded.tags_text,
            tier_reason=excluded.tier_reason,
            entry_json=excluded.entry_json
        """,
        (k, sid, z, fam, stage, tier, updated_at, bundle_id, cost_profile_id, tags_text, tier_reason, entry_json),
    )


def _strategy_registry_db_upsert_eval_policy(
    conn: sqlite3.Connection,
    *,
    ref: str,
    policy_hash: str,
    policy: Dict[str, Any],
    created_at: str,
) -> None:
    r = str(ref or "").strip()
    h = str(policy_hash or "").strip().lower()
    if not r or not h:
        return
    if len(h) != 64:
        return
    try:
        int(h, 16)
    except Exception:
        return
    conn.execute(
        "INSERT OR IGNORE INTO eval_policies (ref, policy_hash, policy_json, created_at) VALUES (?, ?, ?, ?)",
        (
            r,
            h,
            json.dumps(policy or {}, ensure_ascii=False, separators=(",", ":")),
            str(created_at or "").strip() or datetime.now(timezone.utc).isoformat(),
        ),
    )


def _strategy_cost_profile_id_from_entry(entry: Dict[str, Any]) -> Optional[str]:
    bs = entry.get("backtest_spec") if isinstance(entry.get("backtest_spec"), dict) else None
    if not isinstance(bs, dict):
        return None
    got = bs.get("cost_profile_id")
    if isinstance(got, str):
        s = got.strip().lower()
        if len(s) == 64:
            try:
                int(s, 16)
                return s
            except Exception:
                pass
    fees_bps = bs.get("fees_bps")
    slippage_bps = bs.get("slippage_bps")
    mt = bs.get("market_type")
    if fees_bps is None or slippage_bps is None:
        return None
    try:
        f = float(fees_bps)
        s = float(slippage_bps)
        if not math.isfinite(f) or not math.isfinite(s):
            return None
    except Exception:
        return None
    lm = bs.get("leverage_mode")
    sc = bs.get("stake_currency")
    seed = {
        "fees_bps": float(fees_bps),
        "slippage_bps": float(slippage_bps),
        "market_type": (None if mt is None else str(mt).strip()),
        "leverage_mode": (None if lm is None else str(lm).strip()),
        "stake_currency": (None if sc is None else str(sc).strip()),
    }
    b = json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# 事件流
# ---------------------------------------------------------------------------

def _strategy_registry_events_path() -> Path:
    return _user_data_dir() / "strategy_registry_events.jsonl"


def _strategy_registry_events_tail(
    *,
    strategy_id: str,
    source_zip: str,
    limit: int = 20,
    kinds: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    sid = str(strategy_id or "").strip()
    z = str(source_zip or "").strip()
    if (not sid) or (not z):
        return []
    try:
        limit_n = int(limit)
    except Exception:
        limit_n = 20
    limit_n = max(1, min(200, int(limit_n)))
    p = _strategy_registry_events_path()
    if (not p.exists()) or (not p.is_file()):
        return []
    lines = _tail_lines(p, max_lines=max(2000, limit_n * 50), max_bytes=2000000)
    out: List[Dict[str, Any]] = []
    for ln in reversed(lines):
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("strategy_id") or "").strip() != sid:
            continue
        if str(obj.get("source_zip") or "").strip() != z:
            continue
        k = str(obj.get("kind") or "").strip().lower()
        if kinds is not None and k not in kinds:
            continue
        out.append(
            {
                "id": obj.get("id"),
                "ts": obj.get("ts"),
                "kind": obj.get("kind"),
                "trace_id": obj.get("trace_id"),
            }
        )
        if len(out) >= limit_n:
            break
    out.reverse()
    return out


# ---------------------------------------------------------------------------
# 加载与保存
# ---------------------------------------------------------------------------

def _strategy_registry_load() -> Dict[str, Any]:
    if _strategy_registry_sqlite_enabled():
        try:
            _strategy_registry_db_init()
            with contextlib.closing(_strategy_registry_db_conn()) as conn:
                reg: Dict[str, Any] = {"schema_version": 3, "entries": {}}
                rows = conn.execute("SELECT entry_json FROM registry_entries").fetchall()
                out_entries: Dict[str, Any] = {}
                for r in rows:
                    try:
                        e = json.loads(r[0])
                    except Exception:
                        continue
                    if isinstance(e, dict):
                        sid = str(e.get("strategy_id") or "").strip()
                        z = str(e.get("source_zip") or "").strip()
                        if sid and z:
                            out_entries[_strategy_registry_key(sid, z)] = e
                reg["entries"] = out_entries
                return _strategy_registry_normalize(reg)
        except Exception:
            return _strategy_registry_load_json_only()
    return _strategy_registry_load_json_only()


def _strategy_registry_save(reg: Dict[str, Any]) -> bool:
    if _strategy_registry_sqlite_enabled():
        try:
            _strategy_registry_db_init()
            out = _strategy_registry_normalize(reg)
            entries = out.get("entries") if isinstance(out.get("entries"), dict) else {}
            with contextlib.closing(_strategy_registry_db_conn()) as conn:
                for e in entries.values():
                    if isinstance(e, dict):
                        _strategy_registry_db_upsert_entry(conn, e)
            return True
        except Exception:
            pass
    p = _strategy_registry_path()
    try:
        out = _strategy_registry_normalize(reg)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 键与归一化
# ---------------------------------------------------------------------------

def _strategy_registry_key(strategy_id: str, source_zip: str) -> str:
    sid = str(strategy_id or "").strip()
    z = str(source_zip or "").strip()
    return f"{sid}|{z}"


def _strategy_registry_normalize(reg: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(reg, dict):
        return {"schema_version": 2, "entries": {}}
    if isinstance(reg.get("entries"), dict):
        raw_entries = reg.get("entries")
        out_entries: Dict[str, Any] = {}
        for k0, v0 in raw_entries.items():
            if not isinstance(v0, dict):
                continue
            sid = str(v0.get("strategy_id") or "").strip()
            z = str(v0.get("source_zip") or "").strip()
            if (not sid) or (not z):
                try:
                    parts = str(k0 or "").split("|", 1)
                    if not sid and len(parts) >= 1:
                        sid = str(parts[0] or "").strip()
                    if not z and len(parts) >= 2:
                        z = str(parts[1] or "").strip()
                except Exception:
                    pass
            if (not sid) or (not z):
                continue
            e = dict(v0)
            e["strategy_id"] = sid
            e["source_zip"] = z

            fam_n = _strategy_family_normalize(e.get("family")) if e.get("family") is not None else None
            if fam_n is not None:
                e["family"] = fam_n
            stage_n = _strategy_stage_normalize(e.get("stage")) if e.get("stage") is not None else None
            if stage_n is not None:
                e["stage"] = stage_n
            rb_n = _strategy_robustness_normalize(e.get("robustness")) if e.get("robustness") is not None else None
            if rb_n is not None:
                e["robustness"] = rb_n

            k2 = _strategy_registry_key(sid, z)
            ex = out_entries.get(k2)
            if isinstance(ex, dict):
                ts1 = str(ex.get("updated_at") or "")
                ts2 = str(e.get("updated_at") or "")
                if ts2 and (not ts1 or ts2 >= ts1):
                    out_entries[k2] = e
            else:
                out_entries[k2] = e
        out = dict(reg)
        out.setdefault("schema_version", 2)
        out["entries"] = out_entries
        return out
    out_entries: Dict[str, Any] = {}
    legacy = reg.get("strategies") if isinstance(reg.get("strategies"), dict) else {}
    if isinstance(legacy, dict):
        for sid, it in legacy.items():
            if not isinstance(it, dict):
                continue
            s = str(sid or "").strip()
            if not s:
                continue
            e = dict(it)
            if "strategy_id" not in e:
                e["strategy_id"] = s
            if "source_zip" not in e:
                e["source_zip"] = "*"
            key = _strategy_registry_key(e.get("strategy_id"), e.get("source_zip"))
            out_entries[key] = e
    return {"schema_version": 2, "entries": out_entries}


def _strategy_registry_pick(entries: Dict[str, Any], strategy_id: str, source_zip: str) -> Dict[str, Any]:
    sid = str(strategy_id or "").strip()
    z = str(source_zip or "").strip()
    if not sid:
        return {}
    k_exact = _strategy_registry_key(sid, z)
    it = entries.get(k_exact)
    if isinstance(it, dict):
        return it
    k_any = _strategy_registry_key(sid, "*")
    it2 = entries.get(k_any)
    if isinstance(it2, dict):
        return it2
    best: Optional[Dict[str, Any]] = None
    best_ts = ""
    for k, v in entries.items():
        if not isinstance(v, dict):
            continue
        if str(v.get("strategy_id") or "").strip() != sid:
            continue
        ts = str(v.get("updated_at") or "")
        if (not best) or ts > best_ts:
            best = v
            best_ts = ts
    return best or {}


def _strategy_registry_get_entry(strategy_id: str, source_zip: str) -> Dict[str, Any]:
    reg = _strategy_registry_load()
    entries = reg.get("entries") if isinstance(reg.get("entries"), dict) else {}
    return _strategy_registry_pick(entries, str(strategy_id or "").strip(), str(source_zip or "").strip())


# ---------------------------------------------------------------------------
# 辅助归一化函数
# ---------------------------------------------------------------------------

def _strategy_family_normalize(v: Any) -> Optional[str]:
    s = str(v or "").strip().lower()
    if s in ("trend", "tf"):
        return "trend"
    if s in ("mean_reversion", "meanreversion", "mr"):
        return "mean_reversion"
    if s in ("carry", "cr"):
        return "carry"
    if s in ("breakout", "bo"):
        return "breakout"
    return None


def _strategy_stage_normalize(v: Any) -> Optional[str]:
    s = str(v or "").strip().lower()
    if s in ("research", "model", "deployment"):
        return s
    return None


def _strategy_robustness_normalize(v: Any) -> Optional[str]:
    s = str(v or "").strip().lower()
    if s in ("", "unknown", "na", "n/a", "none"):
        return "unknown"
    if s in ("pass", "ok", "good", "success"):
        return "pass"
    if s in ("warn", "warning"):
        return "warn"
    if s in ("fail", "failed", "bad"):
        return "fail"
    return None


def _strategy_lifecycle_normalize(v: Any) -> Optional[str]:
    s = str(v or "").strip().lower()
    if s in (
        "research_draft",
        "research_validated",
        "model_candidate",
        "approved",
        "deployed_canary",
        "deployed_full",
        "deprecated",
        "rolled_back",
    ):
        return s
    return None


def _strategy_lifecycle_expected_stage(state: Any) -> Optional[str]:
    st = _strategy_lifecycle_normalize(state)
    if st in ("research_draft", "research_validated"):
        return "research"
    if st in ("model_candidate", "approved"):
        return "model"
    if st in ("deployed_canary", "deployed_full", "deprecated", "rolled_back"):
        return "deployment"
    return None


def _strategy_lifecycle_transition_ok(from_state: Any, to_state: Any) -> bool:
    fr = _strategy_lifecycle_normalize(from_state) or "research_draft"
    to = _strategy_lifecycle_normalize(to_state)
    if to is None:
        return False
    _VALID_TRANSITIONS: Dict[str, Set[str]] = {
        "research_draft": {"research_validated", "model_candidate"},
        "research_validated": {"model_candidate", "research_draft"},
        "model_candidate": {"approved", "research_validated", "research_draft"},
        "approved": {"deployed_canary", "model_candidate"},
        "deployed_canary": {"deployed_full", "approved", "rolled_back"},
        "deployed_full": {"deprecated", "deployed_canary", "rolled_back"},
        "deprecated": {"deployed_full", "deployed_canary"},
        "rolled_back": {"deployed_canary", "deployed_full", "approved"},
    }
    return to in _VALID_TRANSITIONS.get(fr, set())


# ---------------------------------------------------------------------------
# S3 后端（可选，fail-open 设计）
# ---------------------------------------------------------------------------

def _strategy_registry_s3_config() -> Dict[str, Any]:
    """读取 S3 配置。未配置时返回空 dict（S3 禁用）。"""
    cfg = _config_get() or {}
    s3_cfg = cfg.get("strategy_registry_s3") if isinstance(cfg.get("strategy_registry_s3"), dict) else {}
    bucket = str(s3_cfg.get("bucket") or "").strip()
    if not bucket:
        return {}
    return {
        "bucket": bucket,
        "prefix": str(s3_cfg.get("prefix") or "strategy_registry/").strip() or "strategy_registry/",
        "region": str(s3_cfg.get("region") or "").strip() or None,
        "endpoint_url": str(s3_cfg.get("endpoint_url") or "").strip() or None,
        "access_key": str(s3_cfg.get("access_key") or "").strip() or None,
        "secret_key": str(s3_cfg.get("secret_key") or "").strip() or None,
    }


def _strategy_registry_s3_enabled() -> bool:
    return bool(_strategy_registry_s3_config())


def _s3_client():
    """延迟创建 S3 客户端。失败返回 None（fail-open）。"""
    cfg = _strategy_registry_s3_config()
    if not cfg:
        return None
    try:
        import boto3
        kwargs: Dict[str, Any] = {}
        if cfg.get("region"):
            kwargs["region_name"] = cfg["region"]
        if cfg.get("endpoint_url"):
            kwargs["endpoint_url"] = cfg["endpoint_url"]
        if cfg.get("access_key") and cfg.get("secret_key"):
            kwargs["aws_access_key_id"] = cfg["access_key"]
            kwargs["aws_secret_access_key"] = cfg["secret_key"]
        return boto3.client("s3", **kwargs)
    except Exception:
        return None


def _s3_key(strategy_id: str, source_zip: str) -> str:
    cfg = _strategy_registry_s3_config()
    prefix = cfg.get("prefix", "strategy_registry/")
    sid = str(strategy_id or "").strip().replace("/", "_")
    z = str(source_zip or "").strip().replace("/", "_")
    return f"{prefix}bundles/{sid}/{z}"


def _strategy_bundle_upload_to_s3(strategy_id: str, source_zip: str, local_path: Path) -> bool:
    """上传策略 bundle 到 S3。失败返回 False（不阻断本地流程）。"""
    if not _strategy_registry_s3_enabled():
        return False
    if not local_path.exists() or not local_path.is_file():
        return False
    s3 = _s3_client()
    if s3 is None:
        return False
    cfg = _strategy_registry_s3_config()
    try:
        s3.upload_file(str(local_path), cfg["bucket"], _s3_key(strategy_id, source_zip))
        return True
    except Exception:
        return False


def _strategy_bundle_download_from_s3(strategy_id: str, source_zip: str) -> Optional[Path]:
    """从 S3 下载策略 bundle 到本地缓存。失败返回 None。"""
    if not _strategy_registry_s3_enabled():
        return None
    s3 = _s3_client()
    if s3 is None:
        return None
    cfg = _strategy_registry_s3_config()
    bundles_dir = _strategy_bundles_dir()
    bundles_dir.mkdir(parents=True, exist_ok=True)
    local_path = bundles_dir / f"{str(strategy_id).replace('/', '_')}_{str(source_zip).replace('/', '_')}"
    try:
        s3.download_file(cfg["bucket"], _s3_key(strategy_id, source_zip), str(local_path))
        return local_path
    except Exception:
        return None


def _strategy_registry_sync_to_s3() -> Dict[str, Any]:
    """将策略库元数据同步到 S3（registry.json + bundles）。

    Returns:
        {"ok": bool, "synced_entries": int, "synced_bundles": int, "errors": [...]}
    """
    if not _strategy_registry_s3_enabled():
        return {"ok": False, "error": "s3_not_configured", "synced_entries": 0, "synced_bundles": 0}
    s3 = _s3_client()
    if s3 is None:
        return {"ok": False, "error": "s3_client_unavailable", "synced_entries": 0, "synced_bundles": 0}

    cfg = _strategy_registry_s3_config()
    reg = _strategy_registry_load()
    entries = reg.get("entries") if isinstance(reg.get("entries"), dict) else {}
    errors: List[str] = []
    synced_entries = 0
    synced_bundles = 0

    # 上传 registry.json
    try:
        import io
        buf = io.BytesIO(json.dumps(reg, ensure_ascii=False).encode("utf-8"))
        s3.upload_fileobj(buf, cfg["bucket"], f"{cfg['prefix']}registry.json")
        synced_entries = len(entries)
    except Exception as e:
        errors.append(f"registry_json:{e}")

    # 上传 bundles
    bundles_dir = _strategy_bundles_dir()
    if bundles_dir.exists():
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            sid = str(entry.get("strategy_id") or "").strip()
            z = str(entry.get("source_zip") or "").strip()
            if not sid or not z:
                continue
            local = bundles_dir / f"{sid.replace('/', '_')}_{z.replace('/', '_')}"
            if local.exists() and local.is_file():
                if _strategy_bundle_upload_to_s3(sid, z, local):
                    synced_bundles += 1
                else:
                    errors.append(f"bundle:{sid}/{z}")

    return {
        "ok": len(errors) == 0,
        "synced_entries": synced_entries,
        "synced_bundles": synced_bundles,
        "errors": errors[:10],
    }


def _strategy_registry_sync_from_s3() -> Dict[str, Any]:
    """从 S3 拉取策略库元数据并合并到本地。"""
    if not _strategy_registry_s3_enabled():
        return {"ok": False, "error": "s3_not_configured", "merged": 0}
    s3 = _s3_client()
    if s3 is None:
        return {"ok": False, "error": "s3_client_unavailable", "merged": 0}
    cfg = _strategy_registry_s3_config()
    try:
        import io
        buf = io.BytesIO()
        s3.download_fileobj(cfg["bucket"], f"{cfg['prefix']}registry.json", buf)
        remote_reg = json.loads(buf.getvalue().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"download_failed:{e}", "merged": 0}

    local_reg = _strategy_registry_load()
    local_entries = local_reg.get("entries") if isinstance(local_reg.get("entries"), dict) else {}
    remote_entries = remote_reg.get("entries") if isinstance(remote_reg.get("entries"), dict) else {}

    merged = 0
    for k, v in remote_entries.items():
        if not isinstance(v, dict):
            continue
        if k not in local_entries:
            local_entries[k] = v
            merged += 1
        else:
            # 以较新的为准
            local_ts = str(local_entries[k].get("updated_at") or "")
            remote_ts = str(v.get("updated_at") or "")
            if remote_ts and (not local_ts or remote_ts > local_ts):
                local_entries[k] = v
                merged += 1

    local_reg["entries"] = local_entries
    _strategy_registry_save(local_reg)
    return {"ok": True, "merged": merged}


__all__ = [
    "_strategy_registry_path",
    "_strategy_registry_db_path",
    "_strategy_registry_backend",
    "_strategy_registry_sqlite_enabled",
    "_strategy_registry_db_conn",
    "_strategy_registry_db_init",
    "_strategy_registry_db_migrate_from_json",
    "_strategy_registry_load_json_only",
    "_strategy_registry_db_upsert_entry",
    "_strategy_registry_db_upsert_eval_policy",
    "_strategy_cost_profile_id_from_entry",
    "_strategy_registry_events_path",
    "_strategy_registry_events_tail",
    "_strategy_bundles_dir",
    "_strategy_registry_load",
    "_strategy_registry_save",
    "_strategy_registry_key",
    "_strategy_registry_normalize",
    "_strategy_registry_pick",
    "_strategy_registry_get_entry",
    "_strategy_family_normalize",
    "_strategy_stage_normalize",
    "_strategy_robustness_normalize",
    "_strategy_lifecycle_normalize",
    "_strategy_lifecycle_expected_stage",
    "_strategy_lifecycle_transition_ok",
    "_strategy_registry_s3_config",
    "_strategy_registry_s3_enabled",
    "_strategy_bundle_upload_to_s3",
    "_strategy_bundle_download_from_s3",
    "_strategy_registry_sync_to_s3",
    "_strategy_registry_sync_from_s3",
]
