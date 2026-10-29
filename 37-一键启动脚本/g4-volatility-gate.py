#!/usr/bin/env python3
"""G4 部署窗口门（SPEC P0-4）：部署前输出 ATR20 分位 + 是否放行。

规则：
  - ATR20 分位 > 阈值（默认 90%）→ 禁部署，进入 pending 队列，推迟到下一个低波动窗口
  - 资金费率异常（|rate| > 阈值，默认 0.1%/8h）→ 禁部署
  - hotfix 豁免：`--hotfix --confirmed-by <本人> --reason <原因>` 三者齐全才放行，
    并记录补审截止时间（部署后 24h 内补审，写入 review-reports）
  - 数据缺失/陈旧 → FAIL-OPEN 放行并告警（不因取数失败阻塞部署）

只读脚本，不改动任何云端资源。P0 告警与云端健康由 `cloud-review.sh` 覆盖。

用法：
    python3 37-一键启动脚本/g4-volatility-gate.py
    python3 37-一键启动脚本/g4-volatility-gate.py --symbol ETH --threshold 90
    python3 37-一键启动脚本/g4-volatility-gate.py --hotfix --confirmed-by 张江涛 --reason "P0 故障热修"

退出码：0 放行 / 4 禁部署 / 2 参数或豁免不完整
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_TEMPLATE = str(
    REPO_ROOT / "14-V15经典马丁策略" / "data" / "backtest_cache" / "{symbol}_1d_400.json"
)
REPORT_DIR = REPO_ROOT / ".trae" / "documents" / "review-reports"

ATR_WINDOW = 20
STALE_DAYS = 7


def load_klines(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload.get("data", [])
    return payload


def atr_series(klines: list[dict], window: int = ATR_WINDOW) -> list[float]:
    """简单平均 ATR（True Range 的 window 期均值），返回从第 window 根开始的值。"""
    trs: list[float] = []
    prev_close = None
    for k in klines:
        high, low, close = float(k["h"]), float(k["l"]), float(k["c"])
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    return [sum(trs[i - window + 1 : i + 1]) / window for i in range(window - 1, len(trs))]


def percentile_rank(values: list[float], current: float) -> float:
    """current 在历史序列中的分位（<= current 的占比，%）。"""
    if not values:
        return 0.0
    return 100.0 * sum(1 for v in values if v <= current) / len(values)


def check_volatility(symbol: str, data_file: Path | None, threshold: float):
    """返回 (是否通过, 摘要 dict)。数据缺失/陈旧 → 通过但标注原因。"""
    path = data_file or Path(DEFAULT_CACHE_TEMPLATE.format(symbol=symbol))
    if not path.is_file():
        return True, {
            "status": "data_missing",
            "detail": f"未找到 {path}，按 FAIL-OPEN 放行（分位未采集）",
        }

    klines = load_klines(path)
    if len(klines) < ATR_WINDOW + 2:
        return True, {
            "status": "data_insufficient",
            "detail": f"{path} 仅 {len(klines)} 根，跳过分位",
        }

    last_ts = int(klines[-1]["t"]) / 1000
    age_days = (time.time() - last_ts) / 86400
    if age_days > STALE_DAYS:
        return True, {
            "status": "data_stale",
            "detail": f"{path.name} 最新 K 线已过期 {age_days:.1f} 天（>{STALE_DAYS}），按 FAIL-OPEN 放行",
        }

    series = atr_series(klines)
    current = series[-1]
    pct = percentile_rank(series, current)
    passed = pct <= threshold
    return passed, {
        "status": "ok",
        "symbol": symbol,
        "atr20": round(current, 4),
        "percentile": round(pct, 2),
        "threshold": threshold,
        "samples": len(series),
        "detail": f"ATR20={current:.4f}，分位 {pct:.2f}%（阈值 {threshold}%）",
    }


def check_funding(rate: float | None, threshold: float):
    if rate is None:
        return True, {"status": "not_provided", "detail": "资金费率未提供，跳过（FAIL-OPEN）"}
    passed = abs(rate) <= threshold
    return passed, {
        "status": "ok",
        "funding_rate": rate,
        "threshold": threshold,
        "detail": f"资金费率 {rate:+.4%}（阈值 ±{threshold:.2%}）",
    }


def write_hotfix_record(symbol: str, confirmed_by: str, reason: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    deadline = now + timedelta(hours=24)
    path = REPORT_DIR / f"{now:%Y-%m-%d}-g4-hotfix.md"
    line = (
        f"| {now:%Y-%m-%d %H:%M} | {symbol} | {confirmed_by} | {reason} | "
        f"补审截止 {deadline:%Y-%m-%d %H:%M} |\n"
    )
    if not path.exists():
        path.write_text(
            "# G4 hotfix 豁免记录\n\n"
            "> SPEC P0-4：hotfix 分支 + 本人显式确认可豁免 G4，部署后 24h 内补审。\n\n"
            "| 时间 | 标的 | 确认人 | 原因 | 补审 |\n|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="G4 部署窗口门（ATR20 分位 + 资金费率）")
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--data-file", type=Path, default=None)
    parser.add_argument(
        "--threshold", type=float, default=90.0, help="ATR20 分位阈值(%%)，>阈值禁部署"
    )
    parser.add_argument("--funding-rate", type=float, default=None, help="当期资金费率，如 0.0005")
    parser.add_argument("--funding-threshold", type=float, default=0.001, help="资金费率异常阈值")
    parser.add_argument("--hotfix", action="store_true", help="hotfix 分支豁免")
    parser.add_argument("--confirmed-by", default=None, help="hotfix 确认人（本人）")
    parser.add_argument("--reason", default=None, help="hotfix 原因")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    vol_ok, vol = check_volatility(args.symbol, args.data_file, args.threshold)
    fund_ok, fund = check_funding(args.funding_rate, args.funding_threshold)
    blocked = not (vol_ok and fund_ok)

    if blocked and args.hotfix:
        if not (args.confirmed_by and args.reason):
            print(
                "hotfix 豁免需同时提供 --confirmed-by 与 --reason（本人显式确认）", file=sys.stderr
            )
            return 2
        record = write_hotfix_record(args.symbol, args.confirmed_by, args.reason)
        decision = "hotfix_exempt"
        detail = f"hotfix 豁免放行，已记录补审（24h）: {record}"
        exit_code = 0
    elif blocked:
        decision = "blocked"
        detail = "禁部署：进入 pending 队列，推迟到下一个低波动窗口"
        exit_code = 4
    else:
        decision = "allowed"
        detail = "放行"
        exit_code = 0

    result = {
        "symbol": args.symbol,
        "volatility": vol,
        "funding": fund,
        "decision": decision,
        "detail": detail,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== G4 部署窗口门（{args.symbol}）===")
        print(f"  波动率: {vol['detail']}  -> {'通过' if vol_ok else '拦截'}")
        print(f"  资金费率: {fund['detail']}  -> {'通过' if fund_ok else '拦截'}")
        print(f"  决策: {decision} — {detail}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
