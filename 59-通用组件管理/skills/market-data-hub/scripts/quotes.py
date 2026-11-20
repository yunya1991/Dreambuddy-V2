#!/usr/bin/env python3
"""D4 行情事实：公开日线行情 + 自算统计（A股/港股/美股）。

用法:
    python3 quotes.py --symbols sh600519,hk00700,usAAPL
    python3 quotes.py --symbols sh600519 --window 250 --json

代码前缀: sh/sz（A股）、hk（港股）、us（美股）。
输出: 最新收盘、1/5/20 日变动、区间分位、年化波动、最大回撤、样本量。
仅使用标准库。
"""

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime

KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={}"
UA = {"User-Agent": "market-data-hub/1.0 (research; contact: ops@neodrm.com)"}
LICENSE = "腾讯行情公开日线接口 · 未取得商业再分发授权，仅限本服务内部使用"


def fetch(symbol, bars=320, timeout=15):
    param = "{},day,,,{},qfq".format(symbol, bars)
    url = KLINE.format(urllib.parse.quote(param, safe=","))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    data = payload.get("data") or {}
    node = data.get(symbol) or {}
    series = node.get("qfqday") or node.get("day") or []
    out = []
    for row in series:
        if len(row) < 6:
            continue
        try:
            out.append((str(row[0]), float(row[2]), float(row[5])))
        except (TypeError, ValueError):
            continue
    if not out:
        raise ValueError("empty series")
    return out


def pct_change(values, k):
    if len(values) <= k or values[-1 - k] == 0:
        return None
    return values[-1] / values[-1 - k] - 1.0


def pctile(values, window):
    sample = values[-window:]
    if len(sample) < 20:
        return None
    return sum(1 for x in sample if x <= sample[-1]) / float(len(sample))


def vol(values, window=20):
    if len(values) < window + 1:
        return None
    rets = [math.log(values[i] / values[i - 1])
            for i in range(len(values) - window, len(values))
            if values[i - 1] > 0 and values[i] > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def drawdown(values):
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def build_row(symbol, obs, window):
    dates = [d for d, _, _ in obs]
    closes = [c for _, c, _ in obs]
    volumes = [v for _, _, v in obs]
    return {
        "symbol": symbol,
        "date": dates[-1],
        "close": closes[-1],
        "chg_1d": pct_change(closes, 1),
        "chg_5d": pct_change(closes, 5),
        "chg_20d": pct_change(closes, 20),
        "pctile": pctile(closes, window),
        "pctile_n": min(len(closes), window),
        "vol_20d": vol(closes),
        "max_drawdown": drawdown(closes[-window:]),
        "volume": volumes[-1],
        "observations": len(closes),
    }


def fmt_pct(x, digits=2):
    return "—" if x is None else "{:+.{}f}%".format(x * 100, digits)


def render(rows, missing, window):
    lines = [
        "行情事实 · 数据日期 {} · 生成于 {}".format(rows[0]["date"] if rows else "—",
                                             datetime.now().strftime("%Y-%m-%d %H:%M")),
        "",
        "| 标的 | 收盘 | 1日 | 5日 | 20日 | {}期分位 | 20日波动(年化) | {}期最大回撤 | 样本量 |".format(window, window),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        p = "—" if r["pctile"] is None else "{:.1f}% (n={})".format(r["pctile"] * 100, r["pctile_n"])
        lines.append("| {} | {:.3f} | {} | {} | {} | {} | {} | {} | {} |".format(
            r["symbol"], r["close"], fmt_pct(r["chg_1d"]), fmt_pct(r["chg_5d"]), fmt_pct(r["chg_20d"]),
            p, "—" if r["vol_20d"] is None else "{:.1f}%".format(r["vol_20d"] * 100),
            fmt_pct(r["max_drawdown"]), r["observations"]))
    lines += [
        "",
        "方法ID：M11 区间变动 / M12 序列分位 / M13 年化波动 / M14 最大回撤",
        "数据源：腾讯行情公开日线（前复权）",
        "许可：{}".format(LICENSE),
        "缺失：{}".format("、".join(missing) if missing else "无"),
        "说明：以上均为已发布数据的统计描述，不构成投资建议，不含预测。",
    ]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="行情事实")
    p.add_argument("--symbols", default="sh600519")
    p.add_argument("--window", type=int, default=250)
    p.add_argument("--json", action="store_true")
    p.add_argument("--endpoint", choices=["local"], default="local")
    a = p.parse_args(argv)

    rows, missing = [], []
    for s in [x.strip() for x in a.symbols.split(",") if x.strip()]:
        try:
            rows.append(build_row(s, fetch(s), a.window))
        except Exception as exc:
            missing.append("{}({})".format(s, type(exc).__name__))

    if a.json:
        print(json.dumps({
            "module": "D4",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "window": a.window,
            "rows": rows,
            "missing": missing,
            "sources": [{"name": "腾讯行情公开日线", "url": KLINE, "license": LICENSE}],
            "method_ids": ["M11", "M12", "M13", "M14"],
        }, ensure_ascii=False, indent=2))
        return 0 if rows else 1

    if not rows:
        print("数据不可用：全部标的获取失败（{}）".format("、".join(missing)))
        return 1
    print(render(rows, missing, a.window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
