"""run_human_baseline.py — E0b 人工策略池 OOS 基线运行（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E0）。

设计约束：
  - 数据源为真实执行结果（bcrm_trades.db 实盘成交 + btc_1h_ts.json 行情），非模拟回测——
    实盘配置的基线即其实际表现，避免回放器偏差；
  - OOS 区间纪律（§5）：取成交记录最近 30% 时间窗为 OOS，此前为 IS（样本内）；
  - FAIL-OPEN：数据缺失时该配置标记 baseline_pending，不阻断。

输出：48-涌现架构/registry/human_baseline.json
  每条：config_id、结构向量 hash、OOS PnL/夏普/最大回撤、区间、成交数。
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "48-涌现架构" / "registry"
_TRADES_DB = _REPO_ROOT / "11-易经推理系统" / "scripts" / "data" / "bcrm_trades.db"
OOS_FRACTION = 0.3  # 最近 30% 时间窗为 OOS


def _load_trades() -> List[Dict[str, Any]]:
    trades: List[Dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(_TRADES_DB))
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT symbol, direction, entry_time, exit_time, entry_price, "
            "exit_price, pnl_pct, hold_bars, exit_reason, confidence FROM trades "
            "ORDER BY entry_time"
        ):
            trades.append(dict(row))
        conn.close()
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        pass
    return trades


def _metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """计算 OOS 指标：累计 PnL(%)、夏普（按笔）、最大回撤（按笔累计）。"""
    if not trades:
        return {"n_trades": 0, "status": "baseline_pending"}
    pnls = [float(t["pnl_pct"]) for t in trades if t.get("pnl_pct") is not None]
    if not pnls:
        return {"n_trades": 0, "status": "baseline_pending"}
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    mean = sum(pnls) / len(pnls)
    var = sum((p - mean) ** 2 for p in pnls) / len(pnls)
    std = math.sqrt(var)
    sharpe = (mean / std) * math.sqrt(len(pnls)) if std > 0 else 0.0
    return {
        "n_trades": len(pnls),
        "total_pnl_pct": round(cum, 4),
        "sharpe_per_trade": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd, 4),
        "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 4),
        "status": "ok",
    }


def run() -> Dict[str, Any]:
    registry = json.loads((_REGISTRY / "human_config_hashes.json").read_text(encoding="utf-8"))
    trades = _load_trades()
    # OOS 切分：按 entry_time 排序后最近 30% 为 OOS
    oos_n = max(1, int(len(trades) * OOS_FRACTION)) if trades else 0
    oos_trades = trades[-oos_n:] if oos_n else []
    is_trades = trades[:-oos_n] if oos_n else []

    baselines = []
    for cfg in registry.get("human_configs", []):
        entry = {
            "config_id": cfg.get("id"),
            "source": cfg.get("source", ""),
            "oos_window": {
                "start": oos_trades[0]["entry_time"] if oos_trades else None,
                "end": oos_trades[-1]["exit_time"] if oos_trades else None,
                "fraction": OOS_FRACTION,
            },
            "is_metrics": _metrics(is_trades),
            "oos_metrics": _metrics(oos_trades),
            "generated_at": datetime.now().isoformat(),
        }
        baselines.append(entry)

    out = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "purpose": "E0b 人工策略池 OOS 基线（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E0）：E-BIZ 判据③对照基准（涌现策略须优于本基线）",
        "data_source": {
            "trades_db": str(_TRADES_DB.relative_to(_REPO_ROOT)),
            "note": "实盘真实成交（非模拟回测）；单配置池，known_gaps 见 human_config_hashes.json",
        },
        "baselines": baselines,
    }
    _REGISTRY.mkdir(parents=True, exist_ok=True)
    (_REGISTRY / "human_baseline.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return out


def main() -> int:
    out = run()
    for b in out["baselines"]:
        print(f"{b['config_id']}: OOS={b['oos_metrics']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
