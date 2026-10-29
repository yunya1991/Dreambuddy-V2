# -*- coding: utf-8 -*-
"""43 层自建情绪通道（SPEC v1.0 冻结决策 #2，方案A 实施）。

数据流：18-数据获取中心 records 表（fear_greed / fear_greed_enhanced）→
        本模块（只读）→ 市场情绪维（market_sentiment）输入源。

设计原则：
- 只读：绝不写数据获取中心任何数据
- fail-open：数据缺失/过期/异常 → 返回中性 50
- 时效校验：F&G 数据超过 3 天视为过期（fail-open 中性）
- 输出：market_sentiment_score（0-100 整数）+ 分量明细

v1.2.1：数据源切换——18 层已于 2026-10-17 完成 SQLite → PostgreSQL 迁移
（38-数据库管理系统 SPEC 方案 4），本模块优先读 PostgreSQL（实时数据），
Postgres 不可用时回退 SQLite 旧库（历史数据，时效校验自然 fail-open）。
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# 18-数据获取中心数据库路径（SQLite 旧库，2026-10-17 迁移后仅历史数据）
_DATA_CENTER_DB = "/home/luke/dreambuddy/18-数据获取中心/data_center.db"

# PostgreSQL 连接参数（与 18 层 sink_postgres 保持一致，从环境变量读取）
_PG_HOST = os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1")
_PG_PORT = int(os.environ.get("DATA_CENTER_PG_PORT", "5432"))
_PG_USER = os.environ.get("DATA_CENTER_PG_USER", "dreambuddy")
_PG_DB = os.environ.get("DATA_CENTER_PG_DB", "data_center")

# F&G 数据最大容忍时效（秒）：F&G 为日级更新，3 天容忍
_MAX_AGE_SECONDS = 3 * 24 * 3600

# 增强版 F&G 分量键
_COMPONENT_KEYS = ("momentum", "funding", "capital_flow", "volatility")


def _discover_pg_password() -> str:
    """密码发现：环境变量优先，否则从现有 .env 配置提取（与 18 层 sink_postgres 逻辑一致）。"""
    pwd = os.environ.get("DATA_CENTER_PG_PASSWORD", "")
    if pwd:
        return pwd
    for env_path in (
        Path.home() / "dreambuddy" / "7-产物中台" / "系统研究索引体系" / ".env",
        Path("/home/luke/dreambuddy/7-产物中台/系统研究索引体系/.env"),
    ):
        try:
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    m = re.search(r"postgresql://[^:\s]+:([^@\s]+)@", line)
                    if m:
                        return m.group(1)
        except Exception:
            continue
    return ""


def _parse_ts(value: str) -> Optional[datetime]:
    """解析数据获取中心时间戳（ISO8601 带 Z 后缀）。"""
    try:
        ts = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _row_to_result(row: Any, source: str) -> Dict[str, Any]:
    """公共：单行 (timestamp, metrics) → 结果 dict（含时效校验）。"""
    ts_raw, metrics_raw = row
    ts = _parse_ts(ts_raw)
    if ts is None:
        return {"available": False, "note": "F&G 时间戳非法（fail-open）"}
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    if age < 0 or age > _MAX_AGE_SECONDS:
        return {"available": False, "note": "F&G 数据过期（fail-open）", "age_hours": round(age / 3600, 1)}

    metrics = json.loads(metrics_raw) if isinstance(metrics_raw, str) else (metrics_raw or {})
    components = {
        k: v for k, v in metrics.items()
        if k in _COMPONENT_KEYS
    }
    # 综合值：优先 value / fear_greed_value；缺失时回退分量均值
    value = metrics.get("value")
    if value is None:
        value = metrics.get("fear_greed_value")
    if value is None and components:
        comp_vals = [float(v) for v in components.values() if isinstance(v, (int, float))]
        if comp_vals:
            value = sum(comp_vals) / len(comp_vals)
    return {
        "available": True,
        "source": source,
        "ts": ts_raw,
        "value": value,
        "components": components,
    }


def _load_fear_greed_pg() -> Dict[str, Any]:
    """从 PostgreSQL 加载 F&G（18 层 2026-10-17 迁移后的主数据源，只读）。"""
    try:
        import psycopg2  # 延迟导入：无 psycopg2 环境下回退 SQLite
    except ImportError:
        return {"available": False, "note": "psycopg2 未安装（fail-open）"}
    conn = None
    try:
        conn = psycopg2.connect(
            host=_PG_HOST, port=_PG_PORT, user=_PG_USER,
            password=_discover_pg_password(), dbname=_PG_DB,
        )
        cur = conn.cursor()
        # 优先：增强版 F&G（含分量）
        cur.execute(
            "SELECT timestamp, metrics FROM records "
            "WHERE source='fear_greed_enhanced' "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        row = cur.fetchone()
        source = "fear_greed_enhanced"
        if not row:
            cur.execute(
                "SELECT timestamp, metrics FROM records "
                "WHERE source='fear_greed' "
                "ORDER BY timestamp DESC LIMIT 1"
            )
            row = cur.fetchone()
            source = "fear_greed"
        if not row:
            return {"available": False, "note": "F&G 数据不存在（fail-open）"}
        return _row_to_result(row, source)
    except Exception as exc:  # noqa: BLE001  fail-open
        return {"available": False, "note": "F&G PostgreSQL 加载失败（fail-open）: {}".format(exc)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _load_fear_greed_sqlite(db_path: str) -> Dict[str, Any]:
    """从 SQLite 旧库加载 F&G（回退数据源，只读）。"""
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT timestamp, metrics FROM records "
                "WHERE source='fear_greed_enhanced' "
                "ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            source = "fear_greed_enhanced"
            if not row:
                row = conn.execute(
                    "SELECT timestamp, metrics FROM records "
                    "WHERE source='fear_greed' "
                    "ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                source = "fear_greed"
            if not row:
                return {"available": False, "note": "F&G 数据不存在（fail-open）"}
            return _row_to_result(row, source)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001  fail-open
        return {"available": False, "note": "F&G SQLite 加载失败（fail-open）: {}".format(exc)}


def query_pg(sql: str, params: tuple = ()) -> list:
    """公共只读查询：执行 SQL 并返回全部行（供本模块及其他 43 层模块复用）。

    连接失败/异常时抛出原异常，由调用方决定 fail-open 策略。
    """
    import psycopg2
    conn = psycopg2.connect(
        host=_PG_HOST, port=_PG_PORT, user=_PG_USER,
        password=_discover_pg_password(), dbname=_PG_DB,
    )
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def load_fear_greed(db_path: str = _DATA_CENTER_DB) -> Dict[str, Any]:
    """只读加载恐惧贪婪指数（fail-open 返回 available=False）。

    数据源优先级：PostgreSQL（18 层迁移后主库）→ SQLite 旧库（回退）。
    优先取 fear_greed_enhanced（含分量），回退 fear_greed（单一值）。
    """
    pg_result = _load_fear_greed_pg()
    if pg_result.get("available"):
        return pg_result
    sqlite_result = _load_fear_greed_sqlite(db_path)
    if sqlite_result.get("available"):
        return sqlite_result
    # 两者均不可用：合并说明（保留 PG 主因）
    return {
        "available": False,
        "note": "PG: {} | SQLite: {}".format(pg_result.get("note"), sqlite_result.get("note")),
    }


def compute_market_sentiment_score(db_path: str = _DATA_CENTER_DB) -> Dict[str, Any]:
    """计算市场情绪分（0-100 整数，fail-open 中性 50）。

    评分规则：
    - 基础：F&G 值直接映射（0-100）
    - 增强版分量可用时：value 70% + 分量均值 30%（分量缺失回退 value）
    - 任何异常 → 中性 50
    """
    fg = load_fear_greed(db_path)
    if not fg.get("available"):
        return {
            "market_sentiment_score": 50,
            "available": False,
            "note": fg.get("note", "情绪数据不可用（fail-open 中性 50）"),
        }

    value = fg.get("value")
    components = fg.get("components") or {}
    try:
        if not isinstance(value, (int, float)):
            return {"market_sentiment_score": 50, "available": False, "note": "F&G 值非法（fail-open 中性 50）"}
        base = float(value)
        comp_vals = [float(v) for v in components.values() if isinstance(v, (int, float))]
        if comp_vals:
            score = base * 0.70 + (sum(comp_vals) / len(comp_vals)) * 0.30
        else:
            score = base
        score = int(max(0, min(100, round(score))))
        return {
            "market_sentiment_score": score,
            "available": True,
            "source": fg.get("source"),
            "ts": fg.get("ts"),
            "fg_value": value,
            "components": components,
        }
    except Exception:  # noqa: BLE001
        return {"market_sentiment_score": 50, "available": False, "note": "情绪分计算异常（fail-open 中性 50）"}


if __name__ == "__main__":
    print(json.dumps(compute_market_sentiment_score(), ensure_ascii=False, indent=2))
