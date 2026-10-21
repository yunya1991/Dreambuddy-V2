# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P-权重：内外样本权重机制（SPEC §9.4，零 token）

核心矛盾：本地知识有序高质量 vs 外部快讯无序但鲜活。三层机制：
  1. 初始权重分层：本地蒸馏样本（quality=A/B）初始权重高；快讯样本初始权重低
  2. 动态可信度调整：快讯事件被后续行情印证 → 升权；被证伪 → 降权
     - 印证判定范围：自动发现数据库中所有价格数据表（XXX/USDT），
       关联代币任一有价格数据即可验证，范围随 18 中心采集自动扩展
     - 判定规则（预注册）：快讯情绪预期（od_policy_sentiment_0_1 >0.5 利好 / <0.5 利空）
       vs 发布后 4h 价格变动方向（>+0.5% 同向=印证 / <-0.5% 反向=证伪 / 其间=中性）
  3. 来源可信度画像：按事件类型统计历史印证/证伪/未验证分布

产出:
  - newsflash_weights.jsonl（每条快讯的权重记录，供 34 训练流消费）
  - source_credibility.json（事件类型可信度画像）
用法: /home/luke/venv-trading/bin/python3 gen_newsflash_weights.py
边界: 权重是训练样本属性（描述性），非交易信号（SPEC §9.4/§7.4）
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
sys_path = os.path
import sys
sys.path.insert(0, _THIS_DIR)
import dc_pg

WEIGHTS_PATH = os.path.join(_SYS_DIR, "newsflash_weights.jsonl")
CREDIBILITY_PATH = os.path.join(_SYS_DIR, "source_credibility.json")

# ── 预注册参数（禁止事后调整）──
INIT_WEIGHT_NEWSFLASH = 0.3   # 快讯样本初始权重
INIT_WEIGHT_LOCAL_A = 1.0    # 本地蒸馏 A 级样本初始权重（对照声明）
INIT_WEIGHT_LOCAL_B = 0.7    # 本地蒸馏 B 级样本初始权重（对照声明）
VERIFY_WINDOW_H = 4          # 印证观察窗口：发布后 4 小时
PRICE_MOVE_THRESHOLD = 0.005 # 价格变动阈值：±0.5% 之外才算方向
WEIGHT_UP = 0.6              # 印证后权重
WEIGHT_DOWN = 0.1            # 证伪后权重
WEIGHT_NEUTRAL = 0.3         # 中性维持初始权重


def _parse_ts(ts):
    if not ts:
        return None
    # 毫秒时间戳（快讯 publishTimestamp/published_ms 格式）
    if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
        v = float(ts)
        if v > 1e12:  # 毫秒级
            v = v / 1000.0
        try:
            return datetime.fromtimestamp(v)
        except Exception:
            return None
    t = str(ts).replace("Z", "").replace("T", " ")
    try:
        return datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def load_price_tables():
    """自动发现价格数据表（sub_category 形如 XXX/USDT），返回 {symbol: [(ts, last)] 升序}。

    验证范围随 18 中心价格数据采集自动扩展：新标的价格表入库后，
    对应代币的关联快讯自动进入印证判定范围（无需改代码）。
    """
    try:
        conn = dc_pg._connect()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT sub_category FROM records WHERE sub_category LIKE '%/USDT'")
        cats = [r[0] for r in cur.fetchall()]
        conn.close()
    except Exception:
        cats = []
    tables = {}
    for cat in cats:
        symbol = cat.split("/")[0]
        rows = dc_pg.fetch_records(cat, limit=600, order_desc=False)
        prices = []
        for r in rows:
            m = r.get("metrics") or {}
            last = m.get("last")
            t = _parse_ts(r.get("timestamp"))
            if isinstance(last, (int, float)) and t is not None:
                prices.append((t, float(last)))
        if prices:
            tables[symbol] = prices
    return tables


def price_after(prices, publish_dt, hours):
    """取发布时刻与发布后 N 小时的 BTC 价格（最近的小时线）。"""
    end_dt = publish_dt + timedelta(hours=hours)
    p0 = p1 = None
    for t, p in prices:
        if t <= publish_dt:
            p0 = p
        if t <= end_dt:
            p1 = p
        else:
            break
    if p0 is None or p1 is None or p0 <= 0:
        return None
    return (p1 - p0) / p0


def verify_newsflash(row, price_tables):
    """对单条快讯做印证/证伪/中性/未验证判定（关联代币任一有价格数据即可验证）。"""
    m = row.get("metrics") or {}
    th = m.get("tickers_hit") or []
    if isinstance(th, str):
        try:
            th = json.loads(th)
        except Exception:
            th = []
    sym_prices = None
    for t in th:
        if t in price_tables:
            sym_prices = price_tables[t]
            break
    if sym_prices is None:
        return "unverified", None, None
    pub = _parse_ts(m.get("publishTimestamp") or row.get("timestamp"))
    if pub is None:
        return "unverified", None, None
    move = price_after(sym_prices, pub, VERIFY_WINDOW_H)
    if move is None:
        return "unverified", None, None
    sentiment = m.get("od_policy_sentiment_0_1")
    if not isinstance(sentiment, (int, float)):
        return "neutral", move, None
    expect_up = sentiment > 0.5
    if move > PRICE_MOVE_THRESHOLD:
        actual_up = True
    elif move < -PRICE_MOVE_THRESHOLD:
        actual_up = False
    else:
        return "neutral", move, sentiment  # 价格变动在阈值内，无法判定
    if expect_up == actual_up:
        return "verified", move, sentiment
    return "falsified", move, sentiment


def main():
    price_tables = load_price_tables()
    print(f"[OK] 价格数据表加载: " + ", ".join(f"{s}({len(p)}条)" for s, p in price_tables.items()))
    rows = dc_pg.fetch_records("newsflash_%", limit=2000, order_desc=False)
    print(f"[OK] 快讯加载 {len(rows)} 条")

    records = []
    cred = defaultdict(lambda: {"verified": 0, "falsified": 0, "neutral": 0, "unverified": 0})
    for row in rows:
        m = row.get("metrics") or {}
        status, move, sentiment = verify_newsflash(row, price_tables)
        if status == "verified":
            weight = WEIGHT_UP
        elif status == "falsified":
            weight = WEIGHT_DOWN
        else:
            weight = WEIGHT_NEUTRAL if status == "neutral" else INIT_WEIGHT_NEWSFLASH
        etype = m.get("od_event_type", "unknown")
        cred[etype][status] += 1
        records.append({
            "record_id": row.get("id"),
            "timestamp": row.get("timestamp"),
            "event_type": etype,
            "tickers_hit": m.get("tickers_hit"),
            "policy_sentiment": sentiment,
            "verify_status": status,
            "price_move_4h": round(move, 4) if move is not None else None,
            "weight": weight,
            "weight_rule": f"初始 {INIT_WEIGHT_NEWSFLASH}；印证 {WEIGHT_UP}；证伪 {WEIGHT_DOWN}；中性 {WEIGHT_NEUTRAL}（预注册）",
            "boundary": "训练样本权重属性（P-权重），非交易信号",
        })

    with open(WEIGHTS_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 事件类型可信度画像
    profile = {}
    for etype, c in sorted(cred.items()):
        total = sum(c.values())
        judged = c["verified"] + c["falsified"]
        profile[etype] = {
            "total": total,
            "verified": c["verified"],
            "falsified": c["falsified"],
            "neutral": c["neutral"],
            "unverified": c["unverified"],
            "verify_rate": round(c["verified"] / judged, 4) if judged > 0 else None,
            "note": "印证率基于关联代币价格验证（自动发现价格表，4h 窗口，±0.5% 阈值）" if judged > 0 else "暂无可验证样本",
        }
    out = {
        "generated_at": "2026-10-20",
        "source": "星球日报快讯（单一来源，画像按事件类型维度）",
        "local_sample_weights": {"A": INIT_WEIGHT_LOCAL_A, "B": INIT_WEIGHT_LOCAL_B},
        "newsflash_init_weight": INIT_WEIGHT_NEWSFLASH,
        "verify_rule": f"关联代币价格验证（自动发现 XXX/USDT 价格表），发布后 {VERIFY_WINDOW_H}h 价格变动 ±{PRICE_MOVE_THRESHOLD:.1%}，情绪预期 vs 实际方向（预注册）",
        "event_type_profile": profile,
        "boundary": "来源可信度画像为描述性统计，供训练样本权重调整参考，非交易信号",
    }
    with open(CREDIBILITY_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 汇总
    status_count = defaultdict(int)
    for r in records:
        status_count[r["verify_status"]] += 1
    print(f"[OK] P-权重完成: {len(records)} 条权重记录 -> {WEIGHTS_PATH}")
    print(f"     印证 {status_count['verified']} | 证伪 {status_count['falsified']} | 中性 {status_count['neutral']} | 未验证 {status_count['unverified']}")
    print(f"     可信度画像 -> {CREDIBILITY_PATH}")
    for etype, p in sorted(profile.items(), key=lambda kv: -kv[1]["total"])[:6]:
        vr = f"{p['verify_rate']:.0%}" if p["verify_rate"] is not None else "-"
        print(f"     {etype}: 共 {p['total']} 条, 印证率 {vr}")


if __name__ == "__main__":
    main()
