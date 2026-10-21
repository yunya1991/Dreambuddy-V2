# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P-矛盾：矛盾体语义识别（SPEC §9.5，零 token）

矛盾体识别不新建机制，复用分层事件流架构自然生长：
  快讯事件（外部语义）与内部因子事件（原子层）按时间窗对齐，
  检测方向相反的矛盾体，矛盾事件作为新事件类型写入事件流供 P3 消费。

矛盾类型（SPEC §9.5 三层价值，描述性观察）：
  1. 宏观与微观：宏观快讯情绪 vs 内部市场情绪状态（恐惧贪婪）方向相反
     - 快讯利好(>0.5) vs 恐惧贪婪极度恐慌(<25) → 矛盾
     - 快讯利空(<0.5) vs 恐惧贪婪极度贪婪(>75) → 矛盾
  2. 个体与整体：单币利好/利空快讯密集 vs 整体情绪状态相反
     - 窗口内某代币利好快讯 ≥2 条 vs 整体极度恐慌 → 矛盾
  3. 短期与长期：短期快讯情绪倾向 vs 资金费率状态（持仓结构）方向相反
     - 窗口快讯情绪均值利好 vs 资金费率为负（空头主导） → 矛盾

对齐窗口（预注册）：4 小时
产出:
  - contradiction_events.jsonl（矛盾事件流，供 P3 复杂语义消费）
  - contradiction_semantics.json（矛盾类型统计画像）
用法: /home/luke/venv-trading/bin/python3 gen_contradiction_semantics.py
边界: 描述性矛盾观察（P-矛盾），不做方向判断，不产生交易信号
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _THIS_DIR)
import dc_pg

ATOMIC_PATH = os.path.join(_SYS_DIR, "atomic_events.jsonl")
OUT_EVENTS_PATH = os.path.join(_SYS_DIR, "contradiction_events.jsonl")
OUT_STATS_PATH = os.path.join(_SYS_DIR, "contradiction_semantics.json")

# ── 预注册参数（禁止事后调整）──
ALIGN_WINDOW_H = 4      # 对齐窗口：4 小时
EXTREME_LOW, EXTREME_HIGH = 25.0, 75.0   # 恐惧贪婪极值分区
MIN_TICKER_NEWS = 2     # 个体矛盾：窗口内单币快讯最少条数


def _parse_ts(ts):
    if not ts:
        return None
    if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
        v = float(ts)
        if v > 1e12:
            v = v / 1000.0
        try:
            return datetime.fromtimestamp(v)
        except Exception:
            return None
    t = str(ts).replace("Z", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H"):
        try:
            return datetime.strptime(t[:19], fmt)
        except Exception:
            continue
    return None


# 文本关键词情绪口径（复用 L2 事件线已验证的正负词表）
_POS_WORDS = ("上涨", "突破", "新高", "利好", "批准", "融资", "增持", "上涨", "反弹", "回暖", "乐观", "看涨", "流入")
_NEG_WORDS = ("下跌", "暴跌", "利空", "制裁", "禁止", "黑客", "清算", "减持", "下跌", "暴跌", "恐慌", "看跌", "流出", "暴雷", "崩盘")


def _text_sentiment(desc):
    """描述文本关键词情绪 → 0-1 映射（正 0.7 / 负 0.3 / 中性 0.5）。"""
    pos = sum(1 for w in _POS_WORDS if w in desc)
    neg = sum(1 for w in _NEG_WORDS if w in desc)
    if pos > neg:
        return 0.7
    if neg > pos:
        return 0.3
    return 0.5


def load_newsflash(limit=2000):
    """加载快讯事件，返回 [{ts, sentiment, event_type, tickers, desc}] 升序。

    情绪判定：od_policy_sentiment_0_1 有区分度（≠0.5）时优先（政策类快讯权威标注），
    否则用描述文本关键词情绪（覆盖全部快讯，复用 L2 已验证口径）。
    """
    rows = dc_pg.fetch_records("newsflash_%", limit=limit, order_desc=False)
    events = []
    for r in rows:
        m = r.get("metrics") or {}
        ts = _parse_ts(m.get("publishTimestamp") or r.get("timestamp"))
        if ts is None:
            continue
        desc = m.get("description") or ""
        sent = m.get("od_policy_sentiment_0_1")
        if isinstance(sent, (int, float)) and sent != 0.5:
            sentiment = float(sent)
            sent_source = "policy_field"
        else:
            sentiment = _text_sentiment(desc)
            sent_source = "text_keywords"
        th = m.get("tickers_hit") or []
        if isinstance(th, str):
            try:
                th = json.loads(th)
            except Exception:
                th = []
        events.append({
            "ts": ts,
            "sentiment": sentiment,
            "sentiment_source": sent_source,
            "event_type": m.get("od_event_type", "unknown"),
            "tickers": th if isinstance(th, list) else [],
            "desc": desc[:80],
        })
    events.sort(key=lambda e: e["ts"])
    return events


def load_internal_states():
    """加载内部因子状态时间线：恐惧贪婪值与资金费率。"""
    fg_timeline = []   # [(ts, value)]
    fr_timeline = []   # [(ts, value)]
    try:
        with open(ATOMIC_PATH, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts = _parse_ts(e.get("timestamp", ""))
                if ts is None:
                    continue
                cat = e.get("category", "")
                v = e.get("value")
                if cat in ("crypto_fear_greed", "fear_greed_enhanced") and isinstance(v, (int, float)):
                    fg_timeline.append((ts, float(v)))
                elif cat == "funding_rate" and isinstance(v, (int, float)):
                    fr_timeline.append((ts, float(v)))
    except FileNotFoundError:
        pass
    fg_timeline.sort()
    fr_timeline.sort()
    return fg_timeline, fr_timeline


def _state_at(timeline, ts):
    """取时间线上 ts 时刻的最近状态值。"""
    val = None
    for t, v in timeline:
        if t <= ts:
            val = v
        else:
            break
    return val


def detect_contradictions(news, fg_timeline, fr_timeline):
    """按 4h 窗口对齐检测三类矛盾体（描述性）。"""
    events = []
    if not news:
        return events
    win_start = news[0]["ts"]
    win_end = news[-1]["ts"]
    cur = win_start
    while cur <= win_end:
        w_end = cur + timedelta(hours=ALIGN_WINDOW_H)
        w_news = [n for n in news if cur <= n["ts"] < w_end]
        if w_news:
            # 窗口快讯情绪倾向
            sents = [n["sentiment"] for n in w_news]
            avg_sent = sum(sents) / len(sents)
            bullish = avg_sent > 0.5
            bearish = avg_sent < 0.5
            fg = _state_at(fg_timeline, w_end)
            fr = _state_at(fr_timeline, w_end)
            # 1) 宏观与微观：快讯情绪 vs 恐惧贪婪极值方向相反
            if fg is not None:
                if bullish and fg < EXTREME_LOW:
                    events.append(_mk("macro_micro", cur, w_end, len(w_news),
                                      f"窗口快讯情绪偏利好(均值{avg_sent:.2f}) vs 恐惧贪婪极度恐慌({fg:.0f})",
                                      "宏观利好叙事 vs 微观极度恐慌，矛盾体观察"))
                elif bearish and fg > EXTREME_HIGH:
                    events.append(_mk("macro_micro", cur, w_end, len(w_news),
                                      f"窗口快讯情绪偏利空(均值{avg_sent:.2f}) vs 恐惧贪婪极度贪婪({fg:.0f})",
                                      "宏观利空叙事 vs 微观极度贪婪，矛盾体观察"))
            # 2) 个体与整体：单币快讯密集且方向与整体情绪相反
            if fg is not None:
                ticker_sents = defaultdict(list)
                for n in w_news:
                    for t in n["tickers"]:
                        ticker_sents[t].append(n["sentiment"])
                for t, ss in ticker_sents.items():
                    if len(ss) >= MIN_TICKER_NEWS:
                        t_avg = sum(ss) / len(ss)
                        if t_avg > 0.5 and fg < EXTREME_LOW:
                            events.append(_mk("individual_whole", cur, w_end, len(ss),
                                              f"{t} 窗口内 {len(ss)} 条利好快讯 vs 整体极度恐慌({fg:.0f})",
                                              f"个体({t})利好密集 vs 整体恐慌，矛盾体观察"))
                        elif t_avg < 0.5 and fg > EXTREME_HIGH:
                            events.append(_mk("individual_whole", cur, w_end, len(ss),
                                              f"{t} 窗口内 {len(ss)} 条利空快讯 vs 整体极度贪婪({fg:.0f})",
                                              f"个体({t})利空密集 vs 整体贪婪，矛盾体观察"))
            # 3) 短期与长期：快讯短期情绪 vs 资金费率持仓结构方向相反
            if fr is not None and fr != 0:
                if bullish and fr < 0:
                    events.append(_mk("short_long", cur, w_end, len(w_news),
                                      f"窗口快讯情绪偏利好(均值{avg_sent:.2f}) vs 资金费率为负({fr:.4f})",
                                      "短期利好叙事 vs 持仓结构空头主导，矛盾体观察"))
                elif bearish and fr > 0:
                    events.append(_mk("short_long", cur, w_end, len(w_news),
                                      f"窗口快讯情绪偏利空(均值{avg_sent:.2f}) vs 资金费率为正({fr:.4f})",
                                      "短期利空叙事 vs 持仓结构多头主导，矛盾体观察"))
        cur = w_end
    return events


def _mk(ctype, w_start, w_end, n_news, observation, note):
    return {
        "layer": "organizational",
        "event_type": "contradiction",
        "contradiction_type": ctype,
        "window_start": w_start.strftime("%Y-%m-%d %H:%M"),
        "window_end": w_end.strftime("%Y-%m-%d %H:%M"),
        "news_count": n_news,
        "observation": observation,
        "note": note,
        "boundary": "描述性矛盾观察（P-矛盾），不做方向判断，不产生交易信号",
    }


def main():
    news = load_newsflash()
    fg_timeline, fr_timeline = load_internal_states()
    print(f"[OK] 快讯事件加载 {len(news)} 条（含情绪标注）")
    print(f"[OK] 内部状态加载: 恐惧贪婪 {len(fg_timeline)} 点 / 资金费率 {len(fr_timeline)} 点")

    events = detect_contradictions(news, fg_timeline, fr_timeline)
    with open(OUT_EVENTS_PATH, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # 矛盾类型统计画像
    by_type = defaultdict(int)
    for e in events:
        by_type[e["contradiction_type"]] += 1
    profile = {
        "generated_at": "2026-10-20",
        "align_window_h": ALIGN_WINDOW_H,
        "total_contradictions": len(events),
        "by_type": dict(by_type),
        "type_definition": {
            "macro_micro": "宏观快讯情绪 vs 微观恐惧贪婪极值方向相反",
            "individual_whole": "单币快讯密集方向 vs 整体情绪状态相反",
            "short_long": "短期快讯情绪 vs 资金费率持仓结构方向相反",
        },
        "boundary": "描述性矛盾观察（P-矛盾），矛盾转化检测供 L3 消费，不产生交易信号",
    }
    with open(OUT_STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"[OK] P-矛盾完成: 检出矛盾事件 {len(events)} 条 -> {OUT_EVENTS_PATH}")
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"     {t}: {n} 条")
    print(f"     矛盾画像 -> {OUT_STATS_PATH}")
    for e in events[-3:]:
        print(f"     [样例] {e['window_start']} {e['observation']}")


if __name__ == "__main__":
    main()
