#!/usr/bin/env python3
"""市场事实日报：从公开日线接口取数，计算仅描述已发生事实的统计量。

用法:
    python3 facts.py --symbols sh000001,sz399006
    python3 facts.py --symbols AAPL --json

数据源（公开、免鉴权）:
    https://web.ifzq.gtimg.cn/appstock/app/fqkline/get  (腾讯行情，前复权)
    支持 A 股/指数（sh000001、sz399006）与美股（usAAPL.OQ）

输出为 Markdown 表格 + 方法ID/数据源/缺失/说明四行；--json 输出结构化结果。
仅使用标准库，无需安装依赖。
"""

import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime

TENCENT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
CN_SYMBOL = re.compile(r"^(sh|sz|bj)\d{6}$", re.I)
US_SYMBOL = re.compile(r"^us[A-Za-z.]+$", re.I)
SYMBOL_HINT = ("标的格式：A股/指数用 sh/sz/bj + 6 位数字（如 sh600519、sz000001），"
               "美股用 us + 代码（如 usAAPL.OQ）；不支持 BTCUSDT、600519、000001、AAPL 这类写法")
NAMES = {
    "sh000001": "上证综指",
    "sz399001": "深证成指",
    "sh000300": "沪深300",
    "sz399006": "创业板指",
    "sh000905": "中证500",
}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def _get_json(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_tencent(symbol, limit):
    key = symbol.lower() if CN_SYMBOL.match(symbol) else symbol
    query = urllib.parse.urlencode({"param": "{},day,,,{},qfq".format(key, limit)})
    payload = _get_json(TENCENT + "?" + query)
    data = payload.get("data") or {}
    node = data.get(key) or {}
    if not node:
        for name, value in data.items():
            if name.lower() == key.lower():
                node = value
                break
    rows = node.get("qfqday") or node.get("day") or []
    out = [(r[0], float(r[2])) for r in rows if len(r) >= 3]
    if not out:
        raise ValueError("empty klines")
    return out


def fetch_series(symbol, limit=320):
    if CN_SYMBOL.match(symbol) or US_SYMBOL.match(symbol):
        return fetch_tencent(symbol, limit), "腾讯行情(前复权)"
    raise ValueError(SYMBOL_HINT)


def pct_change(closes, k):
    if len(closes) <= k:
        return None
    return closes[-1] / closes[-1 - k] - 1.0


def percentile(closes, window):
    sample = closes[-window:]
    if len(sample) < window:
        return None
    return sum(1 for x in sample if x <= sample[-1]) / float(len(sample))


def annualized_vol(closes, window=20):
    if len(closes) < window + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(len(closes) - window, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def max_drawdown(closes, window):
    sample = closes[-window:]
    if len(sample) < window:
        return None
    peak = sample[0]
    worst = 0.0
    for x in sample:
        peak = max(peak, x)
        worst = min(worst, x / peak - 1.0)
    return worst


def ma_deviation(closes, window=60):
    if len(closes) < window:
        return None
    ma = sum(closes[-window:]) / window
    return closes[-1] / ma - 1.0


def fmt_pct(value, digits=2):
    return "—" if value is None else "{:+.{}f}%".format(value * 100, digits)


def fmt_plain(value, digits=2):
    return "—" if value is None else "{:.{}f}".format(value, digits)


def build_row(symbol, series, source, window):
    closes = [c for _, c in series]
    n = len(closes)
    return {
        "symbol": symbol,
        "name": NAMES.get(symbol.lower(), symbol),
        "source": source,
        "date": series[-1][0],
        "close": round(closes[-1], 3),
        "d1": pct_change(closes, 1),
        "d5": pct_change(closes, 5),
        "d20": pct_change(closes, 20),
        "pctile": percentile(closes, window),
        "pctile_n": min(n, window),
        "vol": annualized_vol(closes),
        "mdd": max_drawdown(closes, window),
        "mdd_n": min(n, window),
        "ma60": ma_deviation(closes),
    }


def render_markdown(rows, missing, window):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    data_date = rows[0]["date"] if rows else "—"
    lines = [
        "市场事实日报 · 数据日期 {} · 生成于 {}".format(data_date, now),
        "",
        "| 标的 | 收盘 | 1D | 5D | 20D | {}日分位 | 20日年化波动 | {}日最大回撤 | 60日均线偏离 |".format(window, window),
        "|------|------|----|----|-----|-----------|--------------|----------------|--------------|",
    ]
    for r in rows:
        pct_cell = "—"
        if r["pctile"] is not None:
            pct_cell = "{:.1f}% (n={})".format(r["pctile"] * 100, r["pctile_n"])
        vol_cell = fmt_pct(r["vol"]) + (" (n=21)" if r["vol"] is not None else "")
        mdd_cell = fmt_pct(r["mdd"]) + (" (n={})".format(r["mdd_n"]) if r["mdd"] is not None else "")
        ma_cell = fmt_pct(r["ma60"]) + (" (n=60)" if r["ma60"] is not None else "")
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            r["name"], fmt_plain(r["close"]), fmt_pct(r["d1"]), fmt_pct(r["d5"]),
            fmt_pct(r["d20"]), pct_cell, vol_cell, mdd_cell, ma_cell))
    sources = "、".join(sorted({r["source"] for r in rows})) or "—"
    lines += [
        "",
        "方法ID：M01 涨跌幅 / M02 分位 / M03 波动 / M04 回撤 / M05 均线偏离",
        "数据源：{}".format(sources),
        "缺失：{}".format("、".join(missing) if missing else "无"),
        "说明：以上均为已发生数据的统计描述，不构成投资建议，不含任何预测。",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="市场事实日报")
    parser.add_argument("--symbols", default="sh000001,sz399001,sh000300")
    parser.add_argument("--window", type=int, default=250)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rows, missing, format_errors = [], [], []
    for symbol in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        if not (CN_SYMBOL.match(symbol) or US_SYMBOL.match(symbol)):
            missing.append(symbol)
            format_errors.append(symbol)
            continue
        try:
            series, source = fetch_series(symbol)
            rows.append(build_row(symbol, series, source, args.window))
        except Exception as exc:  # 单标的失败不影响整体
            missing.append("{}({})".format(symbol, type(exc).__name__))

    if args.json:
        print(json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "window": args.window,
            "rows": rows,
            "missing": missing,
            "hint": SYMBOL_HINT if format_errors else None,
        }, ensure_ascii=False, indent=2))
        return 0 if rows else 1

    if format_errors:
        print("格式提示：{} 无法识别。{}".format(
            "、".join(format_errors), SYMBOL_HINT))

    if not rows:
        print("数据不可用：全部标的数据获取失败（{}）".format("、".join(missing)))
        return 1

    print(render_markdown(rows, missing, args.window))
    return 0


if __name__ == "__main__":
    sys.exit(main())
