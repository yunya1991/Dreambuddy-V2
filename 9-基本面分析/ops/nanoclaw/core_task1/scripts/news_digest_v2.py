#!/usr/bin/env python3
"""
优化版新闻简报生成器（V2.0 - 传统金融分析框架）

基于：
1. 格雷厄姆 - 多德：证券分析（安全边际）
2. 费雪：闲聊法则（多渠道验证）
3. 达利欧：经济机器运行规律（宏观周期）
4. CFA 框架：宏观 - 行业 - 公司三层分析

核心优化：
1. 负面偏见：坏消息权重更高（安全边际原则）
2. 多源验证：单一来源消息降权
3. 周期定位：根据宏观周期调整信号
4. 护城河思维：区分结构性变化和暂时波动
"""

import json
import math
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# 导入分析模块
sys.path.insert(0, str(Path(__file__).parent))
from traditional_finance_analyzer import TraditionalFinanceAnalyzer, SignalAnalysis
from market_data import get_market_snapshot
from news_crawler import fetch_odaily_newsflash, fetch_wallstreetcn_breakfast
from event_mapping_policy import POLICY_PATH, map_event_type, is_macro_topic, is_high_grade_event
from event_ledger_generator import EventLedgerGenerator

BASE_DIR = Path(__file__).parent.parent
SCHEMA_PATH = BASE_DIR / "schema" / "news_contract.schema.json"
WINDOW_PROFILE_PATH = BASE_DIR / "historical_data" / "window_profile_v03.json"
MARKET_STATE_CONFIG_PATH = BASE_DIR / "historical_data" / "market_state_policy_v01.json"
BTC_DAILY_PRICES_PATH = BASE_DIR / "historical_data" / "btc_daily_prices.json"
ANCHOR_POLICY_PATH = BASE_DIR / "historical_data" / "anchor_delta_policy_v1.json"
CONTRACT_VERSION = "core_task1.v2.4"
MACRO_UNKNOWN_TARGET_RATE = 0.20
ANCHOR_DELTA_VERSION = "anchor_delta.v1"
ANCHOR_REGISTRY_PATH = BASE_DIR / "raw" / "anchor_registry.jsonl"
DELTA_REGISTRY_PATH = BASE_DIR / "raw" / "delta_registry.jsonl"
ANCHOR_SCHEMA_PATH = BASE_DIR / "schema" / "anchor_registry.schema.json"
DELTA_SCHEMA_PATH = BASE_DIR / "schema" / "delta_registry.schema.json"
BRIEF_V3_TITLE = "# 加密市场晨报（V9.3/V9.8 优化版）"
BRIEF_V3_REQUIRED_HEADINGS = [
    "## 📊 市场状态诊断",
    "## 📈 核心数据概览",
    "## 🔔 今日要点（12 条）",
    "## 📐 V9.3 事件账本信号分析",
    "## 💼 动态仓位管理建议",
    "## ⚠️ 风险提示",
    "## 📋 明日观察清单",
    "## 🎯 策略总结",
]


def _load_contract_schema() -> dict:
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


CONTRACT_SCHEMA = _load_contract_schema()


DEFAULT_ANCHOR_POLICY = {
    "version": "anchor_delta_policy.v1",
    "multi_anchor_enabled": True,
    "session_windows_utc": {
        "apac": {"start_hour": 0, "end_hour": 7},
        "eu": {"start_hour": 8, "end_hour": 15},
        "us": {"start_hour": 16, "end_hour": 23},
    },
    "ema_alpha": {
        "default": 0.35,
        "avg_signal_score": 0.45,
        "negative_ratio": 0.3,
        "high_risk_ratio": 0.3,
        "active_narrative_ratio": 0.35,
        "window_gate_open_ratio": 0.25,
        "expectation_unknown_ratio_macro": 0.4,
    },
    "adaptive_threshold": {
        "enabled": True,
        "base_score_shift": 0.2,
        "base_offset_score": 0.35,
        "min_multiplier": 0.7,
        "max_multiplier": 1.6,
        "backtest_files": [
            "backtest_result_v93_optimized.json",
            "backtest_result_v9_8_opt_20260311.json",
            "backtest_result_real_news.json",
        ],
    },
}


def _load_anchor_policy() -> dict:
    try:
        with open(ANCHOR_POLICY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                out = dict(DEFAULT_ANCHOR_POLICY)
                for k, v in data.items():
                    out[k] = v
                return out
    except Exception:
        return dict(DEFAULT_ANCHOR_POLICY)
    return dict(DEFAULT_ANCHOR_POLICY)


ANCHOR_POLICY = _load_anchor_policy()


def _load_window_profile() -> dict:
    try:
        with open(WINDOW_PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        return {}
    return {}


WINDOW_PROFILE = _load_window_profile()

FALLBACK_EVENT_WINDOW_PROFILE = {
    "onchain_data": {"recommended_window_range": "[-48h,+48h]", "recommended_horizon_days": 7, "confidence": 0.65},
    "kols_view": {"recommended_window_range": "[-24h,+24h]", "recommended_horizon_days": 3, "confidence": 0.5},
    "kol_view": {"recommended_window_range": "[-24h,+24h]", "recommended_horizon_days": 3, "confidence": 0.5},
    "project_update": {"recommended_window_range": "[-6h,+6h]", "recommended_horizon_days": 1, "confidence": 0.45},
    "monetary_policy": {"recommended_window_range": "[-48h,+48h]", "recommended_horizon_days": 7, "confidence": 0.75},
    "us_data": {"recommended_window_range": "[-48h,+48h]", "recommended_horizon_days": 7, "confidence": 0.75},
    "geopolitics": {"recommended_window_range": "[-48h,+48h]", "recommended_horizon_days": 7, "confidence": 0.7},
    "crypto_regulation": {"recommended_window_range": "[-24h,+24h]", "recommended_horizon_days": 3, "confidence": 0.65},
    "protocol_tech": {"recommended_window_range": "[-24h,+24h]", "recommended_horizon_days": 3, "confidence": 0.55},
    "security_incident": {"recommended_window_range": "[-24h,+24h]", "recommended_horizon_days": 3, "confidence": 0.7},
    "meme_culture": {"recommended_window_range": "[0,+4h]", "recommended_horizon_days": 1, "confidence": 0.5},
    "market_analysis": {"recommended_window_range": "[-48h,+48h]", "recommended_horizon_days": 7, "confidence": 0.6},
    "us_policy": {"recommended_window_range": "[-24h,+24h]", "recommended_horizon_days": 3, "confidence": 0.6},
}

ASSET_BUCKET_EVENT_TYPES = {
    "crypto_beta": {"onchain_data", "project_update", "protocol_tech", "meme_culture", "kols_view", "kol_view"},
    "macro_policy": {"monetary_policy", "us_data", "geopolitics", "crypto_regulation", "market_analysis", "us_policy"},
    "security_defensive": {"security_incident"},
}

MARKET_STATE_WINDOW_ADJUSTMENT = {
    "risk_off": {
        "macro_policy": "[-48h,+48h]",
        "crypto_beta": "[-6h,+6h]",
        "security_defensive": "[-24h,+24h]",
    },
    "risk_on": {
        "macro_policy": "[-24h,+24h]",
        "crypto_beta": "[-24h,+24h]",
        "security_defensive": "[-24h,+24h]",
    },
    "high_vol": {
        "macro_policy": "[-48h,+48h]",
        "crypto_beta": "[0,+4h]",
        "security_defensive": "[-48h,+48h]",
    },
    "neutral": {
        "macro_policy": "[-24h,+24h]",
        "crypto_beta": "[-24h,+24h]",
        "security_defensive": "[-24h,+24h]",
    },
}

DEFAULT_MARKET_STATE_CONFIG = {
    "version": "market_state_policy.v1",
    "thresholds": {
        "high_vol_vix": 28.0,
        "risk_off_vix": 22.0,
        "risk_on_vix_max": 20.0,
        "risk_on_btc_change_min": 2.0,
        "risk_off_nasdaq_change_max": 0.0,
        "risk_on_nasdaq_change_min": 0.0,
    },
    "window_adjustment": MARKET_STATE_WINDOW_ADJUSTMENT,
    "security_defensive_keywords": [
        "黑客", "被盗", "漏洞", "攻击", "exploit", "hack", "ransomware",
        "清算", "爆仓", "杠杆", "穿仓", "暂停提现", "安全事件",
    ],
}


def _load_market_state_config() -> dict:
    try:
        with open(MARKET_STATE_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        return dict(DEFAULT_MARKET_STATE_CONFIG)
    return dict(DEFAULT_MARKET_STATE_CONFIG)


def _build_window_policy_map() -> dict:
    rows = (WINDOW_PROFILE or {}).get("event_type_profiles", [])
    mapping = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        et = str(row.get("event_type") or "").strip()
        if not et:
            continue
        mapping[et] = {
            "recommended_window_range": str(row.get("recommended_window_range") or "[-24h,+24h]"),
            "recommended_horizon_days": int(row.get("recommended_horizon_days", 2) or 2),
            "confidence": float(row.get("confidence", 0.0) or 0.0),
        }
    for et, cfg in FALLBACK_EVENT_WINDOW_PROFILE.items():
        if et not in mapping:
            mapping[et] = dict(cfg)
    return mapping


WINDOW_POLICY_MAP = _build_window_policy_map()
MARKET_STATE_CONFIG = _load_market_state_config()
MARKET_STATE_THRESHOLDS = dict(DEFAULT_MARKET_STATE_CONFIG.get("thresholds", {}))
MARKET_STATE_THRESHOLDS.update(dict((MARKET_STATE_CONFIG or {}).get("thresholds", {})))
MARKET_STATE_WINDOW_ADJUSTMENT_RUNTIME = dict(DEFAULT_MARKET_STATE_CONFIG.get("window_adjustment", {}))
MARKET_STATE_WINDOW_ADJUSTMENT_RUNTIME.update(dict((MARKET_STATE_CONFIG or {}).get("window_adjustment", {})))
SECURITY_DEFENSIVE_KEYWORDS = [
    str(x).lower()
    for x in ((MARKET_STATE_CONFIG or {}).get("security_defensive_keywords") or DEFAULT_MARKET_STATE_CONFIG["security_defensive_keywords"])
    if str(x).strip()
]


def _window_range_to_max_age_hours(window_range: str) -> int:
    mapping = {
        "[0,+4h]": 4,
        "[-6h,+6h]": 12,
        "[-24h,+24h]": 48,
        "[-48h,+48h]": 96,
    }
    return mapping.get(str(window_range or "").strip(), 48)

DEFAULT_ENUMS = {
    "source_confidence": {"high", "medium", "low"},
    "impact_horizon": {"T0", "T1", "T2", "T3"},
    "attention_type": {"narrative", "event", "policy", "security", "market_microstructure"},
    "event_window_range": {"[-48h,+48h]", "[-24h,+24h]", "[-6h,+6h]", "[0,+4h]"},
    "expectation_bucket": {"偏鹰", "符合", "偏鸽", "利多", "中性", "利空", "unknown"},
    "risk_action_proposal": {"hold", "reduce", "increase", "hedge", "stop_loss", "take_profit"},
    "narrative_status": {"active", "cooling", "archive"},
}


def _normalize_attention_type(value: str) -> str:
    v = str(value or "").strip().lower()
    if not v:
        return "event"
    aliases = {
        "regulatory": "policy",
        "regulation": "policy",
        "policy": "policy",
        "macro_policy": "policy",
        "economic_data": "event",
        "economic": "event",
        "macro": "event",
        "commodity": "event",
        "technology": "narrative",
        "tech": "narrative",
        "security": "security",
        "market_microstructure": "market_microstructure",
        "microstructure": "market_microstructure",
        "onchain": "market_microstructure",
        "leverage": "market_microstructure",
        "liquidity": "market_microstructure",
        "event": "event",
        "narrative": "narrative",
    }
    out = aliases.get(v, "")
    if out:
        return out
    allowed = _schema_enum_values("attention_type")
    if v in allowed:
        return v
    return "event"


def _schema_enum_values(field: str) -> set[str]:
    defs = (CONTRACT_SCHEMA or {}).get("$defs", {})
    common = defs.get("Common", {})
    properties = common.get("properties", {})
    enum_values = properties.get(field, {}).get("enum", [])
    if isinstance(enum_values, list) and enum_values:
        return {str(v) for v in enum_values}
    return set(DEFAULT_ENUMS.get(field, set()))


def _schema_crypto_categories() -> set[str]:
    defs = (CONTRACT_SCHEMA or {}).get("$defs", {})
    props = defs.get("CryptoItem", {}).get("allOf", [])
    for node in props:
        if isinstance(node, dict):
            enum_values = (
                node.get("properties", {})
                .get("category", {})
                .get("enum", [])
            )
            if isinstance(enum_values, list) and enum_values:
                return {str(v) for v in enum_values}
    return {"onchain_data", "kols_view", "project_update"}


def _schema_macro_topics() -> set[str]:
    defs = (CONTRACT_SCHEMA or {}).get("$defs", {})
    props = defs.get("MacroItem", {}).get("allOf", [])
    for node in props:
        if isinstance(node, dict):
            enum_values = (
                node.get("properties", {})
                .get("topic", {})
                .get("enum", [])
            )
            if isinstance(enum_values, list) and enum_values:
                return {str(v) for v in enum_values}
    return {"fed", "us_data", "geopolitics", "us_policy", "market_analysis"}


def _is_non_empty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_item_schema(item: dict, item_kind: str, idx: int) -> list[str]:
    errs: list[str] = []
    prefix = f"{item_kind}[{idx}]"
    if not _is_non_empty_str(item.get("title")):
        errs.append(f"{prefix}.title 不能为空字符串")
    if not _is_non_empty_str(item.get("source_url")):
        errs.append(f"{prefix}.source_url 不能为空字符串")
    if not (_is_non_empty_str(item.get("published_at")) or _is_non_empty_str(item.get("fetched_at"))):
        errs.append(f"{prefix} 需至少包含 published_at 或 fetched_at")
    if not _is_non_empty_str(item.get("analysis_text")):
        errs.append(f"{prefix}.analysis_text 不能为空字符串")
    if item_kind == "raw_crypto":
        if str(item.get("category") or "") not in _schema_crypto_categories():
            errs.append(f"{prefix}.category 不在枚举内")
    if item_kind == "raw_macro":
        if str(item.get("topic") or "") not in _schema_macro_topics():
            errs.append(f"{prefix}.topic 不在枚举内")
        if not _is_non_empty_str(item.get("key_fact")):
            errs.append(f"{prefix}.key_fact 不能为空字符串")
    for field in [
        "source_confidence",
        "impact_horizon",
        "attention_type",
        "event_window_range",
        "expectation_bucket",
        "risk_action_proposal",
        "narrative_status",
    ]:
        value = item.get(field)
        if value is None:
            continue
        if str(value) not in _schema_enum_values(field):
            errs.append(f"{prefix}.{field}={value} 不在枚举内")
    if "attention_score" in item:
        v = item.get("attention_score")
        if not isinstance(v, int) or v < 0 or v > 5:
            errs.append(f"{prefix}.attention_score 必须为 0-5 整数")
    for field in ["community_base_score", "decay_factor", "community_effective_score", "source_quality_score"]:
        if field in item and item.get(field) is not None:
            v = item.get(field)
            if not isinstance(v, (int, float)):
                errs.append(f"{prefix}.{field} 必须为数值")
    return errs


def _validate_contract_payload(payload: dict) -> list[str]:
    errs: list[str] = []
    if not _is_non_empty_str(payload.get("version")):
        errs.append("payload.version 不能为空")
    if not _is_non_empty_str(payload.get("generated_at")):
        errs.append("payload.generated_at 不能为空")
    if not isinstance(payload.get("time_window_hours"), int) or int(payload.get("time_window_hours")) < 1:
        errs.append("payload.time_window_hours 必须为 >=1 的整数")
    raw_crypto = payload.get("raw_crypto")
    raw_macro = payload.get("raw_macro")
    if not isinstance(raw_crypto, list):
        errs.append("payload.raw_crypto 必须为数组")
        raw_crypto = []
    if not isinstance(raw_macro, list):
        errs.append("payload.raw_macro 必须为数组")
        raw_macro = []
    for idx, item in enumerate(raw_crypto):
        if not isinstance(item, dict):
            errs.append(f"raw_crypto[{idx}] 必须为对象")
            continue
        errs.extend(_validate_item_schema(item, "raw_crypto", idx))
    for idx, item in enumerate(raw_macro):
        if not isinstance(item, dict):
            errs.append(f"raw_macro[{idx}] 必须为对象")
            continue
        errs.extend(_validate_item_schema(item, "raw_macro", idx))
    return errs


def _validate_ledger_entries(entries) -> list[str]:
    errs: list[str] = []
    allowed_actions = _schema_enum_values("risk_action_proposal")
    allowed_windows = _schema_enum_values("event_window_range")
    allowed_expectation = _schema_enum_values("expectation_bucket")
    for idx, entry in enumerate(entries or []):
        row = asdict(entry) if hasattr(entry, "__dataclass_fields__") else dict(entry)
        prefix = f"event_ledger[{idx}]"
        if not _is_non_empty_str(row.get("event_id")):
            errs.append(f"{prefix}.event_id 不能为空")
        if not _is_non_empty_str(row.get("timestamp")):
            errs.append(f"{prefix}.timestamp 不能为空")
        if not _is_non_empty_str(row.get("title")):
            errs.append(f"{prefix}.title 不能为空")
        if not _is_non_empty_str(row.get("source_url")):
            errs.append(f"{prefix}.source_url 不能为空")
        if not _is_non_empty_str(row.get("published_at")):
            errs.append(f"{prefix}.published_at 不能为空")
        if str(row.get("window_range") or "") not in allowed_windows:
            errs.append(f"{prefix}.window_range 不在枚举内")
        if str(row.get("risk_action_proposal") or "") not in allowed_actions:
            errs.append(f"{prefix}.risk_action_proposal 不在枚举内")
        if str(row.get("expectation_bucket") or "unknown") not in allowed_expectation:
            errs.append(f"{prefix}.expectation_bucket 不在枚举内")
    return errs


def _run_step(step_name: str, func, audit_rows: list, max_retries: int = 0):
    started_at = datetime.now().isoformat()
    attempts = 0
    last_error = ""
    while attempts <= max_retries:
        attempts += 1
        begin = time.perf_counter()
        try:
            result = func()
            audit_rows.append(
                {
                    "step": step_name,
                    "status": "succeeded",
                    "started_at": started_at,
                    "ended_at": datetime.now().isoformat(),
                    "duration_ms": int((time.perf_counter() - begin) * 1000),
                    "retry_count": attempts - 1,
                    "failure_reason": "",
                }
            )
            return result
        except Exception as exc:
            last_error = str(exc)
            if attempts > max_retries:
                audit_rows.append(
                    {
                        "step": step_name,
                        "status": "failed",
                        "started_at": started_at,
                        "ended_at": datetime.now().isoformat(),
                        "duration_ms": int((time.perf_counter() - begin) * 1000),
                        "retry_count": attempts - 1,
                        "failure_reason": last_error,
                    }
                )
                raise


def _confidence_to_score(conf: str) -> float:
    return {"high": 1.0, "medium": 0.7, "low": 0.4}.get(str(conf or "medium"), 0.7)


def _source_quality_profiles(items: list) -> dict:
    source_stats: dict[str, dict] = {}
    for item in items:
        key = _source_key(item)
        stats = source_stats.setdefault(
            key,
            {"count": 0, "url_ok": 0, "time_ok": 0, "body_ok": 0, "confidence_sum": 0.0},
        )
        stats["count"] += 1
        if _is_non_empty_str(item.get("source_url")):
            stats["url_ok"] += 1
        if _is_non_empty_str(item.get("published_at")) or _is_non_empty_str(item.get("fetched_at")):
            stats["time_ok"] += 1
        body_text = str(item.get("summary") or item.get("key_fact") or "").strip()
        if body_text and "正文缺失，仅标题级信息" not in body_text:
            stats["body_ok"] += 1
        stats["confidence_sum"] += _confidence_to_score(str(item.get("source_confidence") or "medium"))
    profiles: dict[str, dict] = {}
    for source, stats in source_stats.items():
        count = max(1, int(stats["count"]))
        url_rate = stats["url_ok"] / count
        time_rate = stats["time_ok"] / count
        body_rate = stats["body_ok"] / count
        conf_avg = stats["confidence_sum"] / count
        score = 0.35 * url_rate + 0.25 * time_rate + 0.2 * body_rate + 0.2 * conf_avg
        profiles[source] = {
            "count": count,
            "url_rate": round(url_rate, 4),
            "time_rate": round(time_rate, 4),
            "body_rate": round(body_rate, 4),
            "confidence_avg": round(conf_avg, 4),
            "source_quality_score": round(max(0.0, min(1.0, score)), 4),
        }
    return profiles


def _with_source_quality(items: list, profiles: dict) -> list:
    out = []
    for item in items:
        merged = dict(item)
        profile = profiles.get(_source_key(merged), {})
        score = float(profile.get("source_quality_score", 0.6))
        merged["source_quality_score"] = round(score, 4)
        flags = _normalize_risk_flags(merged.get("risk_flags") or [])
        if score < 0.55:
            if "来源质量退化" not in flags:
                flags.append("来源质量退化")
            merged["source_confidence"] = "low"
            merged["confidence"] = "low"
        merged["risk_flags"] = flags
        out.append(merged)
    return out


def _evidence_grade(item: dict) -> str:
    mention_count = max(1, int(item.get("mention_count", 1) or 1))
    conf = str(item.get("source_confidence") or "medium")
    quality = float(item.get("source_quality_score", 0.6) or 0.6)
    analysis_text = str(item.get("analysis_text") or "").strip()
    flags = [str(x) for x in (item.get("risk_flags") or [])]
    severe = {"数据不可复核", "正文缺失，仅标题级信息", "主备源不可用", "无数据支撑"}
    severe_hits = sum(1 for f in flags if f in severe)
    if mention_count >= 2 and conf == "high" and quality >= 0.75 and analysis_text and severe_hits == 0:
        return "A"
    if mention_count >= 2 and conf in {"high", "medium"} and quality >= 0.6 and severe_hits <= 1:
        return "B"
    if mention_count >= 1 and quality >= 0.4:
        return "C"
    return "D"


def _enforce_risk_guardrails(item: dict) -> dict:
    merged = dict(item)
    evidence = str(merged.get("evidence_grade") or "C")
    action = str(merged.get("risk_action_proposal") or "hold")
    flags = _normalize_risk_flags(merged.get("risk_flags") or [])
    expectation_bucket = str(merged.get("expectation_bucket") or "unknown")
    macro_unknown = bool(is_macro_topic(merged.get("topic"))) and expectation_bucket == "unknown"
    dynamic_window_gate_open = bool(merged.get("dynamic_window_gate_open", True))
    if evidence in {"C", "D"} and "证据等级不足" not in flags:
        flags.append("证据等级不足")
    allowed_low_evidence = {"hold", "reduce", "hedge", "stop_loss"}
    if evidence in {"C", "D"} and action not in allowed_low_evidence:
        action = "hold"
    if macro_unknown and action in {"increase", "take_profit"}:
        action = "hold"
    if not dynamic_window_gate_open:
        action = "hold"
        if "超出动态窗口" not in flags:
            flags.append("超出动态窗口")
    merged["risk_flags"] = flags
    merged["risk_action_proposal"] = action
    merged["execution_gate"] = "readonly_advisory_dynamic_window"
    return merged


def _coverage_report(crypto_news: list, macro_news: list) -> dict:
    all_news = (crypto_news or []) + (macro_news or [])
    total = len(all_news)
    analysis_non_empty = sum(1 for x in all_news if _is_non_empty_str(x.get("analysis_text")))
    cross_market_non_empty = sum(1 for x in all_news if _is_non_empty_str(x.get("cross_market_map")))
    macro_total = len(macro_news or [])
    macro_expectation_known = sum(
        1
        for x in (macro_news or [])
        if str(x.get("expectation_bucket") or "unknown") != "unknown"
    )
    expectation_sources = {"explicit_numeric": 0, "implied_text": 0, "implied_market": 0, "none": 0}
    for x in (macro_news or []):
        src = str(x.get("expectation_source") or "none")
        if src not in expectation_sources:
            src = "none"
        expectation_sources[src] += 1
    dynamic_gate_open = sum(1 for x in all_news if bool(x.get("dynamic_window_gate_open", True)))
    window_policy_source = {"calibrated_v03": 0, "default_impact_horizon": 0}
    market_state_distribution = {"risk_off": 0, "risk_on": 0, "high_vol": 0, "neutral": 0}
    asset_bucket_distribution = {"crypto_beta": 0, "macro_policy": 0, "security_defensive": 0}
    applied_event_types = set()
    for x in all_news:
        src = str(x.get("window_policy_source") or "default_impact_horizon")
        if src not in window_policy_source:
            src = "default_impact_horizon"
        window_policy_source[src] += 1
        ms = str(x.get("window_policy_market_state") or "neutral")
        if ms not in market_state_distribution:
            ms = "neutral"
        market_state_distribution[ms] += 1
        ab = str(x.get("window_policy_asset_bucket") or "crypto_beta")
        if ab not in asset_bucket_distribution:
            ab = "crypto_beta"
        asset_bucket_distribution[ab] += 1
        if src == "calibrated_v03":
            applied_event_types.add(str(x.get("event_type") or "unknown"))
    macro_unknown_count = max(0, macro_total - macro_expectation_known)
    macro_unknown_rate = (macro_unknown_count / macro_total) if macro_total else 0.0
    return {
        "ts": datetime.now().isoformat(),
        "sample_count": total,
        "analysis_text_non_empty_rate": round((analysis_non_empty / total) if total else 1.0, 4),
        "cross_market_map_non_empty_rate": round((cross_market_non_empty / total) if total else 1.0, 4),
        "macro_expectation_known_rate": round((macro_expectation_known / macro_total) if macro_total else 1.0, 4),
        "unknown_expectation_count_macro": macro_unknown_count,
        "unknown_expectation_rate_macro": round(macro_unknown_rate, 4),
        "unknown_expectation_target_rate_macro": MACRO_UNKNOWN_TARGET_RATE,
        "unknown_expectation_target_hit_macro": bool(macro_unknown_rate < MACRO_UNKNOWN_TARGET_RATE) if macro_total else True,
        "expectation_source_distribution_macro": expectation_sources,
        "dynamic_window_gate_open_rate": round((dynamic_gate_open / total) if total else 1.0, 4),
        "window_policy_source_distribution": window_policy_source,
        "window_policy_market_state_distribution": market_state_distribution,
        "window_policy_asset_bucket_distribution": asset_bucket_distribution,
        "window_policy_event_type_applied_count": len(applied_event_types),
    }


def _apply_market_implied_expectation(items: list, market_snapshot: dict) -> list:
    nasdaq_change = (
        market_snapshot.get("traditional", {})
        .get("nasdaq", {})
        .get("change_24h", 0.0)
    )
    vix_value = (
        market_snapshot.get("traditional", {})
        .get("vix", {})
        .get("value", 0.0)
    )
    btc_change = (
        market_snapshot.get("crypto", {})
        .get("btc", {})
        .get("change_24h", 0.0)
    )
    try:
        nasdaq_change = float(nasdaq_change or 0.0)
    except Exception:
        nasdaq_change = 0.0
    try:
        vix_value = float(vix_value or 0.0)
    except Exception:
        vix_value = 0.0
    try:
        btc_change = float(btc_change or 0.0)
    except Exception:
        btc_change = 0.0
    market_signal = 0.0
    if abs(nasdaq_change) >= 0.4:
        market_signal += (nasdaq_change / 3.0)
    if abs(btc_change) >= 0.8:
        market_signal += (btc_change / 5.0)
    if vix_value >= 1.0:
        market_signal -= ((vix_value - 20.0) / 20.0)
    market_signal = max(-1.0, min(1.0, market_signal))
    if abs(market_signal) < 0.2:
        return [dict(x) for x in (items or [])]
    out = []
    for item in items or []:
        merged = dict(item)
        has_explicit = isinstance(merged.get("actual_value"), (int, float)) and isinstance(merged.get("expected_value"), (int, float))
        has_implied = merged.get("implied_surprise_score") is not None
        if has_explicit or has_implied:
            out.append(merged)
            continue
        topic = str(merged.get("topic") or "")
        magnitude = max(0.1, min(1.0, abs(market_signal)))
        if topic in {"fed", "us_data"}:
            score = -magnitude if market_signal > 0 else magnitude
        else:
            score = magnitude if market_signal > 0 else -magnitude
        merged["implied_surprise_score"] = round(score, 4)
        merged["surprise"] = round(score, 4)
        merged["expectation_source"] = "implied_market"
        flags = _normalize_risk_flags(merged.get("risk_flags") or [])
        if "预期差使用市场隐含预期" not in flags:
            flags.append("预期差使用市场隐含预期")
        merged["risk_flags"] = flags
        out.append(merged)
    return out


def _methodology_snapshot(
    coverage_report: dict,
    source_profiles: dict,
) -> dict:
    source_scores = [float(v.get("source_quality_score", 0.0) or 0.0) for v in (source_profiles or {}).values()]
    source_mean = sum(source_scores) / len(source_scores) if source_scores else 0.0
    return {
        "contract_version": CONTRACT_VERSION,
        "schema_path": str(SCHEMA_PATH),
        "mapping_policy_path": str(POLICY_PATH),
        "community_decay_profile": {
            "market_microstructure_half_life_hours": 6,
            "event_security_policy_half_life_hours": 24,
            "narrative_half_life_hours": 72,
        },
        "risk_guardrails": {
            "unknown_macro_forbid_actions": ["increase", "take_profit"],
            "low_evidence_forbid_actions": ["increase", "take_profit"],
            "source_quality_degrade_threshold": 0.55,
            "execution_gate": "readonly_advisory_dynamic_window",
            "dynamic_window_gate_enabled": True,
            "window_profile_path": str(WINDOW_PROFILE_PATH),
            "window_policy_event_type_count": len(WINDOW_POLICY_MAP),
            "market_state_config_path": str(MARKET_STATE_CONFIG_PATH),
            "market_state_thresholds": dict(MARKET_STATE_THRESHOLDS),
            "market_trend_state_policy": {"asset": "BTC", "lookback_days": 20, "band": 0.05},
        },
        "coverage": {
            "analysis_text_non_empty_rate": float(coverage_report.get("analysis_text_non_empty_rate", 0.0) or 0.0),
            "cross_market_map_non_empty_rate": float(coverage_report.get("cross_market_map_non_empty_rate", 0.0) or 0.0),
            "macro_expectation_known_rate": float(coverage_report.get("macro_expectation_known_rate", 0.0) or 0.0),
            "expectation_source_distribution_macro": dict(coverage_report.get("expectation_source_distribution_macro") or {}),
            "window_policy_source_distribution": dict(coverage_report.get("window_policy_source_distribution") or {}),
            "window_policy_market_state_distribution": dict(coverage_report.get("window_policy_market_state_distribution") or {}),
            "window_policy_asset_bucket_distribution": dict(coverage_report.get("window_policy_asset_bucket_distribution") or {}),
            "window_policy_event_type_applied_count": int(coverage_report.get("window_policy_event_type_applied_count", 0) or 0),
        },
        "source_profile_summary": {
            "source_count": len(source_scores),
            "source_quality_mean": round(source_mean, 4),
        },
    }


def _flatten_snapshot(snapshot: dict, parent_key: str = "") -> dict:
    flat = {}
    for key, value in (snapshot or {}).items():
        current = f"{parent_key}.{key}" if parent_key else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_snapshot(value, current))
        else:
            flat[current] = value
    return flat


def _methodology_diff(prev_snapshot: dict, current_snapshot: dict) -> dict:
    prev_flat = _flatten_snapshot(prev_snapshot or {})
    curr_flat = _flatten_snapshot(current_snapshot or {})
    added = {}
    removed = {}
    changed = {}
    for key, value in curr_flat.items():
        if key not in prev_flat:
            added[key] = value
        elif prev_flat[key] != value:
            changed[key] = {"from": prev_flat[key], "to": value}
    for key, value in prev_flat.items():
        if key not in curr_flat:
            removed[key] = value
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "change_count": len(added) + len(removed) + len(changed),
    }


def _methodology_diff_summary(methodology_diff: dict, top_k: int = 8) -> dict:
    added = dict(methodology_diff.get("added") or {})
    removed = dict(methodology_diff.get("removed") or {})
    changed = dict(methodology_diff.get("changed") or {})
    changed_rows = []
    for field in sorted(changed.keys()):
        row = dict(changed[field] or {})
        changed_rows.append(
            {
                "field": field,
                "from": row.get("from"),
                "to": row.get("to"),
            }
        )
    added_fields = sorted(list(added.keys()))
    removed_fields = sorted(list(removed.keys()))
    preview = {
        "added_fields": added_fields[:top_k],
        "removed_fields": removed_fields[:top_k],
        "changed_fields": [x["field"] for x in changed_rows[:top_k]],
        "changed_preview": changed_rows[:top_k],
    }
    return {
        "change_count": int(methodology_diff.get("change_count", 0) or 0),
        "added_count": len(added_fields),
        "removed_count": len(removed_fields),
        "changed_count": len(changed_rows),
        "preview": preview,
    }


def _read_last_methodology_snapshot(methodology_path: Path) -> dict:
    if not methodology_path.exists():
        return {}
    last = ""
    try:
        with open(methodology_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = line
        if not last:
            return {}
        data = json.loads(last)
        snapshot = data.get("methodology_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
    except Exception:
        return {}
    return {}


def _run_rolling_window_calibration(raw_dir: Path, file_ts: str) -> dict:
    ledger_files = sorted(raw_dir.glob("event_ledger_*.jsonl"))
    if not ledger_files:
        return {
            "enabled": False,
            "reason": "missing_ledger_files",
            "window_calibration_path": "",
            "window_version_table_path": "",
            "window_profile_path": str(WINDOW_PROFILE_PATH),
            "version_table_count": 0,
            "ledger_file_count": 0,
        }
    selected_files = ledger_files[-21:]
    try:
        from event_ledger_backtester import EventLedgerBacktester, BacktestConfig
    except Exception as exc:
        return {
            "enabled": False,
            "reason": f"import_backtester_failed:{exc}",
            "window_calibration_path": "",
            "window_version_table_path": "",
            "window_profile_path": str(WINDOW_PROFILE_PATH),
            "version_table_count": 0,
            "ledger_file_count": len(selected_files),
        }
    data_dir = BASE_DIR / "historical_data"
    cfg = BacktestConfig(start_date="2020-01-01", end_date=datetime.now().strftime("%Y-%m-%d"))
    backtester = EventLedgerBacktester(cfg)
    prices = backtester.load_prices(data_dir)
    if not prices:
        return {
            "enabled": False,
            "reason": "missing_price_data",
            "window_calibration_path": "",
            "window_version_table_path": "",
            "window_profile_path": str(WINDOW_PROFILE_PATH),
            "version_table_count": 0,
            "ledger_file_count": len(selected_files),
        }
    entries = []
    for p in selected_files:
        try:
            entries.extend(backtester.load_ledger(p))
        except Exception:
            continue
    if not entries:
        return {
            "enabled": False,
            "reason": "missing_ledger_entries",
            "window_calibration_path": "",
            "window_version_table_path": "",
            "window_profile_path": str(WINDOW_PROFILE_PATH),
            "version_table_count": 0,
            "ledger_file_count": len(selected_files),
        }
    calibration = backtester.calibrate_event_windows(entries, prices)
    calibration["rolling_window"] = {
        "ledger_files_used": [str(x) for x in selected_files],
        "ledger_file_count": len(selected_files),
        "entry_count": len(entries),
    }
    window_calibration_path = raw_dir / f"window_calibration_{file_ts}.json"
    with open(window_calibration_path, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2, ensure_ascii=False)
    window_version_rows = list(calibration.get("window_version_table") or [])
    window_version_table_path = raw_dir / f"window_version_table_{file_ts}.json"
    with open(window_version_table_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": calibration.get("generated_at"),
                "row_count": len(window_version_rows),
                "rows": window_version_rows,
                "rolling_window": calibration.get("rolling_window", {}),
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    with open(WINDOW_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2, ensure_ascii=False)
    return {
        "enabled": True,
        "reason": "",
        "window_calibration_path": str(window_calibration_path),
        "window_version_table_path": str(window_version_table_path),
        "window_profile_path": str(WINDOW_PROFILE_PATH),
        "version_table_count": len(window_version_rows),
        "ledger_file_count": len(selected_files),
    }


def _risk_action_events(items: list, now: datetime, file_ts: str) -> list:
    events = []
    for idx, row in enumerate(items):
        action = str(row.get("risk_action_proposal") or "hold")
        evidence = str(row.get("evidence_grade") or "C")
        gate_open = bool(row.get("dynamic_window_gate_open", True))
        enforceable = action in {"reduce", "hedge", "stop_loss"} and evidence in {"A", "B"} and gate_open
        events.append(
            {
                "event_id": f"RAE-{file_ts}-{idx + 1:04d}",
                "ts": now.isoformat(),
                "title": str(row.get("title") or ""),
                "source_url": str(row.get("source_url") or ""),
                "published_at": str(row.get("published_at") or row.get("fetched_at") or ""),
                "event_type": str(row.get("event_type") or "unknown"),
                "event_window_range": str(row.get("event_window_range") or "[-24h,+24h]"),
                "window_policy_source": str(row.get("window_policy_source") or "default_impact_horizon"),
                "window_policy_confidence": float(row.get("window_policy_confidence", 0.0) or 0.0),
                "window_policy_horizon_days": int(row.get("window_policy_horizon_days", 1) or 1),
                "window_policy_market_state": str(row.get("window_policy_market_state") or "neutral"),
                "window_policy_asset_bucket": str(row.get("window_policy_asset_bucket") or "crypto_beta"),
                "window_policy_base_range": str(row.get("window_policy_base_range") or "[-24h,+24h]"),
                "event_age_hours": float(row.get("event_age_hours", 0.0) or 0.0),
                "dynamic_window_gate_open": gate_open,
                "expectation_bucket": str(row.get("expectation_bucket") or "unknown"),
                "risk_action_proposal": action,
                "execution_gate": "readonly_advisory_dynamic_window",
                "evidence_grade": evidence,
                "source_quality_score": float(row.get("source_quality_score", 0.0) or 0.0),
                "enforceable_for_dashboard": enforceable,
                "risk_flags": list(row.get("risk_flags") or []),
            }
        )
    return events


def _clamp(text: str, max_len: int) -> str:
    s = (text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _extract_json_object(text: str) -> dict:
    s = (text or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        pass
    l = s.find("{")
    r = s.rfind("}")
    if l >= 0 and r > l:
        try:
            return json.loads(s[l : r + 1])
        except Exception:
            return {}
    return {}


def _ollama_extract(item: dict, model: str, timeout: int = 60) -> dict:
    title = item.get("title", "")
    body = item.get("summary") or item.get("key_fact") or ""
    prompt = (
        "你是金融新闻结构化抽取器。"
        "只返回JSON对象，不要markdown，不要解释。"
        "字段:source_confidence(high|medium|low),impact_horizon(T0|T1|T2),"
        "risk_flags(字符串数组),cross_market_map(字符串),market_impact(字符串),"
        "attention_score(0-5整数),attention_type(narrative|event|policy|security|market_microstructure)。"
        "新闻标题:" + str(title) + "。新闻内容:" + str(body)
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    req = Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    raw = data.get("response", "")
    out = _extract_json_object(raw)
    if not isinstance(out, dict):
        return {}
    return out


def _normalize_risk_flags(flags: list) -> list:
    allowed = [
        "数据不可复核",
        "单源爆料",
        "单源未确认",
        "标题正文不一致",
        "无数据支撑",
        "高关注但低可证实",
        "政策未落地",
        "正文缺失，仅标题级信息",
        "主备源不可用",
        "预期差数据不足",
        "预期差使用显式数值",
        "预期差使用隐含预期",
        "预期差使用市场隐含预期",
        "来源质量退化",
        "证据等级不足",
        "超出动态窗口",
    ]
    out = []
    for f in flags:
        s = str(f).strip()
        if not s:
            continue
        if s in allowed:
            out.append(s)
            continue
        if "单源" in s:
            out.append("单源爆料")
        elif "不可复核" in s:
            out.append("数据不可复核")
        elif "标题" in s and "正文" in s:
            out.append("标题正文不一致")
        elif "无数据" in s:
            out.append("无数据支撑")
        elif "低可证实" in s:
            out.append("高关注但低可证实")
        elif "政策" in s and ("未落地" in s or "不确定" in s):
            out.append("政策未落地")
        elif "来源" in s and "质量" in s:
            out.append("来源质量退化")
        elif "证据" in s and ("不足" in s or "弱" in s):
            out.append("证据等级不足")
        elif "单源" in s and ("确认" in s or "未确认" in s):
            out.append("单源未确认")
        elif "隐含" in s and "预期" in s:
            out.append("预期差使用隐含预期")
        elif "显式" in s and "预期差" in s:
            out.append("预期差使用显式数值")
        elif "窗口" in s and ("超出" in s or "失效" in s):
            out.append("超出动态窗口")
    dedup = []
    for f in out:
        if f not in dedup:
            dedup.append(f)
    return dedup[:6]


def _event_window_range(impact_horizon: str) -> str:
    mapping = {
        "T0": "[0,+4h]",
        "T1": "[-6h,+6h]",
        "T2": "[-24h,+24h]",
        "T3": "[-48h,+48h]",
    }
    return mapping.get(str(impact_horizon or "").strip(), "[-24h,+24h]")


def _market_state_bucket(market_snapshot: dict) -> str:
    try:
        btc_change = float(market_snapshot.get("crypto", {}).get("btc", {}).get("change_24h", 0.0) or 0.0)
    except Exception:
        btc_change = 0.0
    try:
        nasdaq_change = float(market_snapshot.get("traditional", {}).get("nasdaq", {}).get("change_24h", 0.0) or 0.0)
    except Exception:
        nasdaq_change = 0.0
    try:
        vix = float(market_snapshot.get("traditional", {}).get("vix", {}).get("value", 0.0) or 0.0)
    except Exception:
        vix = 0.0
    high_vol_vix = float(MARKET_STATE_THRESHOLDS.get("high_vol_vix", 28.0) or 28.0)
    risk_off_vix = float(MARKET_STATE_THRESHOLDS.get("risk_off_vix", 22.0) or 22.0)
    risk_on_vix_max = float(MARKET_STATE_THRESHOLDS.get("risk_on_vix_max", 20.0) or 20.0)
    risk_on_btc_change_min = float(MARKET_STATE_THRESHOLDS.get("risk_on_btc_change_min", 2.0) or 2.0)
    risk_off_nasdaq_change_max = float(MARKET_STATE_THRESHOLDS.get("risk_off_nasdaq_change_max", 0.0) or 0.0)
    risk_on_nasdaq_change_min = float(MARKET_STATE_THRESHOLDS.get("risk_on_nasdaq_change_min", 0.0) or 0.0)
    if vix >= high_vol_vix:
        return "high_vol"
    if vix >= risk_off_vix and nasdaq_change <= risk_off_nasdaq_change_max:
        return "risk_off"
    if btc_change >= risk_on_btc_change_min and nasdaq_change >= risk_on_nasdaq_change_min and vix <= risk_on_vix_max:
        return "risk_on"
    return "neutral"


def _load_btc_daily_prices() -> dict:
    try:
        with open(BTC_DAILY_PRICES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_json_schema(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


ANCHOR_REGISTRY_SCHEMA = _load_json_schema(ANCHOR_SCHEMA_PATH)
DELTA_REGISTRY_SCHEMA = _load_json_schema(DELTA_SCHEMA_PATH)


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except Exception:
        return []
    return rows


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _check_type(value, t: str) -> bool:
    if t == "string":
        return isinstance(value, str)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    return True


def _validate_simple_schema(payload: dict, schema: dict, payload_name: str) -> list[str]:
    if not schema:
        return []
    errs = []
    if not isinstance(payload, dict):
        return [f"{payload_name} 必须为对象"]
    required = schema.get("required") or []
    for key in required:
        if key not in payload:
            errs.append(f"{payload_name}.{key} 缺失")
    properties = schema.get("properties") or {}
    for key, rule in properties.items():
        if key not in payload:
            continue
        value = payload.get(key)
        t = str((rule or {}).get("type") or "").strip()
        if t and not _check_type(value, t):
            errs.append(f"{payload_name}.{key} 类型错误，应为 {t}")
            continue
        enum = (rule or {}).get("enum") or []
        if enum and value not in enum:
            errs.append(f"{payload_name}.{key} 枚举值非法")
        if t in {"integer", "number"} and isinstance((rule or {}).get("minimum"), (int, float)):
            if float(value) < float((rule or {}).get("minimum")):
                errs.append(f"{payload_name}.{key} 小于最小值")
        if t == "array":
            item_rule = (rule or {}).get("items") or {}
            item_type = str(item_rule.get("type") or "").strip()
            if item_type:
                for idx, item in enumerate(value):
                    if not _check_type(item, item_type):
                        errs.append(f"{payload_name}.{key}[{idx}] 类型错误，应为 {item_type}")
    return errs


def _validate_anchor_row(row: dict) -> list[str]:
    if ANCHOR_REGISTRY_SCHEMA:
        return _validate_simple_schema(row, ANCHOR_REGISTRY_SCHEMA, "anchor_registry")
    errs = []
    if not _is_non_empty_str(row.get("anchor_id")):
        errs.append("anchor_registry.anchor_id 缺失")
    if not _is_non_empty_str(row.get("anchor_date")):
        errs.append("anchor_registry.anchor_date 缺失")
    if not isinstance(row.get("params"), dict):
        errs.append("anchor_registry.params 缺失")
    if not isinstance(row.get("event_map"), dict):
        errs.append("anchor_registry.event_map 缺失")
    return errs


def _validate_delta_row(row: dict) -> list[str]:
    if DELTA_REGISTRY_SCHEMA:
        return _validate_simple_schema(row, DELTA_REGISTRY_SCHEMA, "delta_registry")
    errs = []
    if not _is_non_empty_str(row.get("update_id")):
        errs.append("delta_registry.update_id 缺失")
    if not _is_non_empty_str(row.get("anchor_id")):
        errs.append("delta_registry.anchor_id 缺失")
    if not isinstance(row.get("changes"), dict):
        errs.append("delta_registry.changes 缺失")
    return errs


def _normalize_anchor_date(anchor_date: str, now: datetime) -> str:
    raw = str(anchor_date or "").strip()
    if not raw:
        return now.strftime("%Y-%m-%d")
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return now.strftime("%Y-%m-%d")


def _session_windows() -> dict:
    windows = (ANCHOR_POLICY or {}).get("session_windows_utc") or {}
    if not isinstance(windows, dict):
        return dict(DEFAULT_ANCHOR_POLICY["session_windows_utc"])
    out = {}
    for k, v in windows.items():
        if not isinstance(v, dict):
            continue
        try:
            sh = int(v.get("start_hour", 0))
            eh = int(v.get("end_hour", 23))
        except Exception:
            continue
        sh = max(0, min(23, sh))
        eh = max(0, min(23, eh))
        out[str(k).strip().lower()] = {"start_hour": sh, "end_hour": eh}
    if not out:
        return dict(DEFAULT_ANCHOR_POLICY["session_windows_utc"])
    return out


def _resolve_anchor_session(now: datetime, anchor_session: str) -> str:
    raw = str(anchor_session or "").strip().lower()
    if raw in {"apac", "eu", "us"}:
        return raw
    hour = int(now.hour)
    for s, cfg in _session_windows().items():
        sh = int(cfg.get("start_hour", 0))
        eh = int(cfg.get("end_hour", 23))
        if sh <= hour <= eh:
            return s
    return "apac"


def _resolve_anchor_key(anchor_date: str, session: str) -> str:
    enabled = bool((ANCHOR_POLICY or {}).get("multi_anchor_enabled", True))
    if not enabled:
        return str(anchor_date)
    return f"{anchor_date}.{str(session or 'apac').strip().lower()}"


def _latest_anchor(anchor_date: str, anchor_key: str = "") -> dict:
    rows = _read_jsonl(ANCHOR_REGISTRY_PATH)
    if str(anchor_key or "").strip():
        scoped = [x for x in rows if str(x.get("anchor_key") or "") == str(anchor_key)]
    else:
        scoped = [x for x in rows if str(x.get("anchor_date") or "") == str(anchor_date)]
    if scoped:
        return scoped[-1]
    return rows[-1] if rows else {}


def _current_param_snapshot(all_news: list) -> dict:
    total = len(all_news or [])
    if total <= 0:
        return {
            "sample_count": 0,
            "avg_signal_score": 0.0,
            "negative_ratio": 0.0,
            "high_risk_ratio": 0.0,
            "active_narrative_ratio": 0.0,
            "window_gate_open_ratio": 0.0,
            "expectation_unknown_ratio_macro": 0.0,
        }
    signal_scores = []
    negative = 0
    high_risk = 0
    active = 0
    window_open = 0
    macro_total = 0
    macro_unknown = 0
    for row in all_news:
        try:
            score = float(row.get("sentiment_score", 0.0) or 0.0)
        except Exception:
            score = 0.0
        signal_scores.append(score)
        if score < 0:
            negative += 1
        if str(row.get("risk_action_proposal") or "") in {"reduce", "hedge", "stop_loss"}:
            high_risk += 1
        if str(row.get("narrative_status") or "") == "active":
            active += 1
        if bool(row.get("dynamic_window_gate_open", True)):
            window_open += 1
        if is_macro_topic(row.get("topic")):
            macro_total += 1
            if str(row.get("expectation_bucket") or "unknown") == "unknown":
                macro_unknown += 1
    avg_signal = sum(signal_scores) / len(signal_scores) if signal_scores else 0.0
    return {
        "sample_count": total,
        "avg_signal_score": round(avg_signal, 6),
        "negative_ratio": round(negative / total, 6),
        "high_risk_ratio": round(high_risk / total, 6),
        "active_narrative_ratio": round(active / total, 6),
        "window_gate_open_ratio": round(window_open / total, 6),
        "expectation_unknown_ratio_macro": round((macro_unknown / macro_total) if macro_total else 0.0, 6),
    }


def _event_map_snapshot(all_news: list) -> dict:
    out = {}
    for row in all_news or []:
        key = _cluster_key(row)
        if not key:
            continue
        out[key] = {
            "title": str(row.get("title") or ""),
            "event_type": str(row.get("event_type") or "unknown"),
            "risk_action_proposal": str(row.get("risk_action_proposal") or "hold"),
            "source_confidence": str(row.get("source_confidence") or "medium"),
            "narrative_status": str(row.get("narrative_status") or "archive"),
            "community_effective_score": float(row.get("community_effective_score", 0.0) or 0.0),
        }
    return out


def _resolve_update_mode(update_mode: str, anchor_date: str, anchor_key: str, force_anchor: bool) -> str:
    mode = str(update_mode or "auto").strip().lower()
    if force_anchor:
        return "anchor"
    if mode in {"anchor", "delta", "reset"}:
        return mode
    today_anchor = _latest_anchor(anchor_date, anchor_key)
    return "anchor" if not today_anchor else "delta"


def _ema_alpha_map() -> dict:
    cfg = (ANCHOR_POLICY or {}).get("ema_alpha") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    out = {}
    for k, v in cfg.items():
        try:
            x = float(v)
        except Exception:
            continue
        out[str(k)] = max(0.01, min(0.99, x))
    if "default" not in out:
        out["default"] = 0.35
    return out


def _ema_update(prev_params: dict, current_params: dict) -> dict:
    alphas = _ema_alpha_map()
    out = {}
    for k, v in (current_params or {}).items():
        try:
            curr = float(v)
        except Exception:
            out[str(k)] = v
            continue
        prev = float((prev_params or {}).get(k, curr) or curr)
        alpha = float(alphas.get(k, alphas.get("default", 0.35)))
        out[str(k)] = round(alpha * curr + (1.0 - alpha) * prev, 6)
    return out


def _adaptive_drift_thresholds() -> dict:
    cfg = (ANCHOR_POLICY or {}).get("adaptive_threshold") or {}
    base_score_shift = float(cfg.get("base_score_shift", 0.2) or 0.2)
    base_offset_score = float(cfg.get("base_offset_score", 0.35) or 0.35)
    min_mult = float(cfg.get("min_multiplier", 0.7) or 0.7)
    max_mult = float(cfg.get("max_multiplier", 1.6) or 1.6)
    if not bool(cfg.get("enabled", True)):
        return {
            "multiplier": 1.0,
            "score_shift_threshold": base_score_shift,
            "offset_score_threshold": base_offset_score,
            "source_file": "",
        }
    files = cfg.get("backtest_files") or []
    if not isinstance(files, list):
        files = []
    source_file = ""
    sharpe = 0.0
    drawdown = 0.0
    for name in files:
        p = BASE_DIR / "historical_data" / str(name)
        if not p.exists():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            res = obj.get("results") if isinstance(obj, dict) else {}
            sharpe = float((res or {}).get("sharpe_ratio", 0.0) or 0.0)
            drawdown = float((res or {}).get("max_drawdown", 0.0) or 0.0)
            source_file = str(p)
            break
        except Exception:
            continue
    multiplier = 1.0 + max(0.0, drawdown) * 0.25 - max(-2.0, min(2.0, sharpe)) * 0.05
    multiplier = max(min_mult, min(max_mult, multiplier))
    return {
        "multiplier": round(multiplier, 6),
        "score_shift_threshold": round(base_score_shift * multiplier, 6),
        "offset_score_threshold": round(base_offset_score * multiplier, 6),
        "source_file": source_file,
    }


def _build_anchor_row(
    now: datetime,
    file_ts: str,
    anchor_date: str,
    anchor_key: str,
    anchor_session: str,
    hours: int,
    market_trend_state: str,
    market_trend_meta: dict,
    signal_analysis: SignalAnalysis,
    all_news: list,
) -> dict:
    event_map = _event_map_snapshot(all_news)
    top_rows = sorted(all_news or [], key=lambda x: float(x.get("community_effective_score", 0.0) or 0.0), reverse=True)[:12]
    top_narratives = []
    for row in top_rows:
        top_narratives.append(
            {
                "title": str(row.get("title") or ""),
                "community_effective_score": float(row.get("community_effective_score", 0.0) or 0.0),
                "risk_action_proposal": str(row.get("risk_action_proposal") or "hold"),
                "event_type": str(row.get("event_type") or "unknown"),
            }
        )
    anchor_id = f"ANCHOR-{anchor_key.replace('-', '').replace('.', '-')}-{file_ts.split('_')[-1]}"
    params = _current_param_snapshot(all_news)
    return {
        "version": ANCHOR_DELTA_VERSION,
        "anchor_id": anchor_id,
        "anchor_date": anchor_date,
        "anchor_key": anchor_key,
        "anchor_session": anchor_session,
        "generated_at": now.isoformat(),
        "file_ts": file_ts,
        "hours": int(hours),
        "anchor_source": "wallstreetcn_breakfast",
        "market_trend_state": str(market_trend_state),
        "market_trend_meta": dict(market_trend_meta or {}),
        "params": params,
        "params_ema": dict(params),
        "adaptive_thresholds": _adaptive_drift_thresholds(),
        "signal_snapshot": {
            "composite_signal": float(signal_analysis.composite_signal),
            "macro_signal": float(signal_analysis.macro_signal),
            "industry_signal": float(signal_analysis.industry_signal),
            "company_signal": float(signal_analysis.company_signal),
            "recommendation": str(signal_analysis.recommendation),
            "position_suggestion": float(signal_analysis.position_suggestion),
        },
        "event_count": len(event_map),
        "event_map": event_map,
        "top_narratives": top_narratives,
    }


def _build_delta_row(
    now: datetime,
    file_ts: str,
    anchor_row: dict,
    hours: int,
    anchor_date: str,
    anchor_key: str,
    anchor_session: str,
    market_trend_state: str,
    signal_analysis: SignalAnalysis,
    all_news: list,
) -> dict:
    current_map = _event_map_snapshot(all_news)
    anchor_map = dict(anchor_row.get("event_map") or {})
    anchor_keys = set(anchor_map.keys())
    current_keys = set(current_map.keys())
    added_keys = sorted(list(current_keys - anchor_keys))
    resolved_keys = sorted(list(anchor_keys - current_keys))
    retained_keys = sorted(list(current_keys & anchor_keys))
    score_shifts = []
    action_changes = []
    adaptive = _adaptive_drift_thresholds()
    score_shift_threshold = float(adaptive.get("score_shift_threshold", 0.2) or 0.2)
    for key in retained_keys:
        old = anchor_map.get(key) or {}
        new = current_map.get(key) or {}
        old_score = float(old.get("community_effective_score", 0.0) or 0.0)
        new_score = float(new.get("community_effective_score", 0.0) or 0.0)
        if abs(new_score - old_score) >= score_shift_threshold:
            score_shifts.append(
                {
                    "title": str(new.get("title") or old.get("title") or ""),
                    "from": round(old_score, 4),
                    "to": round(new_score, 4),
                }
            )
        old_action = str(old.get("risk_action_proposal") or "hold")
        new_action = str(new.get("risk_action_proposal") or "hold")
        if old_action != new_action:
            action_changes.append(
                {
                    "title": str(new.get("title") or old.get("title") or ""),
                    "from": old_action,
                    "to": new_action,
                }
            )
    current_params = _current_param_snapshot(all_news)
    anchor_params = dict(anchor_row.get("params") or {})
    prev_ema = dict(anchor_row.get("params_ema") or anchor_params)
    current_ema = _ema_update(prev_ema, current_params)
    param_drift = {}
    for key in [
        "avg_signal_score",
        "negative_ratio",
        "high_risk_ratio",
        "active_narrative_ratio",
        "window_gate_open_ratio",
        "expectation_unknown_ratio_macro",
    ]:
        old_v = float(anchor_params.get(key, 0.0) or 0.0)
        new_v = float(current_params.get(key, 0.0) or 0.0)
        param_drift[key] = {
            "anchor": round(old_v, 6),
            "current": round(new_v, 6),
            "delta": round(new_v - old_v, 6),
        }
    row_anchor_date = str(anchor_row.get("anchor_date") or anchor_date or "")
    row_anchor_key = str(anchor_row.get("anchor_key") or anchor_key or "")
    row_anchor_session = str(anchor_row.get("anchor_session") or anchor_session or "apac").strip().lower()
    if row_anchor_session not in {"apac", "eu", "us"}:
        row_anchor_session = str(anchor_session or "apac").strip().lower()
    if row_anchor_session not in {"apac", "eu", "us"}:
        row_anchor_session = "apac"
    return {
        "version": ANCHOR_DELTA_VERSION,
        "update_id": f"DELTA-{file_ts}",
        "anchor_id": str(anchor_row.get("anchor_id") or ""),
        "anchor_date": row_anchor_date,
        "anchor_key": row_anchor_key,
        "anchor_session": row_anchor_session,
        "generated_at": now.isoformat(),
        "file_ts": file_ts,
        "hours": int(hours),
        "market_trend_state": str(market_trend_state),
        "signal_snapshot": {
            "composite_signal": float(signal_analysis.composite_signal),
            "macro_signal": float(signal_analysis.macro_signal),
            "industry_signal": float(signal_analysis.industry_signal),
            "company_signal": float(signal_analysis.company_signal),
            "recommendation": str(signal_analysis.recommendation),
            "position_suggestion": float(signal_analysis.position_suggestion),
        },
        "changes": {
            "added_event_count": len(added_keys),
            "resolved_event_count": len(resolved_keys),
            "retained_event_count": len(retained_keys),
            "added_events": [str((current_map.get(k) or {}).get("title") or "") for k in added_keys[:12]],
            "resolved_events": [str((anchor_map.get(k) or {}).get("title") or "") for k in resolved_keys[:12]],
            "score_shifts": score_shifts[:12],
            "action_changes": action_changes[:12],
        },
        "adaptive_thresholds": adaptive,
        "params_ema": current_ema,
        "param_drift": param_drift,
    }


def _apply_event_offset_chain(items: list, anchor_row: dict) -> tuple[list, list]:
    if not anchor_row:
        return [dict(x) for x in (items or [])], []
    anchor_map = dict(anchor_row.get("event_map") or {})
    out = []
    offset_events = []
    adaptive = _adaptive_drift_thresholds()
    offset_score_threshold = float(adaptive.get("offset_score_threshold", 0.35) or 0.35)
    for row in items or []:
        merged = dict(row)
        key = _cluster_key(merged)
        anchor_event = anchor_map.get(key) or {}
        if not anchor_event:
            out.append(merged)
            continue
        prev_score = float(anchor_event.get("community_effective_score", 0.0) or 0.0)
        curr_score = float(merged.get("community_effective_score", 0.0) or 0.0)
        prev_action = str(anchor_event.get("risk_action_proposal") or "hold")
        curr_action = str(merged.get("risk_action_proposal") or "hold")
        opposite = (
            (prev_action == "increase" and curr_action in {"reduce", "stop_loss", "hedge"})
            or (prev_action in {"reduce", "stop_loss"} and curr_action in {"increase", "take_profit"})
            or (prev_score >= offset_score_threshold and curr_score <= -offset_score_threshold)
            or (prev_score <= -offset_score_threshold and curr_score >= offset_score_threshold)
        )
        if not opposite:
            out.append(merged)
            continue
        adjusted = curr_score * 0.5
        merged["community_effective_score"] = round(adjusted, 4)
        merged["narrative_status"] = _narrative_status(merged["community_effective_score"])
        flags = _normalize_risk_flags(merged.get("risk_flags") or [])
        if "反证事件冲销" not in flags:
            flags.append("反证事件冲销")
        merged["risk_flags"] = flags
        if curr_action in {"increase", "take_profit"}:
            merged["risk_action_proposal"] = "hold"
        offset_events.append(
            {
                "title": str(merged.get("title") or ""),
                "cluster_key": key,
                "anchor_action": prev_action,
                "current_action": curr_action,
                "anchor_score": round(prev_score, 4),
                "current_score_before": round(curr_score, 4),
                "current_score_after": round(float(merged.get("community_effective_score", 0.0) or 0.0), 4),
            }
        )
        out.append(merged)
    return out, offset_events


def _build_anchor_delta_view(
    now: datetime,
    mode: str,
    anchor_row: dict,
    delta_row: dict,
    market_trend_state: str,
    signal_analysis: SignalAnalysis,
    offset_events: list,
) -> dict:
    base = {
        "version": ANCHOR_DELTA_VERSION,
        "generated_at": now.isoformat(),
        "mode": str(mode or "auto"),
        "market_trend_state": str(market_trend_state or ""),
        "anchor": {
            "anchor_id": str((anchor_row or {}).get("anchor_id") or ""),
            "anchor_date": str((anchor_row or {}).get("anchor_date") or ""),
            "params": dict((anchor_row or {}).get("params") or {}),
            "signal_snapshot": dict((anchor_row or {}).get("signal_snapshot") or {}),
        },
        "delta": dict(delta_row or {}),
        "offset_events": list(offset_events or []),
        "signal_now": {
            "composite_signal": float(signal_analysis.composite_signal),
            "macro_signal": float(signal_analysis.macro_signal),
            "industry_signal": float(signal_analysis.industry_signal),
            "company_signal": float(signal_analysis.company_signal),
            "recommendation": str(signal_analysis.recommendation),
            "position_suggestion": float(signal_analysis.position_suggestion),
        },
    }
    return base


def _compute_market_trend_state(market_snapshot: dict, now: datetime) -> tuple[str, dict]:
    data = _load_btc_daily_prices()
    closes: list[float] = []
    dates = sorted([d for d in data.keys() if isinstance(d, str)])
    for d in dates[-40:]:
        row = data.get(d) or {}
        try:
            closes.append(float(row.get("close")))
        except Exception:
            continue
    try:
        current_price = float(market_snapshot.get("crypto", {}).get("btc", {}).get("price_usd", 0.0) or 0.0)
    except Exception:
        current_price = 0.0
    if current_price > 0:
        closes.append(current_price)
    lookback = 20
    band = 0.05
    if len(closes) < 5:
        return "unknown", {
            "asset": "BTC",
            "lookback_days": lookback,
            "band": band,
            "price": current_price,
            "ma20": 0.0,
            "volatility_20d": 0.0,
            "price_vs_ma": 0.0,
            "source": str(BTC_DAILY_PRICES_PATH),
            "asof": now.isoformat(),
        }
    window = closes[-lookback:] if len(closes) >= lookback else closes
    ma20 = sum(window) / len(window) if window else 0.0
    volatility = 0.0
    if len(window) > 1:
        returns = []
        for i in range(1, len(window)):
            p0 = window[i - 1]
            p1 = window[i]
            if p0 and p1:
                returns.append((p1 - p0) / p0)
        if len(returns) > 1:
            try:
                volatility = float(__import__("statistics").stdev(returns))
            except Exception:
                volatility = 0.0
    price_vs_ma = (current_price - ma20) / ma20 if ma20 else 0.0
    if price_vs_ma > band:
        state = "bull"
    elif price_vs_ma < -band:
        state = "bear"
    else:
        state = "sideways"
    return state, {
        "asset": "BTC",
        "lookback_days": lookback,
        "band": band,
        "price": current_price,
        "ma20": round(ma20, 6),
        "volatility_20d": round(volatility, 6),
        "price_vs_ma": round(price_vs_ma, 6),
        "source": str(BTC_DAILY_PRICES_PATH),
        "asof": now.isoformat(),
    }


def _asset_bucket(item: dict) -> str:
    event_type = str(item.get("event_type") or "").strip()
    topic = str(item.get("topic") or "").strip()
    category = str(item.get("category") or "").strip()
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or item.get("key_fact") or "")
    risk_flags = " ".join(str(x) for x in (item.get("risk_flags") or []))
    full_text = f"{title} {summary} {risk_flags}".lower()
    if any(k in full_text for k in SECURITY_DEFENSIVE_KEYWORDS):
        return "security_defensive"
    for bucket, event_types in ASSET_BUCKET_EVENT_TYPES.items():
        if event_type in event_types:
            return bucket
    if topic in {"fed", "us_data", "geopolitics", "us_policy", "market_analysis"}:
        return "macro_policy"
    if category in {"onchain_data", "kols_view", "project_update"}:
        return "crypto_beta"
    return "crypto_beta"


def _dynamic_window_policy(event_type: str, asset_bucket: str, market_state: str) -> dict:
    row = WINDOW_POLICY_MAP.get(str(event_type or "").strip())
    if not isinstance(row, dict):
        return {}
    conf = float(row.get("confidence", 0.0) or 0.0)
    if conf < 0.2:
        return {}
    base_window_range = str(row.get("recommended_window_range") or "[-24h,+24h]")
    window_range = (
        MARKET_STATE_WINDOW_ADJUSTMENT_RUNTIME.get(market_state, {}).get(asset_bucket)
        or base_window_range
    )
    horizon_days = int(row.get("recommended_horizon_days", 2) or 2)
    return {
        "window_range": window_range,
        "horizon_days": max(1, horizon_days),
        "confidence": conf,
        "market_state": market_state,
        "asset_bucket": asset_bucket,
        "base_window_range": base_window_range,
    }


def _event_type(item: dict) -> str:
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or item.get("key_fact") or "")
    category = str(item.get("category") or "").strip()
    topic = str(item.get("topic") or "").strip()
    return map_event_type(topic=topic, category=category, title=title, body=summary)


def _expectation_bucket(item: dict) -> str:
    topic = str(item.get("topic") or "").strip()
    actual = item.get("actual_value")
    expected = item.get("expected_value")
    surprise = item.get("surprise")
    implied = item.get("implied_surprise_score")
    if actual is None or expected is None:
        if surprise is None:
            if implied is None:
                return "unknown"
            try:
                surprise = float(implied)
            except Exception:
                return "unknown"
        try:
            surprise = float(surprise)
        except Exception:
            return "unknown"
    else:
        try:
            surprise = float(actual) - float(expected)
        except Exception:
            return "unknown"

    if topic in {"fed", "us_data"}:
        if surprise > 0:
            return "偏鹰"
        if surprise < 0:
            return "偏鸽"
        return "符合"
    if topic in {"geopolitics", "us_policy", "market_analysis"}:
        if surprise > 0:
            return "利多"
        if surprise < 0:
            return "利空"
        return "中性"
    return "unknown"


def _risk_action_proposal(item: dict) -> str:
    event_type = str(item.get("event_type") or "")
    window = str(item.get("event_window_range") or "")
    conf = str(item.get("source_confidence") or "medium").strip()
    s = float(item.get("sentiment_score", 0.0) or 0.0)
    risk_flags = item.get("risk_flags") or []
    risk_flag_count = len(risk_flags) if isinstance(risk_flags, list) else 0

    conf_w = {"high": 0.9, "medium": 0.6, "low": 0.3}.get(conf, 0.6)
    score = s * conf_w
    if risk_flag_count >= 2:
        score *= 0.7

    high_grade = is_high_grade_event(event_type=event_type, event_window_range=window)
    if high_grade:
        if score <= -0.4:
            return "stop_loss"
        if score <= -0.1:
            return "reduce"
        if risk_flag_count > 0:
            return "hedge"
        return "hold"

    if score <= -0.6 and conf == "high":
        return "stop_loss"
    if score <= -0.3:
        return "reduce"
    if score >= 0.3 and conf == "high":
        return "increase"
    return "hold"


def _cluster_key(item: dict) -> str:
    title = str(item.get("title") or "").strip().lower()
    return title[:28] if title else "unknown"


def _source_key(item: dict) -> str:
    source = str(item.get("source") or "").strip().lower()
    if source:
        return source
    url = str(item.get("source_url") or "").strip()
    if not url:
        return "unknown"
    try:
        return (urlparse(url).netloc or "unknown").lower()
    except Exception:
        return "unknown"


def _hours_since_now(item: dict, now: datetime) -> float:
    ts = item.get("published_at") or item.get("fetched_at")
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return 0.0
    if dt.tzinfo is not None and now.tzinfo is None:
        dt = dt.replace(tzinfo=None)
    delta_hours = (now - dt).total_seconds() / 3600.0
    return max(0.0, delta_hours)


def _decay_half_life_hours(attention_type: str) -> int:
    if attention_type == "market_microstructure":
        return 6
    if attention_type in {"event", "policy", "security"}:
        return 24
    return 72


def _decay_factor(hours_since: float, half_life_hours: int) -> float:
    if half_life_hours <= 0:
        return 1.0
    value = math.exp(-math.log(2.0) * float(hours_since) / float(half_life_hours))
    return max(0.0, min(1.0, value))


def _narrative_status(community_effective_score: float) -> str:
    if community_effective_score >= 0.5:
        return "active"
    if community_effective_score >= 0.2:
        return "cooling"
    return "archive"


def _apply_doc_contract_fields(items: list, market_snapshot: dict | None = None) -> list:
    out = []
    now = datetime.now()
    local_market_snapshot = market_snapshot or {}
    market_state = _market_state_bucket(local_market_snapshot)
    cluster_mentions: dict[str, int] = {}
    cluster_sources: dict[str, set[str]] = {}
    for it in items or []:
        key = _cluster_key(it)
        mention_count = int(it.get("mention_count", 0) or 0)
        cluster_mentions[key] = max(cluster_mentions.get(key, 0) + 1, mention_count)
        if key not in cluster_sources:
            cluster_sources[key] = set()
        cluster_sources[key].add(_source_key(it))
    for it in items or []:
        merged = dict(it)
        merged["summary_2lines"] = merged.get("summary_2lines") or _clamp(
            str(merged.get("summary") or merged.get("key_fact") or "正文缺失，仅标题级信息"),
            140,
        )
        merged["fact_text"] = merged.get("fact_text") or str(merged.get("key_fact") or merged.get("summary_2lines") or "")
        merged["analysis_text"] = merged.get("analysis_text") or str(
            merged.get("possible_market_impact") or merged.get("market_impact") or merged.get("cross_market_map") or ""
        )
        merged["confidence"] = merged.get("confidence") or merged.get("source_confidence") or "medium"
        merged["source_confidence"] = merged.get("source_confidence") or merged["confidence"]
        merged["possible_market_impact"] = (
            merged.get("possible_market_impact")
            or merged.get("market_impact")
            or merged.get("cross_market_map")
            or ""
        )
        merged["market_impact"] = merged.get("market_impact") or merged["possible_market_impact"]
        merged["attention_score"] = int(merged.get("attention_score", 0) or 0)
        merged["attention_score"] = max(0, min(5, merged["attention_score"]))
        merged["attention_type"] = _normalize_attention_type(str(merged.get("attention_type") or "event"))
        merged["risk_flags"] = _normalize_risk_flags(merged.get("risk_flags") or [])
        merged["event_type"] = _event_type(merged)
        default_window = _event_window_range(merged.get("impact_horizon", "T1"))
        asset_bucket = _asset_bucket(merged)
        dynamic_policy = _dynamic_window_policy(merged["event_type"], asset_bucket, market_state)
        if dynamic_policy:
            merged["event_window_range"] = dynamic_policy["window_range"]
            merged["window_policy_source"] = "calibrated_v03"
            merged["window_policy_confidence"] = round(float(dynamic_policy["confidence"]), 4)
            merged["window_policy_horizon_days"] = int(dynamic_policy["horizon_days"])
            merged["window_policy_market_state"] = str(dynamic_policy.get("market_state") or market_state)
            merged["window_policy_asset_bucket"] = str(dynamic_policy.get("asset_bucket") or asset_bucket)
            merged["window_policy_base_range"] = str(dynamic_policy.get("base_window_range") or default_window)
        else:
            merged["event_window_range"] = default_window
            merged["window_policy_source"] = "default_impact_horizon"
            merged["window_policy_confidence"] = 0.0
            merged["window_policy_horizon_days"] = max(1, int(_window_range_to_max_age_hours(default_window) / 24))
            merged["window_policy_market_state"] = market_state
            merged["window_policy_asset_bucket"] = asset_bucket
            merged["window_policy_base_range"] = default_window
        if not merged.get("expectation_source"):
            if isinstance(merged.get("expected_value"), (int, float)) and isinstance(merged.get("actual_value"), (int, float)):
                merged["expectation_source"] = "explicit_numeric"
            elif merged.get("implied_surprise_score") is not None:
                merged["expectation_source"] = "implied_text"
            else:
                merged["expectation_source"] = "none"
        merged["expectation_bucket"] = merged.get("expectation_bucket") or _expectation_bucket(merged)
        if merged["expectation_bucket"] != "unknown":
            if str(merged.get("expectation_source")) == "explicit_numeric":
                if "预期差使用显式数值" not in merged["risk_flags"]:
                    merged["risk_flags"].append("预期差使用显式数值")
            elif str(merged.get("expectation_source")) == "implied_market":
                if "预期差使用市场隐含预期" not in merged["risk_flags"]:
                    merged["risk_flags"].append("预期差使用市场隐含预期")
            elif merged.get("implied_surprise_score") is not None:
                if "预期差使用隐含预期" not in merged["risk_flags"]:
                    merged["risk_flags"].append("预期差使用隐含预期")
        if merged["expectation_bucket"] == "unknown" and is_macro_topic(merged.get("topic")):
            if "预期差数据不足" not in merged["risk_flags"]:
                merged["risk_flags"].append("预期差数据不足")
            if merged["source_confidence"] == "high":
                merged["source_confidence"] = "medium"
            elif merged["source_confidence"] == "medium":
                merged["source_confidence"] = "low"
            merged["confidence"] = merged["source_confidence"]
        merged["risk_action_proposal"] = merged.get("risk_action_proposal") or _risk_action_proposal(merged)
        cluster_key = _cluster_key(merged)
        mention_count = max(int(merged.get("mention_count", 0) or 0), cluster_mentions.get(cluster_key, 1))
        source_diversity = max(1, len(cluster_sources.get(cluster_key, {"unknown"})))
        attention_norm = float(merged["attention_score"]) / 5.0
        mention_norm = min(1.0, float(mention_count) / 5.0)
        source_diversity_norm = min(1.0, float(source_diversity) / 4.0)
        community_base_score = 0.5 * attention_norm + 0.3 * mention_norm + 0.2 * source_diversity_norm
        half_life_hours = _decay_half_life_hours(str(merged.get("attention_type") or "event"))
        hours_since = _hours_since_now(merged, now)
        merged["event_age_hours"] = round(hours_since, 4)
        max_age_hours = _window_range_to_max_age_hours(str(merged.get("event_window_range") or "[-24h,+24h]"))
        merged["dynamic_window_gate_open"] = bool(hours_since <= max_age_hours)
        if not merged["dynamic_window_gate_open"]:
            if "超出动态窗口" not in merged["risk_flags"]:
                merged["risk_flags"].append("超出动态窗口")
        decay_factor = _decay_factor(hours_since, half_life_hours)
        credibility_adj = {"high": 1.0, "medium": 0.7, "low": 0.4}.get(str(merged["source_confidence"]), 0.7)
        community_effective_score = community_base_score * decay_factor * credibility_adj
        merged["community_base_score"] = round(max(0.0, min(1.0, community_base_score)), 4)
        merged["decay_half_life_hours"] = int(half_life_hours)
        merged["decay_factor"] = round(decay_factor, 4)
        merged["community_effective_score"] = round(max(0.0, min(1.0, community_effective_score)), 4)
        merged["narrative_status"] = _narrative_status(merged["community_effective_score"])
        if is_macro_topic(merged.get("topic")):
            merged["key_fact"] = merged.get("key_fact") or merged["fact_text"]
        if merged.get("category") in {"onchain_data", "kols_view", "project_update"}:
            merged["summary"] = merged.get("summary") or merged["fact_text"]
        if not merged.get("published_at"):
            merged["published_at"] = merged.get("fetched_at")
        if not merged.get("fetched_at"):
            merged["fetched_at"] = datetime.now().isoformat()
        if int(merged.get("mention_count", 1) or 1) <= 1:
            if "单源未确认" not in merged["risk_flags"]:
                merged["risk_flags"].append("单源未确认")
        if not str(merged.get("analysis_text") or "").strip():
            gap_parts = []
            if "正文缺失，仅标题级信息" in merged["risk_flags"]:
                gap_parts.append("正文缺失")
            if not str(merged.get("cross_market_map") or "").strip():
                gap_parts.append("缺少跨市场传导路径")
            if str(merged.get("expectation_bucket") or "unknown") == "unknown" and is_macro_topic(merged.get("topic")):
                gap_parts.append("预期差不可计算")
            merged["analysis_text"] = (
                "不确定性说明：当前证据不足，暂不形成方向性结论；证据缺口："
                + ("；".join(gap_parts) if gap_parts else "缺少可复核证据")
            )
        out.append(merged)
    return out


def _format_brief_v1(
    crypto_news: list,
    macro_news: list,
    hours: int,
    file_ts: str,
) -> tuple[str, dict]:
    now = datetime.now()
    start = (now - timedelta(hours=hours)).isoformat()
    end = now.isoformat()

    def pick(items: list, predicate, limit: int) -> list:
        selected = [i for i in items if predicate(i)]
        return selected[:limit]

    all_news = (crypto_news or []) + (macro_news or [])
    missing_data: list[str] = []
    for item in all_news:
        if not item.get("source_url"):
            missing_data.append(f"missing_url: {item.get('title', '')}")
        if not (item.get("published_at") or item.get("fetched_at")):
            missing_data.append(f"missing_time: {item.get('title', '')}")
        flags = item.get("risk_flags") or []
        if isinstance(flags, list) and any("正文缺失" in str(f) for f in flags):
            missing_data.append(f"missing_body: {item.get('title', '')}")

    onchain = pick(crypto_news, lambda x: x.get("category") == "onchain_data", 5)
    kols = pick(crypto_news, lambda x: x.get("category") == "kols_view", 5)
    project = pick(crypto_news, lambda x: x.get("category") == "project_update", 5)
    macro = pick(macro_news, lambda x: x.get("topic") in {"fed", "us_data", "geopolitics", "us_policy", "market_analysis"}, 8)

    def line(item: dict, kind: str) -> str:
        title = item.get("title", "")
        url = item.get("source_url", "")
        fact = item.get("key_fact") or item.get("summary") or ""
        impact = item.get("possible_market_impact") or item.get("market_impact") or item.get("cross_market_map") or ""
        confidence = item.get("source_confidence") or item.get("confidence") or "medium"
        horizon = item.get("impact_horizon") or ""
        extra = f"可信度={confidence}, 时效={horizon}" if confidence or horizon else ""
        if kind == "kols":
            uncertainty = "；反方/不确定性：" + ("；".join(item.get("risk_flags", [])) if isinstance(item.get("risk_flags"), list) and item.get("risk_flags") else "unknown")
            return f"- [{title}]：观点：{fact[:120]}{uncertainty}；来源：{url}（{extra}）"
        if kind == "onchain":
            return f"- [{title}]：事实：{fact[:120]}；影响：{impact[:120]}；来源：{url}（{extra}）"
        if kind == "project":
            return f"- [{title}]：事件：{fact[:120]}；潜在影响：{impact[:120]}；来源：{url}（{extra}）"
        return f"- [{title}]：关键事实：{fact[:120]}；资产影响路径：{impact[:120]}；来源：{url}（{extra}）"

    cross_market: list[str] = []
    for item in (macro + onchain)[:6]:
        cmap = str(item.get("cross_market_map") or "").strip()
        if cmap:
            cross_market.append(cmap)
    cross_market = list(dict.fromkeys(cross_market))[:3]

    watchlist: list[str] = []
    for item in macro:
        if item.get("impact_horizon") == "T0":
            watchlist.append(item.get("title", ""))
    watchlist = [w for w in watchlist if w][:8]

    top_risks: list[str] = []
    for item in all_news:
        flags = item.get("risk_flags") or []
        if isinstance(flags, list):
            for f in flags:
                s = str(f).strip()
                if s:
                    top_risks.append(s)
    top_risks = list(dict.fromkeys(top_risks))[:12]

    md = f"""# 24h 市场简报（加密 + 宏观）

**生成时间**: {end}
**时间窗**: {start} ~ {end}
**数据源**: Odaily 星球日报、金色财经、BlockBeats、华尔街见闻
**文件命名**: brief_v2_{file_ts}.md

---

## 0) 时间窗与数据说明
- 时间窗：最近 {hours} 小时
- 数据源：Odaily 星球日报快讯、金色财经快讯、BlockBeats 快讯/文章、华尔街见闻早餐/宏观
- 缺失说明：{("；".join(missing_data[:8]) if missing_data else "无")}

## 1) 链上数据（3-5条）
{chr(10).join([line(i, "onchain") for i in onchain]) if onchain else "- 无"}

## 2) 大V观点（3-5条）
{chr(10).join([line(i, "kols") for i in kols]) if kols else "- 无"}

## 3) 项目动态（3-5条）
{chr(10).join([line(i, "project") for i in project]) if project else "- 无"}

## 4) 美国宏观政策与市场（5-8条）
{chr(10).join([line(i, "macro") for i in macro]) if macro else "- 无"}

## 5) 跨市场联动解读（3条）
{chr(10).join([f"- 结论{i+1}：{c}；证据链：cross_market_map；不确定性：以 risk_flags 为准" for i, c in enumerate(cross_market)]) if cross_market else "- 无"}

## 6) 明日观察清单
{chr(10).join([f"- {w}" for w in watchlist]) if watchlist else "- 事件/指标/时间点/影响资产：待补充"}

## 7) 风险提示
- 信息时效、样本偏差、非投资建议

```json
{json.dumps({"generated_at": end, "top_risks": top_risks, "watchlist": watchlist, "missing_data": missing_data}, ensure_ascii=False, indent=2)}
```
"""

    summary = {
        "generated_at": end,
        "time_window_hours": hours,
        "top_risks": top_risks,
        "watchlist": watchlist,
        "missing_data": missing_data,
    }
    return md, summary


def enrich_news_with_ollama(news_items: list, model: str, max_items: int = 12) -> list:
    enriched = []
    for idx, item in enumerate(news_items):
        merged = dict(item)
        if idx >= max_items:
            merged["llm_enriched_by"] = "skipped"
            enriched.append(merged)
            continue
        try:
            extracted = _ollama_extract(merged, model=model)
            if extracted.get("source_confidence") in {"high", "medium", "low"}:
                merged["source_confidence"] = extracted["source_confidence"]
            if extracted.get("impact_horizon") in {"T0", "T1", "T2"}:
                merged["impact_horizon"] = extracted["impact_horizon"]
            if isinstance(extracted.get("risk_flags"), list):
                merged["risk_flags"] = _normalize_risk_flags(extracted["risk_flags"])
            if isinstance(extracted.get("cross_market_map"), str):
                merged["cross_market_map"] = extracted["cross_market_map"][:220]
            if isinstance(extracted.get("market_impact"), str):
                merged["market_impact"] = extracted["market_impact"][:220]
            if isinstance(extracted.get("attention_type"), str):
                merged["attention_type"] = _normalize_attention_type(extracted["attention_type"])
            if isinstance(extracted.get("attention_score"), int):
                merged["attention_score"] = max(0, min(5, extracted["attention_score"]))
            merged["llm_enriched_by"] = "ollama"
            merged["llm_model"] = model
        except Exception:
            merged["llm_enriched_by"] = "none"
        enriched.append(merged)
    return enriched


def generate_enhanced_briefing(
    hours: int = 24,
    use_ollama: bool = False,
    ollama_model: str = "qwen2.5:7b-instruct",
    ledger_version: str = "auto",
    update_mode: str = "auto",
    anchor_date: str = "",
    anchor_session: str = "auto",
    force_anchor: bool = False,
) -> dict:
    """
    生成优化版简报

    返回：
    {
        "briefing_md": str,          # Markdown 简报
        "signal_analysis": dict,     # 信号分析
        "investment_recommendation": str,  # 投资建议
        "risk_assessment": list      # 风险评估
    }
    """
    now = datetime.now()
    file_ts = now.strftime("%Y%m%d_%H%M")
    resolved_anchor_date = _normalize_anchor_date(anchor_date, now)
    resolved_anchor_session = _resolve_anchor_session(now, anchor_session)
    resolved_anchor_key = _resolve_anchor_key(resolved_anchor_date, resolved_anchor_session)
    resolved_update_mode = _resolve_update_mode(update_mode, resolved_anchor_date, resolved_anchor_key, force_anchor)

    market_snapshot = get_market_snapshot()
    market_trend_state, market_trend_meta = _compute_market_trend_state(market_snapshot, now)
    try:
        crypto_block = market_snapshot.get("crypto")
        if not isinstance(crypto_block, dict):
            crypto_block = {}
            market_snapshot["crypto"] = crypto_block
        ma20_value = float((market_trend_meta or {}).get("ma20") or 0.0)
        if ma20_value > 0:
            crypto_block["btc_ma20"] = ma20_value
            crypto_block["ma20"] = ma20_value
    except Exception:
        pass
    base_dir = Path(__file__).parent.parent
    raw_dir = base_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    def _normalize_ledger_tag(tag: str) -> str:
        t = str(tag or "").strip().lower()
        mapping = {
            "v9.3": "9.3",
            "9.3": "9.3",
            "v9.5": "9.5",
            "9.5": "9.5",
            "v9.7 direct": "9.7_direct",
            "v9.7_direct": "9.7_direct",
            "v9.7": "9.7_direct",
            "9.7": "9.7_direct",
            "9.7_direct": "9.7_direct",
            "v9.8 onchain": "9.8_onchain",
            "v9.8_onchain": "9.8_onchain",
            "v9.8": "9.8_onchain",
            "9.8": "9.8_onchain",
            "9.8_onchain": "9.8_onchain",
        }
        return mapping.get(t, "")

    requested_ledger_version = str(ledger_version or "auto").strip() or "auto"
    resolved_ledger_version = requested_ledger_version
    resolved_overlay_ledger_version = ""
    if requested_ledger_version == "auto":
        try:
            with open(base_dir / "current_version.json", "r", encoding="utf-8") as f:
                cv = json.load(f)
        except Exception:
            cv = {}
        baseline = _normalize_ledger_tag(str((cv or {}).get("strategy_baseline") or ""))
        overlay = _normalize_ledger_tag(str((cv or {}).get("strategy_overlay_priority") or ""))
        if not baseline:
            baseline = "9.3"
        if not overlay:
            overlay = "9.8_onchain"
        resolved_ledger_version = baseline
        resolved_overlay_ledger_version = overlay
    else:
        normalized = _normalize_ledger_tag(requested_ledger_version)
        if normalized:
            resolved_ledger_version = normalized
    step_rows: list[dict] = []
    step_audit_path = raw_dir / f"step_audit_{file_ts}.json"
    crypto_news = []
    macro_news = []
    all_news = []
    source_profiles = {}
    outputs_dir = base_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    status = "succeeded"
    failure_reason = ""
    try:
        crypto_news = _run_step(
            "A_crypto_news_collect",
            lambda: fetch_odaily_newsflash(limit=30, hours=hours),
            step_rows,
            max_retries=1,
        )
        macro_news = _run_step(
            "B_macro_news_collect",
            lambda: fetch_wallstreetcn_breakfast(limit=30, hours=hours),
            step_rows,
            max_retries=1,
        )

        def _synthesis_step():
            local_crypto = list(crypto_news)
            local_macro = list(macro_news)
            if use_ollama:
                local_crypto = enrich_news_with_ollama(local_crypto, model=ollama_model)
                local_macro = enrich_news_with_ollama(local_macro, model=ollama_model)
            local_macro = _apply_market_implied_expectation(local_macro, market_snapshot)
            local_crypto = _apply_doc_contract_fields(local_crypto, market_snapshot)
            local_macro = _apply_doc_contract_fields(local_macro, market_snapshot)
            profiles = _source_quality_profiles(local_crypto + local_macro)
            local_crypto = _with_source_quality(local_crypto, profiles)
            local_macro = _with_source_quality(local_macro, profiles)
            merged = []
            for row in local_crypto + local_macro:
                row["evidence_grade"] = _evidence_grade(row)
                merged.append(_enforce_risk_guardrails(row))
            fixed_crypto = merged[: len(local_crypto)]
            fixed_macro = merged[len(local_crypto) :]
            payload = {
                "version": CONTRACT_VERSION,
                "generated_at": now.isoformat(),
                "time_window_hours": hours,
                "raw_crypto": fixed_crypto,
                "raw_macro": fixed_macro,
            }
            errs = _validate_contract_payload(payload)
            if errs:
                raise RuntimeError("schema 运行时校验失败: " + " | ".join(errs[:20]))
            return fixed_crypto, fixed_macro, merged, profiles

        crypto_news, macro_news, all_news, source_profiles = _run_step(
            "C_briefing_synthesis",
            _synthesis_step,
            step_rows,
            max_retries=0,
        )
        for row in all_news:
            if not isinstance(row, dict):
                continue
            row["market_trend_state"] = market_trend_state
            row["market_trend_ma20"] = float((market_trend_meta or {}).get("ma20") or 0.0)
            row["market_trend_volatility_20d"] = float((market_trend_meta or {}).get("volatility_20d") or 0.0)
            row["market_trend_price_vs_ma"] = float((market_trend_meta or {}).get("price_vs_ma") or 0.0)
        for row in crypto_news:
            if not isinstance(row, dict):
                continue
            row["market_trend_state"] = market_trend_state
        for row in macro_news:
            if not isinstance(row, dict):
                continue
            row["market_trend_state"] = market_trend_state
    except Exception as exc:
        status = "failed"
        failure_reason = str(exc)
        raise
    finally:
        with open(step_audit_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": now.isoformat(),
                    "file_ts": file_ts,
                    "contract_version": CONTRACT_VERSION,
                    "status": status,
                    "failure_reason": failure_reason,
                    "steps": step_rows,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

    with open(raw_dir / f"raw_crypto_{file_ts}.json", "w", encoding="utf-8") as f:
        json.dump(crypto_news, f, indent=2, ensure_ascii=False)
    with open(raw_dir / f"raw_macro_{file_ts}.json", "w", encoding="utf-8") as f:
        json.dump(macro_news, f, indent=2, ensure_ascii=False)
    with open(raw_dir / f"crawl_meta_{file_ts}.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": now.isoformat(),
                "hours": hours,
                "contract_version": CONTRACT_VERSION,
                "ledger_version_requested": requested_ledger_version,
                "ledger_version": resolved_ledger_version,
                "ledger_overlay_version": resolved_overlay_ledger_version,
                "update_mode_requested": str(update_mode or "auto"),
                "update_mode": resolved_update_mode,
                "anchor_date": resolved_anchor_date,
                "anchor_session": resolved_anchor_session,
                "anchor_key": resolved_anchor_key,
                "market_trend_state": market_trend_state,
                "market_trend_meta": market_trend_meta,
                "schema_path": str(SCHEMA_PATH),
                "mapping_policy_path": str(POLICY_PATH),
                "schema_loaded": bool(CONTRACT_SCHEMA),
                "use_ollama": use_ollama,
                "ollama_model": ollama_model if use_ollama else "",
                "counts": {"crypto": len(crypto_news), "macro": len(macro_news)},
                "step_audit_path": f"raw/step_audit_{file_ts}.json",
                "window_profile_path": str(WINDOW_PROFILE_PATH),
                "window_policy_event_type_count": len(WINDOW_POLICY_MAP),
                "market_state_config_path": str(MARKET_STATE_CONFIG_PATH),
                "market_state_config_version": str((MARKET_STATE_CONFIG or {}).get("version") or "market_state_policy.v1"),
                "macro_unknown_target_rate": MACRO_UNKNOWN_TARGET_RATE,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    quality_path = raw_dir / f"source_quality_{file_ts}.json"
    with open(quality_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": now.isoformat(),
                "file_ts": file_ts,
                "profiles": source_profiles,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    brief_v1_md, brief_v1_json = _format_brief_v1(crypto_news, macro_news, hours, file_ts)
    brief_v1_path = outputs_dir / f"brief_{file_ts}.md"
    with open(brief_v1_path, "w", encoding="utf-8") as f:
        f.write(brief_v1_md)

    brief_v1_json_path = brief_v1_path.with_suffix(".json")
    with open(brief_v1_json_path, "w", encoding="utf-8") as f:
        json.dump(brief_v1_json, f, indent=2, ensure_ascii=False)

    ledger = EventLedgerGenerator(ledger_version=resolved_ledger_version)
    ledger_entries = ledger.generate_ledger(all_news)
    ledger_errs = _validate_ledger_entries(ledger_entries)
    if ledger_errs:
        raise RuntimeError("event_ledger 校验失败: " + " | ".join(ledger_errs[:20]))
    ledger_path = raw_dir / f"event_ledger_{file_ts}.jsonl"
    ledger.save_jsonl(ledger_entries, ledger_path)
    overlay_ledger_path = None
    if resolved_overlay_ledger_version:
        overlay = EventLedgerGenerator(ledger_version=resolved_overlay_ledger_version)
        overlay_entries = overlay.generate_ledger(all_news)
        overlay_errs = _validate_ledger_entries(overlay_entries)
        if overlay_errs:
            raise RuntimeError("event_ledger_overlay 校验失败: " + " | ".join(overlay_errs[:20]))
        overlay_ledger_path = raw_dir / f"event_ledger_overlay_{resolved_overlay_ledger_version}_{file_ts}.jsonl"
        overlay.save_jsonl(overlay_entries, overlay_ledger_path)
    risk_action_events = _risk_action_events(all_news, now, file_ts)
    risk_action_path = raw_dir / f"risk_action_events_{file_ts}.json"
    with open(risk_action_path, "w", encoding="utf-8") as f:
        json.dump(risk_action_events, f, indent=2, ensure_ascii=False)
    coverage_report = _coverage_report(crypto_news, macro_news)
    coverage_path = raw_dir / f"coverage_report_{file_ts}.json"
    with open(coverage_path, "w", encoding="utf-8") as f:
        json.dump(coverage_report, f, indent=2, ensure_ascii=False)
    window_calibration_meta = _run_rolling_window_calibration(raw_dir, file_ts)

    methodology_path = raw_dir / "methodology_changelog.jsonl"
    current_snapshot = _methodology_snapshot(coverage_report, source_profiles)
    prev_snapshot = _read_last_methodology_snapshot(methodology_path)
    methodology_diff = _methodology_diff(prev_snapshot, current_snapshot)
    methodology_diff_summary = _methodology_diff_summary(methodology_diff)
    with open(methodology_path, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": now.isoformat(),
                    "file_ts": file_ts,
                    "hours": hours,
                    "contract": "doc_10.1.1.2_10.1.1.3",
                    "contract_version": CONTRACT_VERSION,
                    "ledger_version_requested": requested_ledger_version,
                    "ledger_version": resolved_ledger_version,
                    "ledger_overlay_version": resolved_overlay_ledger_version,
                    "schema_path": str(SCHEMA_PATH),
                    "mapping_policy_path": str(POLICY_PATH),
                    "community_decay_profile": {
                        "market_microstructure_half_life_hours": 6,
                        "event_security_policy_half_life_hours": 24,
                        "narrative_half_life_hours": 72,
                    },
                    "methodology_snapshot": current_snapshot,
                    "methodology_diff": methodology_diff,
                    "methodology_diff_summary": methodology_diff_summary,
                    "outputs": {
                        "raw_crypto": f"raw/raw_crypto_{file_ts}.json",
                        "raw_macro": f"raw/raw_macro_{file_ts}.json",
                        "brief_v1": f"outputs/brief_{file_ts}.md",
                        "brief_v2": f"outputs/brief_v2_{file_ts}.md",
                        "event_ledger": f"raw/event_ledger_{file_ts}.jsonl",
                        "event_ledger_overlay": f"raw/event_ledger_overlay_{resolved_overlay_ledger_version}_{file_ts}.jsonl"
                        if resolved_overlay_ledger_version
                        else "",
                        "step_audit": f"raw/step_audit_{file_ts}.json",
                        "risk_action_events": f"raw/risk_action_events_{file_ts}.json",
                        "coverage_report": f"raw/coverage_report_{file_ts}.json",
                        "source_quality": f"raw/source_quality_{file_ts}.json",
                        "window_profile": str(WINDOW_PROFILE_PATH),
                        "window_calibration": str(window_calibration_meta.get("window_calibration_path") or ""),
                        "window_version_table": str(window_calibration_meta.get("window_version_table_path") or ""),
                        "market_state_config": str(MARKET_STATE_CONFIG_PATH),
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    narrative_path = raw_dir / "narrative_decay_changelog.jsonl"
    previous_status_map: dict[str, str] = {}
    if narrative_path.exists():
        try:
            last_line = ""
            with open(narrative_path, "r", encoding="utf-8") as rf:
                for line in rf:
                    line = line.strip()
                    if line:
                        last_line = line
            if last_line:
                prev = json.loads(last_line)
                for x in prev.get("top_narratives", []):
                    t = str(x.get("title") or "").strip()
                    s = str(x.get("narrative_status") or "").strip()
                    if t and s:
                        previous_status_map[t] = s
        except Exception:
            previous_status_map = {}

    current_rows = []
    for n in all_news:
        try:
            ce = float(n.get("community_effective_score", 0.0) or 0.0)
        except Exception:
            ce = 0.0
        current_rows.append(
            {
                "title": str(n.get("title") or ""),
                "community_effective_score": round(max(0.0, min(1.0, ce)), 4),
                "community_base_score": float(n.get("community_base_score", 0.0) or 0.0),
                "decay_factor": float(n.get("decay_factor", 0.0) or 0.0),
                "attention_type": str(n.get("attention_type") or "event"),
                "narrative_status": str(n.get("narrative_status") or "archive"),
                "risk_action_proposal": str(n.get("risk_action_proposal") or "hold"),
            }
        )
    top_narratives = sorted(current_rows, key=lambda x: x["community_effective_score"], reverse=True)[:20]
    transitions = []
    for row in top_narratives:
        title = row["title"]
        curr = row["narrative_status"]
        prev = previous_status_map.get(title)
        if prev and prev != curr:
            transitions.append({"title": title, "from": prev, "to": curr})
    status_counts = {"active": 0, "cooling": 0, "archive": 0}
    for row in current_rows:
        status = row["narrative_status"]
        if status in status_counts:
            status_counts[status] += 1
    threshold_hits = {
        "high_risk": sum(1 for r in current_rows if r["community_effective_score"] >= 0.70),
        "observe": sum(1 for r in current_rows if 0.40 <= r["community_effective_score"] < 0.70),
        "low_heat": sum(1 for r in current_rows if r["community_effective_score"] < 0.40),
    }
    with open(narrative_path, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": now.isoformat(),
                    "file_ts": file_ts,
                    "hours": hours,
                    "status_counts": status_counts,
                    "threshold_hits": threshold_hits,
                    "transitions": transitions,
                    "top_narratives": top_narratives,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    ref_anchor_for_delta = _latest_anchor(resolved_anchor_date, resolved_anchor_key) if resolved_update_mode == "delta" else {}
    offset_events: list[dict] = []
    if ref_anchor_for_delta:
        all_news, offset_events = _apply_event_offset_chain(all_news, ref_anchor_for_delta)

    analyzer = TraditionalFinanceAnalyzer()
    analyzed_items = [analyzer.analyze_news(n) for n in all_news]
    signal_analysis = analyzer.generate_signal(analyzed_items)

    anchor_registry_path = ANCHOR_REGISTRY_PATH
    delta_registry_path = DELTA_REGISTRY_PATH
    anchor_state_path = ""
    delta_state_path = ""
    anchor_delta_view_path = ""
    linked_anchor_id = ""
    anchor_row_obj = {}
    delta_row_obj = {}
    if resolved_update_mode in {"anchor", "reset"}:
        anchor_row = _build_anchor_row(
            now=now,
            file_ts=file_ts,
            anchor_date=resolved_anchor_date,
            anchor_key=resolved_anchor_key,
            anchor_session=resolved_anchor_session,
            hours=hours,
            market_trend_state=market_trend_state,
            market_trend_meta=market_trend_meta,
            signal_analysis=signal_analysis,
            all_news=all_news,
        )
        anchor_errs = _validate_anchor_row(anchor_row)
        if anchor_errs:
            raise RuntimeError("anchor_registry 校验失败: " + " | ".join(anchor_errs[:20]))
        _append_jsonl(anchor_registry_path, anchor_row)
        anchor_state_file = raw_dir / f"anchor_snapshot_{file_ts}.json"
        with open(anchor_state_file, "w", encoding="utf-8") as f:
            json.dump(anchor_row, f, indent=2, ensure_ascii=False)
        anchor_state_path = str(anchor_state_file)
        linked_anchor_id = str(anchor_row.get("anchor_id") or "")
        anchor_row_obj = dict(anchor_row)
    elif resolved_update_mode == "delta":
        ref_anchor = ref_anchor_for_delta or _latest_anchor(resolved_anchor_date, resolved_anchor_key)
        if ref_anchor:
            delta_row = _build_delta_row(
                now=now,
                file_ts=file_ts,
                anchor_row=ref_anchor,
                hours=hours,
                anchor_date=resolved_anchor_date,
                anchor_key=resolved_anchor_key,
                anchor_session=resolved_anchor_session,
                market_trend_state=market_trend_state,
                signal_analysis=signal_analysis,
                all_news=all_news,
            )
            delta_errs = _validate_delta_row(delta_row)
            if delta_errs:
                raise RuntimeError("delta_registry 校验失败: " + " | ".join(delta_errs[:20]))
            _append_jsonl(delta_registry_path, delta_row)
            delta_state_file = raw_dir / f"delta_update_{file_ts}.json"
            with open(delta_state_file, "w", encoding="utf-8") as f:
                json.dump(delta_row, f, indent=2, ensure_ascii=False)
            delta_state_path = str(delta_state_file)
            linked_anchor_id = str(ref_anchor.get("anchor_id") or "")
            anchor_row_obj = dict(ref_anchor)
            delta_row_obj = dict(delta_row)
        else:
            fallback_anchor = _build_anchor_row(
                now=now,
                file_ts=file_ts,
                anchor_date=resolved_anchor_date,
                anchor_key=resolved_anchor_key,
                anchor_session=resolved_anchor_session,
                hours=hours,
                market_trend_state=market_trend_state,
                market_trend_meta=market_trend_meta,
                signal_analysis=signal_analysis,
                all_news=all_news,
            )
            fallback_errs = _validate_anchor_row(fallback_anchor)
            if fallback_errs:
                raise RuntimeError("anchor_registry 校验失败: " + " | ".join(fallback_errs[:20]))
            _append_jsonl(anchor_registry_path, fallback_anchor)
            anchor_state_file = raw_dir / f"anchor_snapshot_{file_ts}.json"
            with open(anchor_state_file, "w", encoding="utf-8") as f:
                json.dump(fallback_anchor, f, indent=2, ensure_ascii=False)
            anchor_state_path = str(anchor_state_file)
            linked_anchor_id = str(fallback_anchor.get("anchor_id") or "")
            anchor_row_obj = dict(fallback_anchor)
            resolved_update_mode = "anchor"

    anchor_delta_summary = {
        "mode": resolved_update_mode,
        "anchor_date": resolved_anchor_date,
        "anchor_id": str((anchor_row_obj or {}).get("anchor_id") or ""),
        "added_event_count": int((((delta_row_obj or {}).get("changes") or {}).get("added_event_count") or 0)),
        "resolved_event_count": int((((delta_row_obj or {}).get("changes") or {}).get("resolved_event_count") or 0)),
        "offset_events_count": len(offset_events),
    }
    briefing_md = generate_briefing_markdown(
        signal_analysis=signal_analysis,
        market_snapshot=market_snapshot,
        hours=hours,
        file_ts=file_ts,
        anchor_delta_summary=anchor_delta_summary,
    )
    anchor_delta_view = _build_anchor_delta_view(
        now=now,
        mode=resolved_update_mode,
        anchor_row=anchor_row_obj,
        delta_row=delta_row_obj,
        market_trend_state=market_trend_state,
        signal_analysis=signal_analysis,
        offset_events=offset_events,
    )
    anchor_delta_view_file = raw_dir / f"anchor_delta_view_{file_ts}.json"
    with open(anchor_delta_view_file, "w", encoding="utf-8") as f:
        json.dump(anchor_delta_view, f, indent=2, ensure_ascii=False)
    anchor_delta_view_path = str(anchor_delta_view_file)

    return {
        "briefing_md": briefing_md,
        "brief_v1_path": str(brief_v1_path),
        "brief_v1_json_path": str(brief_v1_json_path),
        "event_ledger_path": str(ledger_path),
        "event_ledger_overlay_path": str(overlay_ledger_path) if overlay_ledger_path else "",
        "ledger_version_requested": requested_ledger_version,
        "ledger_version": resolved_ledger_version,
        "ledger_overlay_version": resolved_overlay_ledger_version,
        "methodology_changelog_path": str(methodology_path),
        "narrative_changelog_path": str(narrative_path),
        "step_audit_path": str(step_audit_path),
        "risk_action_events_path": str(risk_action_path),
        "coverage_report_path": str(coverage_path),
        "source_quality_path": str(quality_path),
        "window_calibration_path": str(window_calibration_meta.get("window_calibration_path") or ""),
        "window_version_table_path": str(window_calibration_meta.get("window_version_table_path") or ""),
        "anchor_registry_path": str(anchor_registry_path),
        "delta_registry_path": str(delta_registry_path),
        "anchor_state_path": anchor_state_path,
        "delta_state_path": delta_state_path,
        "anchor_delta_view_path": anchor_delta_view_path,
        "offset_events_count": len(offset_events),
        "update_mode_requested": str(update_mode or "auto"),
        "update_mode": resolved_update_mode,
        "anchor_date": resolved_anchor_date,
        "anchor_session": resolved_anchor_session,
        "anchor_key": resolved_anchor_key,
        "linked_anchor_id": linked_anchor_id,
        "signal_analysis": {
            "composite_signal": signal_analysis.composite_signal,
            "confidence_weighted_signal": signal_analysis.confidence_weighted_signal,
            "macro_signal": signal_analysis.macro_signal,
            "industry_signal": signal_analysis.industry_signal,
            "company_signal": signal_analysis.company_signal,
            "immediate_signal": signal_analysis.immediate_signal,
            "short_term_signal": signal_analysis.short_term_signal
        },
        "investment_recommendation": signal_analysis.recommendation,
        "position_suggestion": signal_analysis.position_suggestion,
        "risk_flags": signal_analysis.risk_flags,
        "timestamp": now.isoformat()
    }


def generate_news_data(hours: int, use_ollama: bool = False, ollama_model: str = "qwen2.5:7b-instruct") -> tuple:
    crypto_news = fetch_odaily_newsflash(limit=30, hours=hours)
    macro_news = fetch_wallstreetcn_breakfast(limit=30, hours=hours)
    if use_ollama:
        crypto_news = enrich_news_with_ollama(crypto_news, model=ollama_model)
        macro_news = enrich_news_with_ollama(macro_news, model=ollama_model)
    return crypto_news, macro_news


def generate_briefing_markdown(
    signal_analysis: SignalAnalysis,
    market_snapshot: dict,
    hours: int,
    file_ts: str,
    anchor_delta_summary: dict | None = None,
) -> str:
    now = datetime.now()
    file_date = str(file_ts or "").split("_")[0] or now.strftime("%Y%m%d")
    window_start = now - timedelta(hours=int(max(1, hours)))
    btc = market_snapshot.get("crypto", {}).get("btc", {})
    eth = market_snapshot.get("crypto", {}).get("eth", {})
    nasdaq = market_snapshot.get("traditional", {}).get("nasdaq", {})
    vix = market_snapshot.get("traditional", {}).get("vix", {})
    sorted_news = sorted(
        signal_analysis.news_items,
        key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.confidence.value, 1),
    )

    def fmt_price(data: dict) -> str:
        p = data.get("price_usd", 0)
        c = data.get("change_24h", data.get("change_pct", 0) or 0)
        if p > 0:
            return f"${p:,.2f}", f"{c:+.2f}%"
        return "数据暂不可用", "0.00%"

    def fmt_plain_price(data: dict) -> str:
        p = data.get("price_usd", data.get("price", 0) or 0)
        if p > 0:
            if p >= 1000:
                return f"${p:,.0f}"
            return f"${p:,.2f}"
        return "数据暂不可用"

    def _event_time(raw: dict) -> str:
        return str(raw.get("published_at") or raw.get("fetched_at") or "")

    def _line(item) -> str:
        raw = item.raw_data or {}
        title = item.title or "无标题"
        fact = str(raw.get("fact_text") or item.content or "").strip() or "正文缺失"
        source = str(raw.get("source_url") or item.source or "").strip() or ""
        ts = _event_time(raw)
        if source and ts:
            return f"{title} - {fact}（{source}，{ts}）"
        if source:
            return f"{title} - {fact}（{source}）"
        return f"{title} - {fact}"

    bullish = []
    bearish = []
    macro = []
    for item in sorted_news:
        raw = item.raw_data or {}
        topic = str(raw.get("topic") or "").strip()
        if topic in {"fed", "us_data", "geopolitics", "us_policy", "market_analysis"}:
            macro.append(item)
        else:
            score = float(getattr(item, "signal_score", 0.0) or 0.0)
            if score >= 0:
                bullish.append(item)
            else:
                bearish.append(item)

    top_points = []
    for item in bullish[:5]:
        top_points.append(("➕", _line(item)))
    for item in bearish[:4]:
        top_points.append(("⚠️", _line(item)))
    for item in macro[:3]:
        top_points.append(("🌍", _line(item)))
    if len(top_points) < 12:
        for item in sorted_news:
            row = _line(item)
            if any(row == p[1] for p in top_points):
                continue
            top_points.append(("•", row))
            if len(top_points) >= 12:
                break

    watchlist = []
    for item in sorted_news:
        raw = item.raw_data or {}
        if str(raw.get("impact_horizon") or item.time_horizon.value) == "T0":
            watchlist.append(item.title)
    watchlist = list(dict.fromkeys([w for w in watchlist if w]))[:8]
    recommendation = str(signal_analysis.recommendation or "hold").upper()
    anchor_delta_summary = anchor_delta_summary or {}
    anchor_delta_block = "\n".join(
        [
            f"- 模式：{str(anchor_delta_summary.get('mode') or 'auto')}",
            f"- 锚点日期：{str(anchor_delta_summary.get('anchor_date') or '')}",
            f"- 锚点 ID：{str(anchor_delta_summary.get('anchor_id') or '')}",
            f"- 新增事件：{int(anchor_delta_summary.get('added_event_count') or 0)}",
            f"- 消退事件：{int(anchor_delta_summary.get('resolved_event_count') or 0)}",
            f"- 冲销事件：{int(anchor_delta_summary.get('offset_events_count') or 0)}",
        ]
    )
    event_type_labels = {
        "geopolitics": "地缘风险",
        "monetary_policy": "货币政策",
        "us_data": "美国经济数据",
        "crypto_regulation": "加密监管",
        "protocol_tech": "协议技术",
        "security_incident": "安全事件",
        "meme_culture": "meme 事件",
        "onchain_data": "链上数据",
        "kols_view": "大V观点",
        "project_update": "项目动态",
        "market_analysis": "市场分析",
        "unknown": "未知分类",
    }
    event_sections: dict[str, list] = {}
    for item in sorted_news:
        raw = item.raw_data or {}
        et = str(raw.get("event_type") or "unknown").strip() or "unknown"
        if et not in event_sections:
            event_sections[et] = []
        if len(event_sections[et]) < 3:
            event_sections[et].append(item)
    event_type_lines = []
    for et, items in sorted(event_sections.items(), key=lambda kv: len(kv[1]), reverse=True):
        label = event_type_labels.get(et, et)
        event_type_lines.append(f"### {label}（{et}）")
        for it in items:
            event_type_lines.append(f"- {_line(it)}")
    if not event_type_lines:
        event_type_lines.append("- 当前窗口暂无可用事件类型样本")
    pos_now = int(round(float(signal_analysis.position_suggestion or 0.5) * 100))
    pos_next = max(10, min(80, pos_now + (10 if signal_analysis.composite_signal > 0.12 else -10 if signal_analysis.composite_signal < -0.12 else 0)))
    btc_price, btc_24h = fmt_price(btc)
    eth_price, eth_24h = fmt_price(eth)
    nasdaq_price, nasdaq_24h = fmt_price(nasdaq)
    vix_value = float(vix.get("value", vix.get("price", 0)) or 0)
    vix_24h = float(vix.get("change_24h", vix.get("change_pct", 0)) or 0)
    ma20 = float((market_snapshot.get("crypto", {}).get("btc_ma20") or market_snapshot.get("crypto", {}).get("ma20") or 0) or 0)
    price_vs_ma = ((float(btc.get("price_usd", 0) or 0) / ma20 - 1.0) * 100.0) if ma20 > 0 else 0.0
    market_state = "震荡市（Sideways）"
    if signal_analysis.composite_signal >= 0.15:
        market_state = "趋势偏多（Bullish）"
    elif signal_analysis.composite_signal <= -0.15:
        market_state = "风险偏空（Defensive）"
    risk_lines = [f"- {x}" for x in (signal_analysis.risk_flags[:8] if signal_analysis.risk_flags else [])]
    if not risk_lines:
        risk_lines = ["- 信息时效、样本偏差、非投资建议"]
    point_lines = []
    for idx, (_, txt) in enumerate(top_points[:12], start=1):
        point_lines.append(f"{idx}. **[{txt.split(' - ')[0]}]** - {txt.split(' - ', 1)[1] if ' - ' in txt else txt}")
    if not point_lines:
        point_lines.append("1. **[样本不足]** - 当前窗口暂无可用新闻样本")

    md = f"""# 加密市场晨报（V9.3/V9.8 优化版）

**生成时间**: {now.strftime("%Y-%m-%d %H:%M:%S")} CST
**数据窗口**: {window_start.strftime("%Y-%m-%d %H:%M")} ~ {now.strftime("%Y-%m-%d %H:%M")}
**分析框架**: V9.3 事件账本 + 市场状态识别 + 动态仓位管理

---

## 📊 市场状态诊断

### 当前市场状态：**{market_state}**

| 指标 | 数值 | 阈值 | 状态 |
|------|------|------|------|
| BTC 当前价 | {fmt_plain_price(btc)} | - | {"突破" if signal_analysis.composite_signal > 0 else "观察"} |
| MA20(20 日均线) | {f"${ma20:,.0f}" if ma20 > 0 else "数据暂不可用"} | - | - |
| 价格 vs MA20 | **{price_vs_ma:+.2f}%** | +5% | {"接近牛市阈值" if price_vs_ma >= 3 else "中性"} |
| 24h 波动率 | {abs(float(btc.get("change_24h", 0) or 0)):.1f}% | 3% | {"高波动" if abs(float(btc.get("change_24h", 0) or 0)) >= 3 else "常态"} |
| VIX | {vix_value:.2f} | 22 | {"高风险" if vix_value >= 22 else "可控"} |

**判定依据**: 综合信号 {signal_analysis.composite_signal:+.3f}，可信度加权 {signal_analysis.confidence_weighted_signal:+.3f}

---

## 📈 核心数据概览

| 资产 | 价格 | 24h | 7 日 | 信号 |
|------|------|-----|-----|------|
| BTC | {btc_price} | {btc_24h} | - | {"✅ 强势" if signal_analysis.composite_signal > 0.1 else "➖ 中性" if signal_analysis.composite_signal > -0.1 else "🔴 偏弱"} |
| ETH | {eth_price} | {eth_24h} | - | {"✅ 强势" if signal_analysis.industry_signal > 0 else "➖ 中性"} |
| ETH/BTC | {market_snapshot.get('crypto', {}).get('eth_btc_ratio', 0):.4f} | - | - | ➖ 中性 |
| 纳指 | {nasdaq_price} | {nasdaq_24h} | - | {"✅ 偏强" if signal_analysis.macro_signal > 0 else "➖ 中性" if signal_analysis.macro_signal > -0.1 else "🔴 偏弱"} |
| VIX | {vix_value:.2f} | {vix_24h:+.2f}% | - | {"🔴 高风险" if vix_value >= 22 else "➖ 中性"} |

---

## 🔔 今日要点（12 条）

{chr(10).join(point_lines)}

---

## 🧭 按事件类型分节

{chr(10).join(event_type_lines)}

---

## 📐 V9.3 事件账本信号分析

### 信号计算公式
```
signal = Σ(base_sentiment × type_weight × window_weight × surprise_weight × confidence)
```

### 信号汇总

| 信号类型 | 数值 | 阈值 | 解读 |
|----------|------|------|------|
| **综合信号** | **{signal_analysis.composite_signal:+.3f}** | ±0.15 | {"偏多" if signal_analysis.composite_signal > 0.15 else "偏空" if signal_analysis.composite_signal < -0.15 else "中性"} |
| 可信度加权 | {signal_analysis.confidence_weighted_signal:+.3f} | ±0.15 | 经可靠性调整 |
| 宏观信号 | {signal_analysis.macro_signal:+.3f} | ±0.15 | {"宽松偏多" if signal_analysis.macro_signal > 0 else "收紧偏空" if signal_analysis.macro_signal < 0 else "中性"} |
| 行业信号 | {signal_analysis.industry_signal:+.3f} | ±0.15 | {"景气向上" if signal_analysis.industry_signal > 0 else "景气承压" if signal_analysis.industry_signal < 0 else "中性"} |
| 即时信号 | {signal_analysis.immediate_signal:+.3f} | ±0.15 | 当日交易参考 |

---

## 💼 动态仓位管理建议

### 今日仓位建议

```
┌─────────────────────────────────────────┐
│  建议动作：{recommendation}                           │
│  建议仓位：{pos_now}% → {pos_next}%                       │
│  信号阈值：±0.15（固定模板门槛）          │
│  风险约束：execution_gate=readonly_advisory │
└─────────────────────────────────────────┘
```

---

## ⚠️ 风险提示

{chr(10).join(risk_lines)}

---

## 📋 明日观察清单

{chr(10).join([f"- {w}" for w in watchlist]) if watchlist else "- 事件/指标/时间点/影响资产：待补充"}

---

## 🔄 相对早餐变化

{anchor_delta_block}

---

## 🎯 策略总结

> **固定模板输出：结构稳定、字段稳定、只读建议稳定**

1. 市场状态：{market_state}
2. 信号方向：综合 {signal_analysis.composite_signal:+.3f}（阈值 ±0.15）
3. 仓位建议：{pos_now}%（建议动作 {recommendation}）
4. 风控要点：以风险提示与事件账本为准，禁止直接执行

---

*报告生成：V9.3/V9.8 优化策略 | 下一份更新：按定时触发配置执行*
*落盘路径：/workspace/ops/nanoclaw/core_task1/outputs/brief_v3_{file_date}_optimized.md*
"""
    _assert_brief_v3_template(md)
    return md


def _assert_brief_v3_template(md: str) -> None:
    txt = str(md or "")
    if not txt.strip():
        raise RuntimeError("brief_v3 模板守卫失败: 内容为空")
    lines = [x.rstrip() for x in txt.splitlines()]
    first_non_empty = ""
    for x in lines:
        if x.strip():
            first_non_empty = x.strip()
            break
    if first_non_empty != BRIEF_V3_TITLE:
        raise RuntimeError("brief_v3 模板守卫失败: 标题不匹配")
    ordered_idx: list[int] = []
    for h in BRIEF_V3_REQUIRED_HEADINGS:
        idx = -1
        for i, ln in enumerate(lines):
            if ln.strip() == h:
                idx = i
                break
        if idx < 0:
            raise RuntimeError(f"brief_v3 模板守卫失败: 缺少章节 {h}")
        ordered_idx.append(idx)
    if any(ordered_idx[i] >= ordered_idx[i + 1] for i in range(len(ordered_idx) - 1)):
        raise RuntimeError("brief_v3 模板守卫失败: 章节顺序异常")
    must_tokens = [
        "**生成时间**:",
        "**数据窗口**:",
        "**分析框架**:",
        "execution_gate=readonly_advisory",
    ]
    for t in must_tokens:
        if t not in txt:
            raise RuntimeError(f"brief_v3 模板守卫失败: 缺少关键字段 {t}")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='生成优化版新闻简报（V2.0 传统金融框架）')
    parser.add_argument('--hours', '-H', type=int, default=24, help='时间窗口（小时）')
    parser.add_argument('--output', '-o', type=str, default=None, help='输出文件名')
    parser.add_argument('--json', action='store_true', help='同时输出 JSON')
    parser.add_argument('--use-ollama', action='store_true', help='使用本地 Ollama 做结构化抽取')
    parser.add_argument('--ollama-model', type=str, default='qwen2.5:7b-instruct', help='Ollama 模型名称')
    parser.add_argument('--ledger-version', type=str, default='auto', choices=['auto', '9.3', '9.5', '9.7_direct', '9.8_onchain'], help='事件账本生成器版本')
    parser.add_argument('--update-mode', type=str, default='auto', choices=['auto', 'anchor', 'delta', 'reset'], help='更新模式（auto=有锚点则增量，无锚点则锚点）')
    parser.add_argument('--anchor-date', type=str, default='', help='锚点日期 YYYY-MM-DD，默认今天')
    parser.add_argument('--anchor-session', type=str, default='auto', choices=['auto', 'apac', 'eu', 'us'], help='锚点交易时段')
    parser.add_argument('--force-anchor', action='store_true', help='强制以锚点模式运行')
    args = parser.parse_args()

    now = datetime.now()
    file_ts = now.strftime("%Y%m%d_%H%M")

    print(f"=== 生成优化版新闻简报（V2.0）===")
    print(f"时间窗口：最近 {args.hours} 小时")

    # 生成简报
    result = generate_enhanced_briefing(
        args.hours,
        use_ollama=args.use_ollama,
        ollama_model=args.ollama_model,
        ledger_version=args.ledger_version,
        update_mode=args.update_mode,
        anchor_date=args.anchor_date,
        anchor_session=args.anchor_session,
        force_anchor=args.force_anchor,
    )

    # 确定输出路径
    output_dir = Path(__file__).parent.parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        md_path = output_dir / args.output
    else:
        md_path = output_dir / f"brief_v3_{file_ts.split('_')[0]}_optimized.md"

    # 保存 Markdown
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(result["briefing_md"])
    print(f"[✓] 简报已保存：{md_path}")

    # JSON 输出（可选）
    if args.json:
        json_path = md_path.with_suffix('.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": result["timestamp"],
                "signal_analysis": result["signal_analysis"],
                "recommendation": result["investment_recommendation"],
                "position": result["position_suggestion"],
                "risk_flags": result["risk_flags"]
            }, f, indent=2, ensure_ascii=False)
        print(f"[✓] JSON 已保存：{json_path}")

    # 打印摘要
    print(f"\n【信号分析】")
    sa = result["signal_analysis"]
    print(f"  综合信号：{sa['composite_signal']:+.3f}")
    print(f"  宏观信号：{sa['macro_signal']:+.3f}")
    print(f"  行业信号：{sa['industry_signal']:+.3f}")
    print(f"\n【投资建议】")
    print(f"  建议：{result['investment_recommendation'].upper()}")
    print(f"  仓位：{result['position_suggestion']:.0%}")
    print(f"\n【状态更新】")
    print(f"  模式：{result['update_mode']}")
    print(f"  锚点日：{result['anchor_date']}")
    print(f"  时段：{result.get('anchor_session', '')}")
    if result.get("linked_anchor_id"):
        print(f"  关联锚点：{result['linked_anchor_id']}")

    return result


if __name__ == "__main__":
    main()
