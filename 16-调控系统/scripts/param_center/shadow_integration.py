"""P3 T13-T14: 参数中心影子模式增强

SPEC §2.3.4 ShadowLogger 增强：
  新增字段：
    - param_center_recommended: 参数中心聚合建议值（JSON）
    - actual_used: 子系统实际使用值（JSON）
    - deviation_pct: 偏差百分比
    - aggregator_weights: 各算法权重（JSON）

设计决策：
  用独立表 param_center_deviation_log + 独立方法 record_deviation()，
  不改动已有 shadow_param_log schema（避免破坏生产数据）。
  后续可通过 view 关联两表做联合查询。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 路径设置
# ============================================================================
_THIS = Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
if str(_YIJING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_YIJING_SCRIPTS))

# 默认 DB 路径（复用 11-易经推理系统 的 storage）
_DEFAULT_DB_PATH = _YIJING_SCRIPTS / "memory_l4" / "data" / "param_center_deviation.db"


# ============================================================================
# 表 schema
# ============================================================================
_SCHEMA = """
CREATE TABLE IF NOT EXISTS param_center_deviation_log (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol                      TEXT NOT NULL,
    timestamp                   TEXT NOT NULL,
    param_center_recommended    TEXT,   -- JSON: {sl_floor, tp_floor, atr_mult}
    actual_used                 TEXT,   -- JSON: {sl_floor, tp_floor, atr_mult}
    deviation_pct               REAL,   -- 偏差百分比 (sl 偏差 + tp 偏差均值)
    aggregator_weights          TEXT,   -- JSON: {algo_name: weight}
    confidence                  REAL,   -- 参数中心聚合置信度
    event_type                  TEXT    -- "open" | "polling" | "exit"
);
CREATE INDEX IF NOT EXISTS idx_pcdl_symbol_ts
    ON param_center_deviation_log(symbol, timestamp);
"""


class ParamCenterShadowLogger:
    """参数中心影子模式记录器。

    记录"参数中心推荐值 vs 子系统实际值"偏差，作为算法校准信号。
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        """初始化表 schema（IF NOT EXISTS 幂等）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
        except Exception as exc:
            logger.error("影子表 schema 初始化失败: %s", exc)

    def record_deviation(
        self,
        symbol: str,
        recommended: Dict[str, float],
        actual_used: Dict[str, float],
        weights: Optional[Dict[str, float]] = None,
        confidence: float = 0.0,
        event_type: str = "polling",
    ) -> Optional[int]:
        """记录一次参数中心 vs 子系统实际偏差。

        Args:
            symbol: 交易对
            recommended: 参数中心推荐值 {sl_floor, tp_floor, atr_mult}
            actual_used: 子系统实际使用值
            weights: 各算法权重（聚合器输出）
            confidence: 参数中心聚合置信度
            event_type: 事件类型 "open" | "polling" | "exit"

        Returns:
            记录 ID 或 None（失败时）
        """
        try:
            # 计算偏差百分比（sl + tp 均值）
            sl_rec = recommended.get("sl_floor", 0.0)
            sl_act = actual_used.get("sl_floor", 0.0)
            tp_rec = recommended.get("tp_floor", 0.0)
            tp_act = actual_used.get("tp_floor", 0.0)
            sl_dev = abs(sl_rec - sl_act) / max(sl_rec, 1e-6) if sl_rec > 0 else 0.0
            tp_dev = abs(tp_rec - tp_act) / max(tp_rec, 1e-6) if tp_rec > 0 else 0.0
            deviation_pct = (sl_dev + tp_dev) / 2.0

            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO param_center_deviation_log
                    (symbol, timestamp, param_center_recommended, actual_used,
                     deviation_pct, aggregator_weights, confidence, event_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        symbol.upper(),
                        datetime.utcnow().isoformat(),
                        json.dumps(recommended, ensure_ascii=False),
                        json.dumps(actual_used, ensure_ascii=False),
                        deviation_pct,
                        json.dumps(weights or {}, ensure_ascii=False),
                        confidence,
                        event_type,
                    ),
                )
                conn.commit()
                return cur.lastrowid
        except Exception as exc:
            logger.warning("record_deviation FAIL-OPEN: %s", exc)
            return None

    def query_deviation_report(
        self,
        symbol: str,
        days: int = 7,
    ) -> List[Dict]:
        """查询最近 N 天的偏差报告"""
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    """SELECT * FROM param_center_deviation_log
                    WHERE symbol = ? AND timestamp >= ?
                    ORDER BY timestamp DESC""",
                    (symbol.upper(), since),
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.warning("query_deviation_report FAIL-OPEN: %s", exc)
            return []

    def get_daily_deviation_summary(
        self,
        symbol: str,
        days: int = 30,
    ) -> Dict:
        """获取 N 天偏差统计摘要"""
        records = self.query_deviation_report(symbol, days)
        if not records:
            return {"symbol": symbol, "count": 0, "avg_deviation": 0.0}
        deviations = [r.get("deviation_pct", 0) for r in records]
        return {
            "symbol": symbol,
            "count": len(records),
            "avg_deviation": sum(deviations) / len(deviations),
            "max_deviation": max(deviations),
            "min_deviation": min(deviations),
        }


# ============================================================================
# 模块级单例
# ============================================================================
_DEFAULT_LOGGER = ParamCenterShadowLogger()


def get_shadow_logger() -> ParamCenterShadowLogger:
    """获取默认 ParamCenterShadowLogger 单例"""
    return _DEFAULT_LOGGER
