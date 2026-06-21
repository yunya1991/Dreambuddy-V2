#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests


def _clean_line(s: str) -> str:
    x = re.sub(r"\s+", " ", str(s or "")).strip()
    x = x.replace("•", "-").replace("：", ":")
    return x


def _strip_noise(content: str) -> str:
    out: list[str] = []
    in_code = False
    for raw in str(content or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip("\n")
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        low = s.lower()
        if "trace_id" in low or "debug" in low or "分析框架" in s:
            continue
        if "/users/" in low or "\\users\\" in low:
            continue
        if s.startswith("{") and s.endswith("}"):
            continue
        out.append(s)
    text = "\n".join(out).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _split_sections(content: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"正文": []}
    current = "正文"
    for raw in str(content or "").replace("\r\n", "\n").split("\n"):
        s = raw.strip()
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", s)
        if m:
            current = m.group(1).strip() or "正文"
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(raw.rstrip("\n"))
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _pick_section(parsed: dict[str, str], keywords: list[str]) -> str:
    for name, text in parsed.items():
        n = name.lower()
        if any(k.lower() in n for k in keywords) and text.strip():
            return text.strip()
    return ""


def _to_bullets(text: str, max_items: int = 5) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\n；;。]", str(text or "")):
        s = _clean_line(raw)
        if not s:
            continue
        if s.startswith("-"):
            s = s[1:].strip()
        if len(s) < 4:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _summary_from_bullets(items: list[str], limit: int = 220) -> str:
    merged = "；".join([x for x in items if x.strip()])
    merged = re.sub(r"\s+", " ", merged).strip()
    if not merged:
        merged = "加密市场信息日报"
    return merged[:limit]


def _is_relevant_market_state_line(text: str) -> bool:
    s = _clean_line(text)
    low = s.lower()
    if not s:
        return False
    if "|" in s:
        return False
    if "http://" in low or "https://" in low or "://" in low:
        return False
    reject_kw = ["价格预测", "预售", "meme", "presale", "airdrop", "launchpad", "钠电", "锂电", "机器人第一股"]
    if any(k.lower() in low for k in reject_kw):
        return False
    allow_kw = [
        "热度",
        "资金",
        "净流入",
        "净流出",
        "波动",
        "成交",
        "流动性",
        "杠杆",
        "清算",
        "趋势",
        "突破",
        "回撤",
        "主线",
        "btc",
        "eth",
        "比特币",
        "以太坊",
        "etf",
        "稳定币",
        "美联储",
        "fomc",
    ]
    return any(k in low for k in allow_kw) or any(k in s for k in allow_kw)


def _extract_market_state(parsed: dict[str, str], fallback_text: str) -> list[str]:
    market = _pick_section(parsed, ["市场", "宏观", "行情", "驱动", "状态"])
    source = market or fallback_text
    lines = _to_bullets(source, max_items=8)
    lines = [x for x in lines if ("生成时间" not in x and "数据窗口" not in x)]
    lines = [x for x in lines if _is_relevant_market_state_line(x)]
    if len(lines) < 3:
        lines.extend(
            [
                "当前市场处于事件驱动与结构分化并存阶段，需重点观察主线持续性。",
                "资金对高流动性标的更敏感，长尾标的受情绪扰动更大。",
                "主要关注点在于资金净流向是否连续与快讯兑现节奏是否匹配。",
            ]
        )
    # 去重保持顺序
    uniq: list[str] = []
    seen: set[str] = set()
    for x in lines:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq[:4]


def _extract_actions(parsed: dict[str, str], fallback_text: str) -> list[str]:
    sec = _pick_section(parsed, ["执行摘要", "摘要", "结论", "建议", "动作", "策略"])
    source = sec or fallback_text
    cands = _to_bullets(source, max_items=8)
    actions = [
        x for x in cands if any(k in x for k in ["建议", "动作", "仓位", "控制", "关注", "观察", "提高", "降低", "止损", "风控"])
    ]
    if len(actions) < 3:
        actions = [
            "基线动作: 维持中性偏多，优先配置高流动性标的，控制事件仓位。",
            "触发动作: 若关注度与资金净流入同步提升，可逐步提高进攻仓位。",
            "防守动作: 若出现连续负面快讯并伴随成交萎缩，应主动降低风险暴露。",
        ]
    return actions[:4]


def _fallback_headlines(cleaned: str, max_items: int = 5) -> list[dict]:
    rows: list[dict] = []
    for line in cleaned.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        if s.startswith("-"):
            s = s[1:].strip()
        if len(s) < 12:
            continue
        rows.append({"title": s[:120], "url": "", "content": s})
        if len(rows) >= max_items:
            break
    return rows


def _tavily_search(query: str, api_key: str, max_results: int = 5, timeout_sec: int = 12) -> list[dict]:
    if not api_key.strip():
        return []
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key.strip(),
        "query": query,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
        "max_results": max(1, min(8, int(max_results))),
        "topic": "news",
    }
    try:
        resp = requests.post(url, json=payload, timeout=float(timeout_sec))
        if int(resp.status_code) >= 400:
            return []
        data = resp.json() if resp.text else {}
        rows = data.get("results")
        if not isinstance(rows, list):
            return []
        out: list[dict] = []
        for x in rows:
            if not isinstance(x, dict):
                continue
            out.append(
                {
                    "title": str(x.get("title") or "").strip(),
                    "url": str(x.get("url") or "").strip(),
                    "content": str(x.get("content") or "").strip(),
                }
            )
        return out
    except Exception:
        return []


def _extract_markdown_sections(content: str, level: int = 2) -> dict[str, str]:
    lines = str(content or "").replace("\r\n", "\n").split("\n")
    pat = re.compile(rf"^\s{{0,3}}#{{{level}}}(?!#)\s*(.+?)\s*$")
    idx: list[tuple[str, int]] = []
    for i, raw in enumerate(lines):
        m = pat.match(raw.strip())
        if m:
            idx.append((m.group(1).strip(), i))
    out: dict[str, str] = {}
    if not idx:
        return out
    for p, (name, start) in enumerate(idx):
        end = idx[p + 1][1] if p + 1 < len(idx) else len(lines)
        block = "\n".join(lines[start + 1 : end]).strip()
        out[name] = block
    return out


def _extract_news_categories(raw_content: str) -> dict[str, list[str]]:
    lines = str(raw_content or "").replace("\r\n", "\n").split("\n")
    h3: dict[str, list[str]] = {}
    in_news = False
    current_h3 = ""
    for raw in lines:
        s = raw.strip()
        h2 = re.match(r"^\s{0,3}##(?!#)\s*(.+?)\s*$", s)
        if h2:
            name = h2.group(1).strip()
            in_news = ("新闻事件影响分析" in name) or ("按事件类型分节" in name)
            current_h3 = ""
            continue
        if not in_news:
            continue
        m3 = re.match(r"^\s{0,3}###(?!#)\s*(.+?)\s*$", s)
        if m3:
            current_h3 = m3.group(1).strip()
            h3.setdefault(current_h3, [])
            continue
        if current_h3:
            h3[current_h3].append(raw.rstrip("\n"))
    # key mapping to keep old source categories
    mapping = [
        ("监管与政策", ["crypto_regulation", "监管", "政策"]),
        ("项目与技术", ["project_update", "项目", "技术"]),
        ("市场与交易", ["market_analysis", "市场", "交易"]),
        ("DeFi / NFT / 链上生态", ["defi", "nft", "链上", "生态"]),
    ]
    out: dict[str, list[str]] = {k: [] for k, _ in mapping}
    for sec_name, rows_block in h3.items():
        norm = sec_name.lower()
        bucket = None
        for label, keys in mapping:
            if any(k.lower() in norm for k in keys):
                bucket = label
                break
        if bucket is None:
            continue
        for row in rows_block:
            s = row.strip()
            if not s:
                continue
            if s.startswith("-"):
                s = s[1:].strip()
            if len(s) < 8:
                continue
            out[bucket].append(s)
    return out


def _extract_market_chart_items(raw_content: str) -> list[str]:
    h2 = _extract_markdown_sections(raw_content, level=2)
    target = ""
    for k, v in h2.items():
        if "市场状态诊断" in k:
            target = v
            break
    rows = _to_bullets(target, max_items=10)
    rows = [x for x in rows if ("|" not in x and not re.match(r"^-{3,}$", x.strip()))]
    rows = [x for x in rows if ("生成时间" not in x and "数据窗口" not in x)]
    return rows[:5]


def _extract_signal_and_risk(raw_content: str) -> tuple[list[str], list[str]]:
    h2 = _extract_markdown_sections(raw_content, level=2)
    h3 = _extract_markdown_sections(raw_content, level=3)
    signal = ""
    risk = ""
    for k, v in h2.items():
        if "信号汇总" in k:
            signal = v
        if "风险提示" in k:
            risk = v
    if not signal:
        for k, v in h3.items():
            if "信号汇总" in k:
                signal = v
                break
    signal_items = _signal_bullets_from_signal_block(signal)
    risk_items = _to_bullets(risk, max_items=8)
    return signal_items, risk_items


def _extract_watchlist(raw_content: str) -> list[str]:
    h2 = _extract_markdown_sections(raw_content, level=2)
    sec = ""
    for k, v in h2.items():
        if "观察清单" in k:
            sec = v
            break
    items = _to_bullets(sec, max_items=8)
    if not items:
        items = ["持续跟踪宏观政策窗口与链上流动性变化。"]
    return items


def _default_llm_cn(text: str) -> str:
    prompt = (
        "请将下面新闻标题改写为简洁中文标题，保留核心事实，不要增加结论，不要超过28字：\n"
        f"{text.strip()}"
    )
    model = str(os.environ.get("REPORT_TRANSFORM_LLM_MODEL") or "qwen2.5:7b-instruct").strip()
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    try:
        resp = requests.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=20)
        if int(resp.status_code) >= 400:
            return text
        data = resp.json() if resp.text else {}
        ans = str(data.get("response") or "").strip()
        ans = re.sub(r"^['\"“”]+|['\"“”]+$", "", ans).strip()
        if not ans:
            return text
        return ans
    except Exception:
        return text


def _guess_translate_terms(s: str) -> str:
    rep = {
        "SEC": "美国证监会",
        "ETF": "交易所交易基金",
        "FOMC": "美联储议息会议",
        "funding rate": "资金费率",
        "Funding rate": "资金费率",
        "open interest": "未平仓量",
        "Open interest": "未平仓量",
        "fear and greed": "恐惧与贪婪",
        "Fear and Greed": "恐惧与贪婪",
        "stablecoin": "稳定币",
        "Stablecoin": "稳定币",
        "Nasdaq": "纳斯达克",
        "S&P": "标普",
        "CPI": "通胀数据",
        "Bitcoin": "比特币",
        "Ethereum": "以太坊",
    }
    out = s
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


def _signal_bullets_from_signal_block(block: str) -> list[str]:
    text = str(block or "").strip()
    if not text:
        return []
    lines = [x.rstrip() for x in text.splitlines() if x.strip()]
    is_table = any(x.lstrip().startswith("|") for x in lines) and any("|" in x for x in lines)
    if not is_table:
        return _to_bullets(text, max_items=8)
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        s = raw.strip()
        if not s.startswith("|"):
            continue
        if "信号类型" in s:
            continue
        if set(re.sub(r"[^-]", "", s)) >= {"-"}:
            continue
        cols = [re.sub(r"[*_`]", "", x).strip() for x in s.strip("|").split("|")]
        cols = [x for x in cols if x]
        if len(cols) < 3:
            continue
        if len(cols) >= 4:
            name, val, thr, interp = cols[0], cols[1], cols[2], cols[3]
            item = f"{name}: {val}（阈值={thr}，解读={interp}）"
        else:
            name, val, interp = cols[0], cols[1], cols[2]
            item = f"{name}: {val}（解读={interp}）"
        item = _clean_line(item)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= 8:
            break
    return out


def _fetch_btc_indicators(days: int = 120) -> dict:
    try:
        if str(os.environ.get("REPORT_TRANSFORM_DISABLE_REMOTE") or "").strip() in {"1", "true", "yes"}:
            return {}
        closes: list[float] = []
        base_dir = Path(__file__).resolve().parents[1]
        local_path = base_dir / "historical_data" / "btc_daily_prices.json"
        if local_path.exists() and local_path.is_file():
            try:
                obj = json.loads(local_path.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    rows: list[tuple[str, float]] = []
                    for day, bar in obj.items():
                        if not isinstance(day, str):
                            continue
                        if not isinstance(bar, dict):
                            continue
                        px = bar.get("close")
                        try:
                            rows.append((day, float(px)))
                        except Exception:
                            continue
                    rows.sort(key=lambda x: x[0])
                    closes = [px for _, px in rows][-max(60, int(days)) :]
            except Exception:
                closes = []

        if len(closes) < 60:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
                params={"vs_currency": "usd", "days": int(days)},
                timeout=6,
            )
            if int(resp.status_code) >= 400:
                return {}
            data = resp.json() if resp.text else {}
            prices = data.get("prices")
            if not isinstance(prices, list) or len(prices) < 60:
                return {}
            by_day: dict[str, float] = {}
            for pair in prices:
                if not isinstance(pair, list) or len(pair) < 2:
                    continue
                ts_ms, px = pair[0], pair[1]
                try:
                    day = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
                    by_day[day] = float(px)
                except Exception:
                    continue
            days_sorted = sorted(by_day.keys())
            closes = [by_day[d] for d in days_sorted]
        if len(closes) < 60:
            return {}

        def sma(n: int) -> float | None:
            if len(closes) < n:
                return None
            w = closes[-n:]
            return sum(w) / float(n)

        def ema(series: list[float], n: int) -> list[float]:
            if not series:
                return []
            alpha = 2.0 / (n + 1.0)
            out = [series[0]]
            for x in series[1:]:
                out.append(alpha * x + (1.0 - alpha) * out[-1])
            return out

        def rsi14() -> float | None:
            n = 14
            if len(closes) < n + 1:
                return None
            gains = 0.0
            losses = 0.0
            for i in range(len(closes) - n, len(closes)):
                d = closes[i] - closes[i - 1]
                if d > 0:
                    gains += d
                elif d < 0:
                    losses += -d
            avg_gain = gains / n
            avg_loss = losses / n
            if avg_loss <= 1e-12:
                return 100.0
            rs = avg_gain / avg_loss
            return 100.0 - (100.0 / (1.0 + rs))

        px = closes[-1]
        ma20 = sma(20)
        ma50 = sma(50)
        ma100 = sma(100)
        ma200 = sma(200)
        rsi = rsi14()
        e12 = ema(closes, 12)
        e26 = ema(closes, 26)
        macd_len = min(len(e12), len(e26))
        macd_line = [e12[-macd_len + i] - e26[-macd_len + i] for i in range(macd_len)]
        sig = ema(macd_line, 9) if len(macd_line) >= 9 else []
        hist = (macd_line[-1] - sig[-1]) if (macd_line and sig) else None
        rets: list[float] = []
        for i in range(-21, -1):
            prev = closes[i - 1]
            cur = closes[i]
            if prev > 0:
                rets.append((cur / prev) - 1.0)
        vol20 = None
        if len(rets) >= 2:
            mean = sum(rets) / len(rets)
            var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
            vol20 = var ** 0.5
        abs_ret20 = (sum(abs(x) for x in rets) / len(rets)) if rets else None
        ret7 = None
        if len(closes) >= 8 and closes[-8] > 0:
            ret7 = (closes[-1] / closes[-8]) - 1.0
        ret30 = None
        if len(closes) >= 31 and closes[-31] > 0:
            ret30 = (closes[-1] / closes[-31]) - 1.0
        return {
            "price": px,
            "ma20": ma20,
            "ma50": ma50,
            "ma100": ma100,
            "ma200": ma200,
            "rsi14": rsi,
            "macd_hist": hist,
            "vol20": vol20,
            "ret7": ret7,
            "ret30": ret30,
            "abs_ret20": abs_ret20,
        }
    except Exception:
        return {}


def _normalize_cn_title(text: str, llm_fn: Callable[[str], str] | None = None) -> str:
    source = _clean_line(text)
    if not source:
        return ""
    fn = llm_fn or _default_llm_cn
    normalized = _clean_line(fn(source))
    if not normalized:
        normalized = source
    normalized = _guess_translate_terms(normalized)
    normalized = re.sub(r"https?://\S+", "", normalized).strip()
    normalized = re.sub(r"[A-Za-z]{2,}", "", normalized).strip()
    normalized = re.sub(r"\s{2,}", " ", normalized).strip(" -:：")
    return normalized or source


def _classify_sentiment(headlines: list[dict]) -> tuple[list[str], list[str]]:
    pos_kw = ["获批", "增持", "上涨", "突破", "流入", "合作", "adoption", "inflow", "upgrade", "approval"]
    neg_kw = ["下跌", "减持", "清算", "漏洞", "攻击", "监管收紧", "outflow", "hack", "exploit", "ban", "lawsuit"]
    bull: list[str] = []
    bear: list[str] = []
    for row in headlines:
        text = f"{row.get('title','')} {row.get('content','')}".lower()
        if any(k.lower() in text for k in pos_kw):
            bull.append(str(row.get("title") or "").strip())
        if any(k.lower() in text for k in neg_kw):
            bear.append(str(row.get("title") or "").strip())
    if not bull:
        bull = ["主线资产流动性改善且资金关注度回升。"]
    if not bear:
        bear = ["若市场成交深度下降，短线波动可能放大。"]
    return bull[:3], bear[:3]


def _is_relevant_watch_event(text: str) -> bool:
    s = _clean_line(text).lower()
    if not s:
        return False
    s_compact = re.sub(r"[\s\-\—_,，。:：;；()（）\[\]{}<>|]+", "", s)
    if s_compact in {"btc", "eth", "bitcoin", "ethereum", "比特币", "以太坊"}:
        return False
    reject_kw = [
        "price prediction",
        "target",
        "presale",
        "pre-sale",
        "meme",
        "dogecoin",
        "shib",
        "pepe",
        "airdrop",
        "launchpad",
        "stage",
        "x100",
        "x50",
        "moon",
        "pump",
        "memecoin",
        "价格预测",
        "目标价",
        "预售",
        "空投",
        "拉盘",
        "梭哈",
        "狗狗币",
        "土狗",
        "喊单",
    ]
    if any(k in s for k in reject_kw):
        return False
    context_kw = [
        "etf",
        "funding",
        "资金费率",
        "open interest",
        "未平仓",
        "liquidation",
        "清算",
        "stablecoin",
        "稳定币",
        "usdt",
        "usdc",
        "sec",
        "监管",
        "policy",
        "政策",
        "lawsuit",
        "诉讼",
        "hack",
        "exploit",
        "漏洞",
        "攻击",
        "exchange",
        "交易所",
        "withdraw",
        "deposit",
        "暂停",
        "宕机",
        "macro",
        "cpi",
        "pce",
        "nonfarm",
        "fomc",
        "fed",
        "美联储",
        "利率",
        "dxy",
        "美元指数",
        "treasury",
        "yield",
        "国债",
        "收益率",
    ]
    if any(k in s for k in ["stablecoin", "稳定币", "usdt", "usdc"]):
        return True
    if any(k in s for k in ["macro", "cpi", "pce", "nonfarm", "fomc", "fed", "美联储", "利率", "dxy", "美元指数", "treasury", "yield", "国债", "收益率"]):
        return True
    if any(k in s for k in ["sec", "监管", "policy", "政策", "lawsuit", "诉讼"]):
        return True
    if any(k in s for k in ["hack", "exploit", "漏洞", "攻击", "exchange", "交易所", "withdraw", "deposit", "暂停", "宕机"]):
        return True
    if any(k in s for k in ["funding", "资金费率", "open interest", "未平仓", "liquidation", "清算", "etf"]):
        return True
    base_asset_kw = ["btc", "bitcoin", "比特币", "eth", "ethereum", "以太坊"]
    if any(k in s for k in base_asset_kw) and any(k in s for k in context_kw):
        return True
    return False


def _is_placeholder_text(text: str) -> bool:
    t = _clean_line(text)
    low = t.lower()
    if not t:
        return True
    if low in {"暂无", "tbd", "待补充"}:
        return True
    if t.startswith("暂无") and any(k in t for k in ["可用", "数据", "条目", "高置信度", "更新", "事件", "信号", "内容"]):
        return True
    return False


def _source_label_from_url(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    m = re.match(r"^https?://([^/]+)", u)
    host = (m.group(1) if m else "").lower().strip()
    host = host.split(":")[0].strip()
    if not host:
        return ""
    if host.endswith("coindesk.com"):
        return "CoinDesk"
    if host.endswith("theblockbeats.info"):
        return "BlockBeats"
    if host.endswith("odaily.news"):
        return "Odaily"
    if host.endswith("cointelegraph.com"):
        return "Cointelegraph"
    if host.endswith("reuters.com"):
        return "Reuters"
    if host.endswith("cnbc.com"):
        return "CNBC"
    if host.endswith("wallstreetcn.com"):
        return "华尔街见闻"
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _extract_source_events(raw_content: str) -> list[dict]:
    text = str(raw_content or "").replace("\r\n", "\n")
    rows: list[dict] = []

    for line in text.split("\n"):
        s = line.strip()
        m = re.match(r"^\s*\d+\.\s+\*\*\[(.+?)\]\*\*.*?（(https?://[^，)\s]+)", s)
        if not m:
            continue
        title = _clean_line(m.group(1))
        url = _clean_line(m.group(2))
        if not title:
            continue
        rows.append({"title": title, "url": url, "source": _source_label_from_url(url), "kind": "highlight"})

    in_types = False
    for line in text.split("\n"):
        s = line.strip()
        if re.match(r"^\s{0,3}##\s+.*按事件类型分节.*$", s):
            in_types = True
            continue
        if in_types and re.match(r"^\s{0,3}##\s+.*$", s) and "按事件类型分节" not in s:
            in_types = False
        if not in_types:
            continue
        m = re.match(r"^\s*-\s*(.+?)（(https?://[^，)\s]+)", s)
        if not m:
            continue
        title = _clean_line(m.group(1))
        url = _clean_line(m.group(2))
        if not title:
            continue
        rows.append({"title": title, "url": url, "source": _source_label_from_url(url), "kind": "typed"})

    # dedup by title
    out: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        t = str(r.get("title") or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(r)
    return out


def _is_relevant_news_item(text: str, url: str = "") -> bool:
    s = _clean_line(text)
    low = s.lower()
    if not s:
        return False
    reject_kw = [
        "钠电",
        "锂电",
        "机器人",
        "宁德时代",
        "提出建议",
        "——",
        "price prediction",
        "presale",
        "meme",
        "dogecoin",
        "shib",
        "pepe",
        "memecoin",
    ]
    if any(k.lower() in low for k in reject_kw):
        return False
    src = _source_label_from_url(url)
    if src in {"CoinDesk", "BlockBeats", "Odaily", "Cointelegraph", "Reuters", "CNBC", "华尔街见闻"}:
        return True
    allow_kw = [
        "btc",
        "bitcoin",
        "比特币",
        "eth",
        "ethereum",
        "以太坊",
        "美联储",
        "fomc",
        "cpi",
        "pce",
        "伊朗",
        "地缘",
        "谈判",
        "稳定币",
        "stablecoin",
        "etf",
        "sec",
        "监管",
        "交易所",
        "binance",
        "okx",
        "coinbase",
        "funding",
        "资金费率",
        "open interest",
        "未平仓",
        "清算",
        "liquidation",
        "hack",
        "exploit",
        "漏洞",
        "攻击",
        "defi",
        "nft",
        "layer2",
        "rollup",
        "gas",
    ]
    return any(k in low for k in allow_kw) or any(k in s for k in allow_kw)


def _format_with_source(title: str, url: str = "") -> str:
    t = _clean_line(title)
    src = _source_label_from_url(url)
    if not t:
        return ""
    if not src:
        return t
    return f"{t}（来源={src}）"


def _extract_btc_numbers_from_source(raw_content: str) -> dict:
    text = str(raw_content or "").replace("\r\n", "\n")
    out: dict[str, float] = {}
    m_px = re.search(r"BTC\s*当前价[^$0-9]*\$?\s*([0-9][0-9,]*)", text, flags=re.IGNORECASE)
    if m_px:
        try:
            out["price"] = float(m_px.group(1).replace(",", ""))
        except Exception:
            pass
    m_ma20 = re.search(r"MA20\([^)]*\)\s*\|\s*\$?\s*([0-9][0-9,]*)", text, flags=re.IGNORECASE)
    if m_ma20:
        try:
            out["ma20"] = float(m_ma20.group(1).replace(",", ""))
        except Exception:
            pass
    return out


def _contains_disallowed_coin_token(text: str) -> bool:
    s = str(text or "")
    s2 = s.replace("，", ",").replace("（", "(").replace("）", ")")
    allow = {"BTC", "ETH", "USDT", "USDC", "USD", "EUR", "DXY", "CPI", "PCE", "FOMC", "FED"}

    pairs = re.findall(r"\b([A-Z0-9]{2,10})/(BTC|ETH)\b", s2.upper())
    for base, quote in pairs:
        if base not in allow and base not in {"BTC", "ETH"}:
            return True

    tickers = set(re.findall(r"\b[A-Z0-9]{2,10}\b", s2.upper()))
    disallowed = {t for t in tickers if t not in allow and t not in {"BTC", "ETH"}}
    if disallowed:
        if any(k in s2.lower() for k in ["binance", "okx", "coinbase", "交易所", "上线", "下架", "移除", "listing", "delist"]):
            return True
    return False


def _core_impact_dimension(title: str) -> str:
    t = _clean_line(title)
    low = t.lower()
    if not t:
        return ""
    if _contains_disallowed_coin_token(t):
        return ""
    if any(k in t for k in ["伊朗", "巴基斯坦", "停火", "谈判", "地缘", "制裁", "冲突", "战争"]):
        return "地缘政治"
    if ("stablecoin" in low) or ("稳定币" in t):
        return "政策监管"
    if any(k in low for k in ["sec", "regulation", "policy"]) or any(k in t for k in ["监管", "政策", "立法", "执法", "听证会", "制裁"]):
        return "政策监管"
    if any(k in low for k in ["fomc", "fed", "rate cut", "rate hike"]) or any(k in t for k in ["美联储", "鲍威尔", "降息", "加息", "议息"]):
        return "美联储动态"
    if any(k in low for k in ["etf", "inflow", "outflow", "institution"]) or any(k in t for k in ["ETF", "净流入", "净流出", "机构", "基金", "Strategy", "贝莱德", "BlackRock"]):
        return "机构资金流入"
    if any(k in low for k in ["whale", "transfer"]) or any(k in t for k in ["巨鲸", "大额转账", "转移", "派盾", "PeckShield"]):
        return "巨鲸转账"
    if any(k in low for k in ["upgrade", "hardfork", "protocol", "layer2", "rollup"]) or any(k in t for k in ["协议", "升级", "硬分叉", "EIP", "安全漏洞", "攻击", "修复", "Layer2", "Rollup", "链上"]):
        return "重要技术进展"
    return ""


def transform_daily_report_v3(
    raw_content: str,
    title: str,
    tavily_api_key: str = "",
    max_headlines: int = 6,
    max_events: int = 6,
    search_fn: Callable[[str, int], list[dict]] | None = None,
    llm_fn: Callable[[str], str] | None = None,
) -> dict:
    cleaned = _strip_noise(raw_content)
    parsed = _split_sections(cleaned)
    actions = _extract_actions(parsed, cleaned)
    market_state = _extract_market_state(parsed, cleaned)

    # Keep charts/signal/risk/watchlist from source outputs
    chart_items = _extract_market_chart_items(raw_content)
    h2_blocks = _extract_markdown_sections(raw_content, level=2)
    h3_blocks = _extract_markdown_sections(raw_content, level=3)
    raw_signal_block = ""
    for k, v in h2_blocks.items():
        if "信号汇总" in k:
            raw_signal_block = v or ""
            break
    if not raw_signal_block:
        for k, v in h3_blocks.items():
            if "信号汇总" in k:
                raw_signal_block = v or ""
                break
    signal_table_present = ("信号类型" in raw_signal_block) and ("|" in raw_signal_block)
    signal_items, risk_items = _extract_signal_and_risk(raw_content)
    watch_items = _extract_watchlist(raw_content)
    watch_items = [_normalize_cn_title(x, llm_fn=llm_fn) for x in watch_items if str(x or "").strip()]
    watch_filtered = [x for x in watch_items if _is_relevant_watch_event(x)]
    watch_filtered_out = max(0, len(watch_items) - len(watch_filtered))
    if not watch_filtered:
        watch_filtered = ["未发现与BTC/ETH/宏观直接相关的高置信度事件（仅监控FOMC/CPI/监管与交易所状态）。"]
    watch_items = watch_filtered[:max_events]

    source_events = _extract_source_events(raw_content)
    btc_src = _extract_btc_numbers_from_source(raw_content)
    source_title_to_url: dict[str, str] = {}
    for r in source_events:
        t0 = str(r.get("title") or "").strip()
        u = str(r.get("url") or "").strip()
        if t0 and u and t0 not in source_title_to_url:
            source_title_to_url[t0] = u
        t1 = _normalize_cn_title(t0, llm_fn=llm_fn) if t0 else ""
        if t1 and u and t1 not in source_title_to_url:
            source_title_to_url[t1] = u

    def _lookup_url(title_text: str) -> str:
        t = str(title_text or "").strip()
        if not t:
            return ""
        if t in source_title_to_url:
            return source_title_to_url[t]
        t2 = _normalize_cn_title(t, llm_fn=llm_fn)
        return source_title_to_url.get(t2, "")

    source_categories = _extract_news_categories(raw_content)
    tavily_used = False
    source_urls: list[str] = []
    tavily_signal_fill_n = 0
    if search_fn is None:
        def _default_search(q: str, n: int) -> list[dict]:
            return _tavily_search(q, tavily_api_key, max_results=n)
        search_fn = _default_search

    news_rows = search_fn("crypto market breaking news last 24 hours", max_headlines) if tavily_api_key.strip() else []
    event_rows = search_fn("upcoming crypto events next 72 hours", max_events) if tavily_api_key.strip() else []
    if news_rows or event_rows:
        tavily_used = True

    if len(signal_items) < 5 and tavily_api_key.strip():
        need = max(0, 6 - len(signal_items))
        fill_rows = search_fn(
            "BTC funding rate open interest fear and greed index exchange netflow today",
            max(3, min(8, need)),
        )
        seen_sig: set[str] = set(signal_items)
        for row in fill_rows:
            title_raw = str(row.get("title") or row.get("content") or "").strip()
            if not title_raw:
                continue
            item = _normalize_cn_title(title_raw, llm_fn=llm_fn)
            if not item or item in seen_sig:
                continue
            seen_sig.add(item)
            signal_items.append(item)
            tavily_signal_fill_n += 1
            u = str(row.get("url") or "").strip()
            if u and u not in source_urls:
                source_urls.append(u)
        if tavily_signal_fill_n > 0:
            tavily_used = True

    # Merge source categories first; Tavily as补齐
    cat_rows: dict[str, list[str]] = {
        "宏观与地缘": [],
        "监管与政策": list(source_categories.get("监管与政策", [])),
        "项目与技术": list(source_categories.get("项目与技术", [])),
        "市场与交易": list(source_categories.get("市场与交易", [])),
        "DeFi / NFT / 链上生态": list(source_categories.get("DeFi / NFT / 链上生态", [])),
    }
    for x in watch_items:
        t = _normalize_cn_title(x, llm_fn=llm_fn)
        if not t or _is_placeholder_text(t):
            continue
        dim = _core_impact_dimension(t)
        if dim in {"地缘政治", "美联储动态"}:
            cat_rows["宏观与地缘"].append(t)
        elif dim in {"政策监管"}:
            cat_rows["监管与政策"].append(t)
        elif dim in {"机构资金流入"}:
            cat_rows["市场与交易"].append(t)
        elif dim in {"巨鲸转账"}:
            cat_rows["DeFi / NFT / 链上生态"].append(t)
        elif dim in {"重要技术进展"}:
            cat_rows["项目与技术"].append(t)
    for r in source_events[:20]:
        t = str(r.get("title") or "").strip()
        u = str(r.get("url") or "").strip()
        if not t or not _is_relevant_news_item(t, url=u):
            continue
        dim = _core_impact_dimension(t)
        if dim in {"地缘政治", "美联储动态"}:
            cat_rows["宏观与地缘"].append(_format_with_source(t, u))
        elif dim in {"政策监管"}:
            cat_rows["监管与政策"].append(_format_with_source(t, u))
        elif dim in {"机构资金流入"}:
            cat_rows["市场与交易"].append(_format_with_source(t, u))
        elif dim in {"巨鲸转账"}:
            cat_rows["DeFi / NFT / 链上生态"].append(_format_with_source(t, u))
        elif dim in {"重要技术进展"}:
            cat_rows["项目与技术"].append(_format_with_source(t, u))
    for row in news_rows:
        title_raw = str(row.get("title") or row.get("content") or "").strip()
        if not title_raw:
            continue
        # heuristics for category
        low = f"{title_raw} {row.get('content','')}".lower()
        if any(k in low for k in ["sec", "regulation", "policy", "监管", "政策"]):
            target = "监管与政策"
        elif any(k in low for k in ["protocol", "upgrade", "项目", "技术", "开发"]):
            target = "项目与技术"
        elif any(k in low for k in ["market", "price", "etf", "inflow", "交易", "行情"]):
            target = "市场与交易"
        else:
            target = "DeFi / NFT / 链上生态"
        if _is_relevant_news_item(title_raw, url=str(row.get("url") or "")):
            cat_rows[target].append(title_raw)
        u = str(row.get("url") or "").strip()
        if u and u not in source_urls:
            source_urls.append(u)

    def _dedup(items: list[str], n: int) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for x in items:
            s = _normalize_cn_title(x, llm_fn=llm_fn)
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
            if len(out) >= n:
                break
        return out

    cat_rows = {k: [x for x in _dedup(v, 6) if _is_relevant_news_item(x)] for k, v in cat_rows.items()}

    btc_ind = _fetch_btc_indicators()
    if btc_src.get("price") and isinstance(btc_ind, dict) and isinstance(btc_ind.get("price"), (int, float)):
        try:
            src_px = float(btc_src["price"])
            ind_px = float(btc_ind.get("price"))
            if ind_px > 0 and abs(src_px / ind_px - 1.0) > 0.02:
                btc_ind = {}
        except Exception:
            btc_ind = {}
    if btc_ind:
        ind_lines = [
            f"BTC 现价: ${btc_ind.get('price'):.0f}" if btc_ind.get("price") is not None else "",
            f"MA20: ${btc_ind.get('ma20'):.0f}" if btc_ind.get("ma20") is not None else "",
            f"MA50: ${btc_ind.get('ma50'):.0f}" if btc_ind.get("ma50") is not None else "",
            f"MA100: ${btc_ind.get('ma100'):.0f}" if btc_ind.get("ma100") is not None else "",
            f"MA200: ${btc_ind.get('ma200'):.0f}" if btc_ind.get("ma200") is not None else "",
            f"RSI(14): {btc_ind.get('rsi14'):.1f}" if btc_ind.get("rsi14") is not None else "",
            f"MACD 柱状: {'向上' if (btc_ind.get('macd_hist') or 0) > 0 else '向下'}" if btc_ind.get("macd_hist") is not None else "",
            f"20日波动率(近似): {btc_ind.get('vol20'):.2%}" if btc_ind.get("vol20") is not None else "",
            f"20日平均涨跌幅(绝对值): {btc_ind.get('abs_ret20'):.2%}" if btc_ind.get("abs_ret20") is not None else "",
            f"7日涨跌幅: {btc_ind.get('ret7'):.2%}" if btc_ind.get("ret7") is not None else "",
            f"30日涨跌幅: {btc_ind.get('ret30'):.2%}" if btc_ind.get("ret30") is not None else "",
        ]
        ind_lines = [x for x in ind_lines if x]
        chart_items = [x for x in chart_items if x] + ind_lines

    if (not chart_items) and (btc_src.get("price") is not None or btc_src.get("ma20") is not None):
        chart_items = []
        if btc_src.get("price") is not None:
            chart_items.append(f"BTC 当前价(主源): ${float(btc_src['price']):.0f}")
        if btc_src.get("ma20") is not None:
            chart_items.append(f"MA20(主源): ${float(btc_src['ma20']):.0f}")
    if not chart_items:
        chart_items = ["市场状态图表缺失，建议检查源文件产物完整性。"]
    if not signal_items:
        signal_items = ["当前信号偏中性，等待资金与热度同向确认。"]
    if not risk_items:
        risk_items = ["潜在影响事件: 宏观政策窗口与突发监管消息。"]

    moved_to_news: list[str] = []
    for x in risk_items:
        t = _normalize_cn_title(x, llm_fn=llm_fn)
        if not t:
            continue
        if _core_impact_dimension(t) and _is_relevant_news_item(t, url=_lookup_url(t)):
            moved_to_news.append(t)
    for t in moved_to_news[:6]:
        dim = _core_impact_dimension(t)
        u = _lookup_url(t)
        if dim in {"地缘政治", "美联储动态"}:
            cat_rows["宏观与地缘"].append(_format_with_source(t, u))
        elif dim in {"政策监管"}:
            cat_rows["监管与政策"].append(_format_with_source(t, u))
        elif dim in {"机构资金流入"}:
            cat_rows["市场与交易"].append(_format_with_source(t, u))
        elif dim in {"巨鲸转账"}:
            cat_rows["DeFi / NFT / 链上生态"].append(_format_with_source(t, u))
        elif dim in {"重要技术进展"}:
            cat_rows["项目与技术"].append(_format_with_source(t, u))

    risk_events = [x for x in risk_items if (x not in moved_to_news) and any(k in x for k in ["监管", "宏观", "地缘", "波动", "流动性", "风险"])]
    risk_events = [_normalize_cn_title(x, llm_fn=llm_fn) for x in risk_events]
    risk_events = [x for x in risk_events if x and len(x) >= 6][:3]
    if not risk_events:
        risk_events = ["风险聚焦: 宏观政策窗口与突发监管口径变化，叠加流动性走弱会放大短线波动。"]

    event_lines = [str(x.get("title") or x.get("content") or "").strip() for x in event_rows]
    event_lines = [_normalize_cn_title(x, llm_fn=llm_fn) for x in event_lines if x.strip()]
    event_lines = [x for x in event_lines if x and x not in {",", "，"} and len(x) >= 6]
    event_filtered_out = 0
    filtered: list[str] = []
    for x in event_lines:
        if _is_relevant_watch_event(x):
            filtered.append(x)
        else:
            event_filtered_out += 1
    event_lines = filtered[:max_events]
    if not event_lines:
        event_lines = watch_items[:max_events]

    pos_kw = ["获批", "增持", "上涨", "突破", "流入", "合作", "adoption", "inflow", "upgrade", "approval", "net inflow"]
    neg_kw = ["下跌", "减持", "清算", "漏洞", "攻击", "监管收紧", "outflow", "hack", "exploit", "ban", "lawsuit", "liquidation"]
    bull_news: list[str] = []
    bear_news: list[str] = []
    for row in (source_events[:20] + [{"title": str(x.get("title") or ""), "url": str(x.get("url") or "")} for x in news_rows]):
        t = _clean_line(str(row.get("title") or ""))
        u = str(row.get("url") or "").strip()
        if not t or not _is_relevant_news_item(t, url=u):
            continue
        text_low = f"{t} {row.get('content','')}".lower()
        if any(k.lower() in text_low for k in pos_kw):
            bull_news.append(_format_with_source(t, u))
        if any(k.lower() in text_low for k in neg_kw):
            bear_news.append(_format_with_source(t, u))
    if not bull_news:
        bull_news = ["暂无明确利多催化（以资金与事件验证为准）"]
    if not bear_news:
        bear_news = ["暂无明确利空催化（以风险与清算验证为准）"]
    bull_news = list(dict.fromkeys(bull_news))[:3]
    bear_news = list(dict.fromkeys(bear_news))[:3]

    now_cst = datetime.now(timezone(timedelta(hours=8)))
    date_txt = now_cst.strftime("%Y-%m-%d")
    public_title = f"{title}｜日报｜{date_txt}｜BTC/ETH/宏观｜V3"
    update_points = [
        f"市场状态: {(_normalize_cn_title(chart_items[0], llm_fn=llm_fn) if chart_items else '状态待确认')}",
        f"信号: {(_normalize_cn_title(signal_items[0], llm_fn=llm_fn) if signal_items else '信号待确认')}",
        f"风险: {(_normalize_cn_title(risk_events[0], llm_fn=llm_fn) if risk_events else '风险待确认')}",
    ]
    applicability = [
        "适用周期: T+0 ~ T+3（短线事件驱动为主）",
        "适用市场: 现货为主，合约需严格风控",
        "适用风险偏好: 均衡型（激进请降低仓位/提高止损纪律）",
    ]
    driver_candidates: list[dict] = []
    for r in source_events[:12]:
        t = str(r.get("title") or "").strip()
        u = str(r.get("url") or "").strip()
        if not t:
            continue
        dim = _core_impact_dimension(t)
        if not dim:
            continue
        driver_candidates.append({"title": t, "url": u, "dimension": dim})

    def _driver_priority(t: str) -> tuple[int, str, str]:
        low = t.lower()
        if any(k in low for k in ["btc", "bitcoin", "比特币", "etf", "inflow", "净流入", "资金", "成交", "清算"]):
            return 0, "P0", "Medium"
        if any(k in low for k in ["sec", "监管", "policy", "stablecoin", "稳定币", "诉讼"]):
            return 1, "P1", "Medium"
        if any(k in low for k in ["fomc", "fed", "美联储", "cpi", "pce", "伊朗", "地缘", "战争", "谈判"]):
            return 2, "P2", "Low"
        return 3, "P2", "Low"

    driver_candidates.sort(key=lambda x: _driver_priority(str(x.get("title") or ""))[0])
    top_drivers = [
        {"p": "P0", "topic": "BTC 主线资金与流动性", "confidence": "Medium"},
        {"p": "P1", "topic": "监管与政策预期变化", "confidence": "Medium"},
        {"p": "P2", "topic": "宏观与地缘事件扰动", "confidence": "Low"},
    ]
    mainline = "主线=BTC；驱动=资金/流动性；验证=成交深度与资金连续性；失效=关键位失守并放量下跌"
    px = (btc_src.get("price") if btc_src.get("price") is not None else (btc_ind.get("price") if isinstance(btc_ind, dict) else None))
    ma20 = (btc_src.get("ma20") if btc_src.get("ma20") is not None else (btc_ind.get("ma20") if isinstance(btc_ind, dict) else None))
    ma50 = (btc_ind.get("ma50") if isinstance(btc_ind, dict) else None)
    rsi = btc_ind.get("rsi14") if isinstance(btc_ind, dict) else None
    macd_hist = btc_ind.get("macd_hist") if isinstance(btc_ind, dict) else None
    pct20 = None if (not isinstance(px, (int, float)) or not isinstance(ma20, (int, float)) or ma20 == 0) else (float(px) / float(ma20) - 1.0)
    pct50 = None if (not isinstance(px, (int, float)) or not isinstance(ma50, (int, float)) or ma50 == 0) else (float(px) / float(ma50) - 1.0)
    trend = "偏强" if (isinstance(pct20, float) and pct20 > 0 and isinstance(pct50, float) and pct50 > 0) else "偏弱/震荡"
    mom = "向上" if (isinstance(macd_hist, (int, float)) and macd_hist > 0) else "偏弱"
    btc_extension = []
    if isinstance(px, (int, float)) and isinstance(ma20, (int, float)):
        if isinstance(ma50, (int, float)):
            btc_extension.append(f"趋势: BTC=${px:.0f}，较MA20 {pct20:.2%}、较MA50 {pct50:.2%}，判断={trend}。")
        else:
            btc_extension.append(f"趋势: BTC=${px:.0f}，较MA20 {pct20:.2%}，判断={trend}。")
    if rsi is not None:
        btc_extension.append(f"动能: RSI(14)={float(rsi):.1f}，MACD柱状={mom}，短线动能与趋势一致性需结合成交验证。")
    if top_drivers:
        btc_extension.append(f"事件: {top_drivers[0]['topic']}，需要用资金与关键位去验证是否能转化为趋势延续。")
    while len(btc_extension) < 3:
        btc_extension.append("风控: 若出现放量回撤+清算上升，应主动降低杠杆并收缩事件仓位。")
    hot_events = []
    for d in driver_candidates[:5]:
        t = str(d.get("title") or "").strip()
        u = str(d.get("url") or "").strip()
        if not t:
            continue
        hot_events.append({"title": _format_with_source(t, u), "direction": "中性", "horizon": "24-72h"})
    if not hot_events:
        hot_events = [{"title": "宏观数据/监管动态/安全事件监控", "direction": "中性", "horizon": "24-72h"}]
    core_impact_lines = [
        f"- {_format_with_source(d['title'], d.get('url',''))}"
        for d in (driver_candidates[:3] or [])
        if str(d.get("title") or "").strip()
    ]
    if not core_impact_lines:
        core_impact_lines = ["- 未发现符合六维度的主源核心事件（已过滤非BTC/ETH/稳定币相关条目）。"]
    indicator_analysis: list[str] = []
    if isinstance(px, (int, float)) and isinstance(ma20, (int, float)) and isinstance(pct20, float):
        indicator_analysis.append(f"均线偏离: BTC 相对 MA20 偏离 {pct20:.2%}（用于判断趋势强弱与回撤空间）。")
    if isinstance(btc_ind, dict) and btc_ind.get("ma100") is not None and btc_ind.get("ma200") is not None:
        ma50v = btc_ind.get("ma50")
        ma100v = btc_ind.get("ma100")
        ma200v = btc_ind.get("ma200")
        if isinstance(ma50v, (int, float)) and isinstance(ma100v, (int, float)) and isinstance(ma200v, (int, float)):
            indicator_analysis.append(f"均线结构: MA50/MA100/MA200={ma50v:.0f}/{ma100v:.0f}/{ma200v:.0f}（用于判断中期趋势与支撑带）。")
    if rsi is not None:
        indicator_analysis.append(f"动能: RSI(14)={float(rsi):.1f}，MACD柱状={mom}（用于判断短线动能是否衰竭/延续）。")
    if isinstance(btc_ind, dict) and btc_ind.get("vol20") is not None:
        try:
            indicator_analysis.append(f"波动: 20日波动率≈{float(btc_ind.get('vol20')):.2%}（用于设置仓位与止损宽度）。")
        except Exception:
            pass
    if isinstance(btc_ind, dict) and btc_ind.get("ret7") is not None:
        try:
            indicator_analysis.append(f"收益: 7日涨跌幅 {float(btc_ind.get('ret7')):.2%}（用于判断趋势是否扩散）。")
        except Exception:
            pass
    if isinstance(btc_ind, dict) and btc_ind.get("ret30") is not None:
        try:
            indicator_analysis.append(f"收益: 30日涨跌幅 {float(btc_ind.get('ret30')):.2%}（用于判断中期方向）。")
        except Exception:
            pass
    if not indicator_analysis:
        indicator_analysis = ["指标补充不足: 仅保留主源图表与信号表，不对指标做过度推断。"]
    md = "\n".join(
        [
            f"# {public_title}",
            "",
            "## 本期更新点",
            *[f"- {x}" for x in update_points],
            "",
            "## 适用说明",
            *[f"- {x}" for x in applicability],
            "",
            "## 一、执行摘要（今日建议动作）",
            "### Top 3 驱动（P0/P1/P2）",
            *[f"- {d['p']}: {d['topic']}（置信度={d['confidence']}）" for d in top_drivers],
            "",
            *[f"- {x}" for x in actions[:4]],
            "### 核心影响事件（主源）",
            *core_impact_lines,
            "",
            "## 二、市场状态与主要矛盾",
            f"- {mainline}",
            *[f"- {x}" for x in market_state[:4]],
            "",
            "### 2.0 以 BTC 为分析标的（说人话）",
            *[f"- {x}" for x in btc_extension],
            "",
            "### 2.1 市场状态诊断图表（保留）",
            *[f"- {x}" for x in chart_items[:8]],
            "",
            "### 2.2 热门事件（需重点关注）",
            *[f"- {e['title']}（方向={e['direction']}，时点={e['horizon']}）" for e in hot_events],
            "",
            "### 2.3 技术指标与解读",
            *[f"- {x}" for x in indicator_analysis[:6]],
            "",
            "## 三、重点新闻与分类解读（中文）",
            "### 3.0 宏观与地缘",
            *[
                f"- {x}"
                for x in (
                    cat_rows.get("宏观与地缘")
                    or ["未检索到高置信度条目，建议关注FOMC/CPI与地缘突发事件。"]
                )
            ],
            "",
            "### 3.1 监管与政策",
            *[
                f"- {x}"
                for x in (
                    cat_rows.get("监管与政策")
                    or ["未检索到高置信度条目，建议关注监管口径与执法动态。"]
                )
            ],
            "",
            "### 3.2 项目与技术",
            *[
                f"- {x}"
                for x in (
                    cat_rows.get("项目与技术")
                    or ["未检索到高置信度条目，建议关注头部项目升级/漏洞/治理投票。"]
                )
            ],
            "",
            "### 3.3 市场与交易",
            *[
                f"- {x}"
                for x in (
                    cat_rows.get("市场与交易")
                    or ["未检索到高置信度条目，建议关注成交、资金流与关键价位。"]
                )
            ],
            "",
            "### 3.4 DeFi / NFT / 链上生态",
            *[
                f"- {x}"
                for x in (
                    cat_rows.get("DeFi / NFT / 链上生态")
                    or ["未检索到高置信度条目，建议关注链上资金迁移与安全事件。"]
                )
            ],
            "",
            "## 四、信号汇总与风险提示（保留）",
            "### 4.1 多空新闻（24h）",
            "- 利多:",
            *[f"  - {x}" for x in bull_news],
            "- 利空:",
            *[f"  - {x}" for x in bear_news],
            "### 4.2 信号汇总",
            *[f"- {x}" for x in signal_items[:5]],
            "### 4.3 风险提示（潜在影响事件）",
            *[f"- {_format_with_source(x, _lookup_url(x))}" for x in risk_events[:5]],
            "",
            "",
        ]
    ).strip() + "\n"

    summary = _summary_from_bullets(actions, limit=220)
    banned_pat = re.compile(
        r"(保证收益|稳赚|无风险|价格必到|必然(?:上涨|下跌|盈利|赚钱|收益)|确定(?:上涨|下跌|盈利|赚钱|收益))"
    )
    low_info = ["晨讯:动态", "新闻报道"]
    qa_fail_reasons: list[str] = []
    qa_score = 100
    diff_audit: list[dict] = []
    diff_audit.append({"type": "apply_sellside_header", "detail": "added title/update/applicability/top3"})
    if signal_table_present:
        diff_audit.append({"type": "signal_table_normalized", "detail": "converted markdown table rows to bullet statements"})
    if tavily_signal_fill_n > 0:
        diff_audit.append({"type": "tavily_signal_fill", "detail": f"filled_missing_signal_items={tavily_signal_fill_n}"})
    if tavily_api_key.strip() and event_filtered_out > 0:
        diff_audit.append({"type": "tavily_event_filter", "detail": f"filtered_irrelevant_events={event_filtered_out}"})
    if watch_filtered_out > 0:
        diff_audit.append({"type": "watchlist_filter", "detail": f"filtered_low_quality_watch_items={watch_filtered_out}"})
    if banned_pat.search(md):
        qa_fail_reasons.append("命中禁语")
        qa_score -= 40
    h2_blocks = _extract_markdown_sections(raw_content, level=2)
    h3_blocks = _extract_markdown_sections(raw_content, level=3)
    required_hits = {
        "市场状态诊断": any("市场状态诊断" in k for k in h2_blocks.keys()),
        "信号汇总": any("信号汇总" in k for k in list(h2_blocks.keys()) + list(h3_blocks.keys())),
        "风险提示": any("风险提示" in k for k in list(h2_blocks.keys()) + list(h3_blocks.keys())),
        "观察清单": any(("观察清单" in k) or ("明日观察清单" in k) for k in list(h2_blocks.keys()) + list(h3_blocks.keys())),
    }
    missing_required = [k for k, ok in required_hits.items() if not ok]
    if missing_required:
        qa_fail_reasons.append(f"源文件关键章节缺失:{'/'.join(missing_required)}")
        qa_score -= 60
    core_items = list(signal_items or []) + list(risk_items or []) + list(event_lines or []) + list(watch_items or [])
    if any(_is_placeholder_text(x) for x in core_items):
        qa_fail_reasons.append("核心章节出现暂无")
        qa_score -= 40
    if len(signal_items) < 5:
        if tavily_api_key.strip():
            qa_fail_reasons.append("信号汇总条目不足（已尝试Tavily补齐）")
            qa_score -= 25
        else:
            qa_fail_reasons.append("信号汇总条目不足（需Tavily补齐）")
            qa_score -= 35
    if any("|" in x for x in signal_items[:6]):
        qa_fail_reasons.append("信号格式异常")
        qa_score -= 20
    if any(x in md for x in low_info):
        qa_fail_reasons.append("出现低信息量句")
        qa_score -= 15
    if "主线=" not in md:
        qa_fail_reasons.append("主线定义缺失")
        qa_score -= 25
    if "以 BTC 为分析标的" not in md:
        qa_fail_reasons.append("BTC延展缺失")
        qa_score -= 25
    if "热门事件" not in md:
        qa_fail_reasons.append("热门事件清单缺失")
        qa_score -= 25
    if len(chart_items) < 6:
        qa_fail_reasons.append("技术指标不足")
        qa_score -= 15
    if qa_score < 0:
        qa_score = 0
    qa_gate = "pass"
    hard_fail_exact = {"命中禁语", "核心章节出现暂无", "信号格式异常"}
    hard_fail_prefix = ("信号汇总条目不足",)
    hard_fail_hit = any((r in hard_fail_exact) or any(r.startswith(p) for p in hard_fail_prefix) for r in qa_fail_reasons)
    if qa_score < 70 or hard_fail_hit:
        qa_gate = "fail"
    elif qa_score < 85:
        qa_gate = "warn"
    meta = {
        "transform_profile": "daily_report_v3_llm",
        "tavily_enabled": bool(tavily_api_key.strip()),
        "tavily_used": bool(tavily_used),
        "llm_enabled": True,
        "qa_gate": qa_gate,
        "qa_score": int(qa_score),
        "qa_fail_reasons": qa_fail_reasons,
        "diff_audit": diff_audit,
        "source_urls": source_urls[:12],
        "source_category_counts": {k: len(v) for k, v in source_categories.items()},
        "source_chars": len(raw_content or ""),
        "public_chars": len(md),
    }
    return {"title": public_title, "summary": summary, "content": md, "meta": meta}


def transform_daily_report_v2(
    raw_content: str,
    title: str,
    tavily_api_key: str = "",
    max_headlines: int = 5,
    max_events: int = 5,
    search_fn: Callable[[str, int], list[dict]] | None = None,
) -> dict:
    cleaned = _strip_noise(raw_content)
    parsed = _split_sections(cleaned)

    actions = _extract_actions(parsed, cleaned)
    market_state = _extract_market_state(parsed, cleaned)

    tavily_used = False
    source_urls: list[str] = []
    queries = [
        "crypto market breaking news last 24 hours",
        "upcoming crypto events next 72 hours",
    ]
    if search_fn is None:
        def _default_search(q: str, n: int) -> list[dict]:
            return _tavily_search(q, tavily_api_key, max_results=n)
        search_fn = _default_search

    news_rows = search_fn(queries[0], max_headlines) if tavily_api_key.strip() else []
    event_rows = search_fn(queries[1], max_events) if tavily_api_key.strip() else []

    if news_rows or event_rows:
        tavily_used = True
    if not news_rows:
        news_rows = _fallback_headlines(cleaned, max_items=max_headlines)
    if not event_rows:
        event_rows = _fallback_headlines(cleaned, max_items=max_events)

    for x in news_rows + event_rows:
        u = str(x.get("url") or "").strip()
        if u and u not in source_urls:
            source_urls.append(u)

    headlines = [str(x.get("title") or x.get("content") or "").strip() for x in news_rows]
    headlines = [x for x in headlines if x][:max_headlines]
    if not headlines:
        headlines = ["暂无可用快讯标题，建议关注交易所与链上事件更新。"]
    bull, bear = _classify_sentiment(news_rows)

    event_lines = [str(x.get("title") or x.get("content") or "").strip() for x in event_rows]
    event_lines = [x for x in event_lines if x][:max_events]
    if not event_lines:
        event_lines = ["未来24-72小时暂无高置信度事件，建议持续监控宏观与链上动态。"]

    constraints = [
        "仅在满足流动性与成交量阈值的标的上执行，避免低深度追单。",
        "若热度上升但资金净流入转弱，应降低进攻仓位并提高止损纪律。",
        "重大事件公布前后控制杠杆与仓位，避免流动性瞬时塌陷。",
    ]

    public_title = f"{title}｜对外版"
    now_txt = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = "\n".join(
        [
            f"# {public_title}",
            "",
            f"> 发布时间: {now_txt}",
            "",
            "## 一、今日建议动作（执行摘要）",
            *[f"- {x}" for x in actions],
            "",
            "## 二、市场状态与主要矛盾",
            *[f"- {x}" for x in market_state],
            "",
            "## 三、关键信号与证据（多维）",
            "### 3.1 快讯标题（24h）",
            *[f"- {x}" for x in headlines],
            "",
            "### 3.2 利多/利空简析",
            "- 利多:",
            *[f"  - {x}" for x in bull],
            "- 利空:",
            *[f"  - {x}" for x in bear],
            "",
            "## 四、交易约束与失效条件",
            *[f"- {x}" for x in constraints],
            "",
            "## 五、未来24-72小时关键事件日历",
            *[f"- {x}" for x in event_lines],
            "",
            "## 六、说明",
            "- 本内容仅用于市场信息交流，不构成投资建议。",
            "",
        ]
    ).strip() + "\n"

    summary = _summary_from_bullets(actions, limit=220)
    meta = {
        "transform_profile": "daily_report_v2_tavily",
        "tavily_enabled": bool(tavily_api_key.strip()),
        "tavily_used": bool(tavily_used),
        "query_count": 2 if tavily_api_key.strip() else 0,
        "source_urls": source_urls[:12],
        "headlines_count": len(headlines),
        "events_count": len(event_lines),
        "source_chars": len(raw_content or ""),
        "public_chars": len(md),
    }
    return {
        "title": public_title,
        "summary": summary,
        "content": md,
        "meta": meta,
    }


def main() -> int:
    # simple manual probe
    sample = os.environ.get("DAILY_REPORT_SAMPLE_MD", "")
    if not sample.strip():
        print(json.dumps({"ok": False, "error": "DAILY_REPORT_SAMPLE_MD is empty"}, ensure_ascii=False))
        return 2
    out = transform_daily_report_v3(
        raw_content=sample,
        title="AI 市场研究日报",
        tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
    )
    print(json.dumps({"ok": True, "summary": out["summary"], "meta": out["meta"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
