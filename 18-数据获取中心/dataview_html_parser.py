"""Dataview HTML 结构化解析器（Playwright 渲染后 HTML → 字典 → DataRecord）。

策略：
1) Playwright Chromium 渲染 27s（等待 AJAX + 懒加载）→ 完整 HTML。
2) 正则 + 文本模式从 HTML 提取三块数据：
   a. echarts_cards（16个ECharts卡片：指标标题+时间范围，元信息）
   b. pulse_score（市场脉动指数分数 + 11个抄底逃顶子指标）
   c. top_inflows（链上净流入 Top10，symbol+金额）
3) to_records() 产出统一 DataRecord（category=chain/web），喂给 SqliteSink / 战略层。
"""
from __future__ import annotations

import json
import re
import html as html_mod
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from data_center.core.contract import DataRecord, CATEGORIES
    _HAS_CONTRACT = True
except Exception:
    _HAS_CONTRACT = False
    CATEGORIES = ("macro", "finance", "chain", "news", "web")

HTML_PATH = Path(__file__).parent / ".probe_output" / "dataview.html"

SOURCE_NAME = "theblockbeats_dataview"

# 抄底逃顶信号 → 五维映射（供战略层用）
SIGNAL_BUY = {"买入", "加仓", "看多", "多头", "超卖"}
SIGNAL_SELL = {"卖出", "减仓", "看空", "空头", "超买"}
SIGNAL_NEUTRAL = {"保持持有", "观望", "中性", "震荡", "N/A"}

# 五维标签映射（供 five_domain_sqlite_reader 消费）
METRIC_DIMENSIONS = {
    "M2 Global Supply": "dao",              # 道（宏观流动性）
    "DXY 美元指数": "dao",                  # 道
    "10年期美债收益率": "dao",              # 道
    "Bitfinex 杠杆多单持仓": "jiang",       # 将（衍生品）
    "市场脉动指数": "tian",                 # 天（情绪）
    "整体市场流动性指数": "tian",
    "比特币流动性指数": "tian",
    "以太坊流动性指数": "tian",
    "过去24小时累积比特币流动性指数": "tian",
    "整体市场流动性（以比特币为单位）": "tian",
    "合约多空比偏离指数": "jiang",           # 将
    "山寨币抗跌指数": "tian",
    "Bitfinex BTC/USD 溢价": "jiang",
    "USDC/USDT 溢价": "di",                 # 地（稳定币）
    "Binance USDT 借贷利率": "jiang",
    "持仓量加权资金费率年化利率": "jiang",
    "链上净流入前十币种": "di",             # 地（链上资金流）
}

# ---------- 工具 ----------
def strip_tags(s: str) -> str:
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s, flags=re.S)
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

# ---------- 提取 ----------
@dataclass
class ParsedCard:
    metric_title: str
    time_range: str
    raw: str

@dataclass
class ParsedSignal:
    index_name: str
    status: str

@dataclass
class ParsedInflow:
    rank: int
    symbol: str
    inflow_text: str

@dataclass
class PulseScore:
    score: str
    powered_by: str

def parse(html: str) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # 1. KPI 卡片标题（所有 kline-chart-wrap-head-left -> 标题 + 时间）
    # 使用正则匹配 <div class="kline-chart-wrap-head"> 下的 left+right 组合
    cards: list[ParsedCard] = []
    head_pat = re.compile(
        r'<div\s[^>]*class="kline-chart-wrap-head[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        re.I | re.S,
    )
    for hm in head_pat.finditer(html):
        inner = hm.group(1)
        left_m = re.search(r'kline-chart-wrap-head-left[^>]*>(.*?)</div>', inner, re.I|re.S)
        right_m = re.search(r'(kline-chart-wrap-head-right|home-inflow-top-rgt)[^>]*>(.*?)</div>\s*</div>', inner, re.I|re.S)
        title = strip_tags(left_m.group(1)) if left_m else ""
        tr = strip_tags(right_m.group(2)) if right_m else ""
        # 去除 Powered by / 按钮文字 / 交流群等 footer 串扰
        if any(w in title for w in ["Powered by","API 订阅","交流群","风险提示","联系我们","鲁ICP备","全部","关于我们"]):
            continue
        if title:
            cards.append(ParsedCard(metric_title=title, time_range=tr, raw=f"{title} {tr}".strip()))
    out["echarts_cards"] = [asdict(c) for c in cards]

    # 2. 抄底逃顶指标 - 脉动指数 + 状态列表
    pulse_m = re.search(
        r'macd-wrap-head-right-num[^>]*>\s*([\-]?\d[\d\.]*)',
        html, re.I|re.S,
    )
    powered_m = re.search(
        r'抄底逃顶指标.*?Powered by[:：]\s*([^<\n]+)',
        html, re.I|re.S,
    )
    out["pulse_score"] = asdict(PulseScore(
        score=pulse_m.group(1).strip() if pulse_m else "",
        powered_by=powered_m.group(1).strip() if powered_m else "",
    ))

    signals: list[ParsedSignal] = []
    # 每个 li: 标题名（macd-wrap-title-name[-li]） + 状态（macd-wrap-cont-li-status status1|2|3）
    li_pat = re.compile(
        r'<div[^>]*class="[^"]*macd-wrap-cont-li[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*macd-wrap-cont-li|Powered by)',
        re.I|re.S,
    )
    for li in li_pat.finditer(html):
        inner = li.group(1)
        name_m = re.search(
            r'class="[^"]*macd-wrap-title-name(?:\s+macd-wrap-title-name-li)?[^"]*"[^>]*>\s*([^<]+)',
            inner, re.I,
        )
        status_m = re.search(
            r'class="[^"]*macd-wrap-cont-li-status status\d[^"]*"[^>]*>\s*([^<]+)',
            inner, re.I,
        )
        # 也支持无 status class 的写法：文本中最后一个中文词通常为"买入/卖出/保持持有"
        if not status_m:
            last = re.findall(r">(保持持有|买入|卖出|观望|减仓|加仓|中性|多头|空头|超买|超卖|震荡)<", inner, re.I)
            status = last[-1] if last else ""
        else:
            status = status_m.group(1).strip()
        name = name_m.group(1).strip() if name_m else ""
        if name:
            signals.append(ParsedSignal(index_name=name, status=status or "N/A"))
    out["bottom_signals"] = [asdict(s) for s in signals]

    # 3. 链上净流入 Top N：整段文本解析更稳定
    inflows: list[ParsedInflow] = []
    chart_blk = re.search(
        r'<div[^>]*class="[^"]*top-tokens-chart[^"]*"[^>]*>(.*?)(Powered by|API 订阅|<div[^>]*class="footer)',
        html, re.I | re.S,
    )
    if chart_blk:
        raw = strip_tags(chart_blk.group(1))
        # (symbol + inflow amount) 对：
        #   symbol 是 3-15字母/数字 的全大写 token，或"牛来"等中文币名
        #   inflow 是 数字+K/M/B/万 后缀
        pairs = re.findall(
            r'([A-Z][A-Z0-9]{2,15}|牛来)\s+'
            r'([\-]?[\d\.,]+(?:[KMBT万亿]|美元|USDT|BTC|ETH)?)',
            raw,
        )
        rank = 0
        seen: set[str] = set()
        for sym, amt in pairs:
            if sym in seen:
                continue
            seen.add(sym)
            if sym in {"LOGO", "全部", "API", "交流群", "通道", "关于", "风险"}:
                continue
            rank += 1
            inflows.append(ParsedInflow(rank=rank, symbol=sym, inflow_text=amt))
    out["top_inflows"] = [asdict(i) for i in inflows]

    # 4. 抄底逃顶 11 子指标：整段文本切分更鲁棒（DOM 正则匹配失败兜底）
    if not any(s.status and s.status != "N/A" for s in signals):
        block = re.search(
            r'<div[^>]*class="macd-wrap"[^>]*>(.*?)(?=<div class="home-echarts-component|Powered by)',
            html, re.S | re.I,
        )
        if block:
            raw = strip_tags(block.group(1))
            # 脉动指数（"市场脉动指数 51 ..."）
            m = re.search(r'市场脉动指数\s+([\-]?\d[\d\.]*)', raw)
            if m and not pulse_m:
                out["pulse_score"] = asdict(PulseScore(
                    score=m.group(1).strip(),
                    powered_by=out.get("pulse_score", {}).get("powered_by", ""),
                ))
            # 切分成 "指标名 + 状态" 的二元组（按中文/英文指标名与状态枚举边界）
            known_statuses = r"(保持持有|买入|卖出|观望|减仓|加仓|中性|多头|空头|超买|超卖|震荡)"
            idx_names_pat = "|".join(re.escape(s.index_name) for s in signals if s.index_name)
            if idx_names_pat:
                pattern = f"({idx_names_pat})\\s+{known_statuses}"
                updated: list[ParsedSignal] = []
                found: dict[str, str] = {}
                for nm, st in re.findall(pattern, raw):
                    found[nm] = st
                for s in signals:
                    new_status = found.get(s.index_name, s.status)
                    updated.append(ParsedSignal(index_name=s.index_name, status=new_status))
                out["bottom_signals"] = [asdict(s) for s in updated]

    return out

if __name__ == "__main__":
    import json
    html = HTML_PATH.read_text(encoding="utf-8")
    data = parse(html)

    print("=== ECharts 卡片元信息 ({}) ===".format(len(data["echarts_cards"])))
    for i, c in enumerate(data["echarts_cards"], 1):
        print(f"  #{i:02d} [{c['time_range']:>5}] {c['metric_title']}")

    ps = data["pulse_score"]
    print(f"\n=== 抄底逃顶 / 市场脉动指数: {ps['score']} (powered by {ps['powered_by']}) ===")
    print("信号列表 ({}):".format(len(data["bottom_signals"])))
    for s in data["bottom_signals"]:
        emoji = {"买入":"🟢","卖出":"🔴","保持持有":"🟡","N/A":"⚪"}.get(s["status"][:4],"⚪")
        print(f"  {emoji} {s['index_name']:>20} → {s['status']}")

    print(f"\n=== 链上净流入 Top N ({len(data['top_inflows'])}) ===")
    for i, row in enumerate(data["top_inflows"], 1):
        print(f"  #{row['rank']:02d} {row['symbol']:<15} inflow {row['inflow_text']}")

    (HTML_PATH.parent / "parsed_structured.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✓ 已写入 parsed_structured.json  ({HTML_PATH.parent})")


# ──────────────────────────────────────────────────────────────────────────────
#  转换：解析结果 → DataRecord 列表（统一契约，喂给 SqliteSink / 五维 reader）
# ──────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _dimension_for(metric_key: str) -> str:
    """映射到易经五维维度标签（dao/tian/di/jiang/fa）。"""
    for k, dim in METRIC_DIMENSIONS.items():
        if metric_key.startswith(k) or k in metric_key:
            return dim
    return "fa"


def _signal_to_score(status: str) -> float:
    """抄底逃顶信号 → -1.0 (卖出) ~ +1.0 (买入)，中性 0.0."""
    if status in SIGNAL_BUY:
        return 1.0
    if status in SIGNAL_SELL:
        return -1.0
    return 0.0


def _parse_amount_usd(txt: str) -> float | None:
    """1.40M → 1_400_000.0, 596.20K → 596_200.0, 86.02K → 86_020.0，不识别返回 None."""
    if not txt or txt == "N/A":
        return None
    m = re.fullmatch(r'([\-]?[\d\.,]+)\s*([KMBT万亿]?)', txt.strip())
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "万": 1e4, "亿": 1e8}[m.group(2)]
    return round(num * mult, 2)


def to_records(data: dict[str, Any], source: str = SOURCE_NAME,
               ts: str | None = None) -> list["DataRecord"]:
    """将 parse() 输出 → DataRecord 列表（4类：echarts卡片元 / 脉动指数 / 信号 / 净流入）。"""
    if not _HAS_CONTRACT:
        raise RuntimeError("data_center.core.contract 导入失败，无法产出 DataRecord。")
    ts = ts or _now_iso()
    recs: list[DataRecord] = []

    # (1) ECharts 卡片元信息（宏观/链上的图表清单，无数值 → 仅 events / raw）
    for card in data.get("echarts_cards", []):
        title = card.get("metric_title", "")
        dim = _dimension_for(title)
        recs.append(DataRecord(
            source=source,
            category="web" if dim == "fa" else {
                "dao": "macro", "tian": "web", "di": "chain", "jiang": "finance", "fa": "web",
            }[dim],
            sub_category=f"echarts_card_meta_{dim}",
            timestamp=ts,
            metrics={
                "five_dimension": dim,
                "metric_title": title,
                "time_range": card.get("time_range", ""),
            },
            events=[{"type": "chart_card", "title": title, "raw": card}],
            timeseries=[],
            raw=card,
        ))

    # (2) 市场脉动指数（情绪打分 0-100 → 天维度）
    ps = data.get("pulse_score", {})
    if ps:
        try:
            score_val = float(ps["score"]) if ps.get("score") else None
        except (TypeError, ValueError):
            score_val = None
        pulse_metrics = {
            "five_dimension": _dimension_for("市场脉动指数"),
            "score": score_val if score_val is not None else "",
            "score_raw": ps.get("score", ""),
            "powered_by": ps.get("powered_by", ""),
        }
        pulse_metrics = {k: v for k, v in pulse_metrics.items() if v != ""}
        recs.append(DataRecord(
            source=source,
            category="web",
            sub_category="bottom_pulse_index",
            timestamp=ts,
            metrics=pulse_metrics,
            events=[{"type": "pulse_score", **ps}],
            timeseries=[],
            raw=ps,
        ))

    # (3) 11 个抄底逃顶信号（逐个记录 → 天/将/地 多维）
    for sig in data.get("bottom_signals", []):
        name = sig.get("index_name", "")
        status = sig.get("status", "N/A")
        dim = _dimension_for(name)
        cat_map = {"dao": "macro", "tian": "web", "di": "chain", "jiang": "finance", "fa": "web"}
        recs.append(DataRecord(
            source=source,
            category=cat_map.get(dim, "web"),
            sub_category=f"bottom_signal_{dim}",
            timestamp=ts,
            metrics={
                "five_dimension": dim,
                "signal_name": name,
                "status": status,
                "score": _signal_to_score(status),
            },
            events=[{"type": "signal", **sig}],
            timeseries=[],
            raw=sig,
        ))

    # (4) 链上净流入 Top N（地维度）
    for inflow in data.get("top_inflows", []):
        amt_usd = _parse_amount_usd(inflow.get("inflow_text", ""))
        recs.append(DataRecord(
            source=source,
            category="chain",
            sub_category="top10_inflow_di",
            timestamp=ts,
            metrics={
                "five_dimension": "di",
                "rank": inflow.get("rank", 0),
                "symbol": inflow.get("symbol", ""),
                "inflow_text": inflow.get("inflow_text", ""),
                "inflow_usd": amt_usd if amt_usd is not None else "",
            },
            events=[{"type": "top_inflow", **inflow}],
            timeseries=[],
            raw=inflow,
        ))
    return recs


if __name__ == "__main__":  # noqa: E302 (keep for back-compat)
    pass  # CLI entrypoint 已经跑到上面 print 块，这里不需要重复
