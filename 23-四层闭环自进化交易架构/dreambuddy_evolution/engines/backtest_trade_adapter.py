"""
BacktestTradeAdapter — 回测交易记录适配层

将 walk_forward_backtester.Trade 转换为 TradeIndexBuilder 期望的字典格式，
以 source_system="backtest" 注入系统级交易索引库，供 ReflectionScanner 统计胜率。

解决冷启动问题：新币种无真实交易记录 → reflection_ri=0.50，通过回测数据注入
为扫描池全部币种提供胜率统计。

设计原则：
- FAIL-OPEN：转换异常时跳过该条交易，不中断整体
- 来源隔离：source_system="backtest"，与真实交易区分
- 折扣机制：由 ReflectionScanner 对 backtest 来源打折扣（缓解 sim-to-real gap）
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# 标准化方向
_DIRECTION_MAP = {1: "long", -1: "short", "1": "long", "-1": "short"}


def trade_to_index_record(
    trade: Any,
    coin: str,
    timestamps: list | None = None,
    size: float = 1.0,
) -> dict[str, Any] | None:
    """
    将 walk_forward_backtester.Trade 转换为 TradeIndexBuilder 格式。

    Args:
        trade: Trade 对象（或兼容的 dict/dataclass）
        coin: 币种名称
        timestamps: K 线时间戳列表，用于 bar index → ISO 时间转换；为 None 时用当前时间
        size: 名义仓位大小，用于 pnl 计算

    Returns:
        标准化字典，或 None（转换失败时）
    """
    try:
        # 支持 dataclass 和 dict
        if isinstance(trade, dict):
            g = trade.get
        else:
            g = lambda k, d=None: getattr(trade, k, d)

        direction_raw = g("direction")
        direction = _DIRECTION_MAP.get(direction_raw, "long" if direction_raw == 1 else "short")

        entry_price = float(g("entry_price", 0.0) or 0.0)
        exit_price = float(g("exit_price", 0.0) or 0.0)
        pnl_pct = float(g("pnl_pct", 0.0) or 0.0)
        confidence = float(g("confidence", 0.5) or 0.5)

        # pnl = entry_price * pnl_pct * size（名义盈亏）
        pnl = entry_price * pnl_pct * size

        # bar index → ISO 时间
        entry_time = _bar_to_iso(g("entry_bar"), timestamps)
        exit_time = _bar_to_iso(g("exit_bar"), timestamps)

        return {
            "coin": coin,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "pnl": round(pnl, 6),
            "pnl_pct": round(pnl_pct, 6),
            "confidence": round(confidence, 4),
            "exit_reason": g("exit_reason", "backtest") or "backtest",
            "source_system": "backtest",
            "strategy_source": "walk_forward_backtest",
        }
    except Exception as e:
        logger.warning("[FO] backtest trade convert fail for %s: %s", coin, e)
        return None


def _bar_to_iso(bar_idx: int | None, timestamps: list | None) -> str:
    """将 bar index 转换为 ISO 时间字符串。"""
    try:
        if timestamps and bar_idx is not None and 0 <= bar_idx < len(timestamps):
            ts = timestamps[bar_idx]
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if isinstance(ts, str):
                return ts
            if hasattr(ts, "isoformat"):
                return ts.isoformat()
        # fallback: 当前时间
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def write_backtest_trades(
    records: list[dict[str, Any]],
    output_path: str | Path,
) -> int:
    """
    将回测交易记录写入 jsonl 文件。

    Returns:
        成功写入的记录数
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for rec in records:
                if not rec:
                    continue
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                written += 1
    except Exception as e:
        logger.error("[FO] write backtest trades fail: %s", e)
        return 0

    logger.info("wrote %d backtest trades to %s", written, output_path)
    return written
