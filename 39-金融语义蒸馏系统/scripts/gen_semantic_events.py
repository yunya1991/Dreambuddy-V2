# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P1 语义事件流生成（SPEC §7.2，零 token）

将交易日志中的术语出现记录升级为语义事件：
  语义事件 = {术语, 时间戳, 标的, 取值, 市场上下文, 后续结果}

产出: semantic_events.jsonl（持续追加流，供 P3 复杂语义衍生与 34 训练消费）

运行模式:
  --backfill  回填模式：扫描历史 trader.log，生成历史事件（一次性）
  --live      增量模式：只处理上次运行后的新增日志行（配合定时任务持续追加）

事件源模式（SPEC-EMERGENCE-FINANCIAL-ENV §3.4 / P0-A，2026-11-11）:
  --source events  读取 canonical EventRecord（18/data_center/events/events.jsonl），
                   调用 9 域 SentimentEngine 打分后追加 sentiment/event/trace_id 三个块；
                   sentiment=null 是合法状态（模型不可用），禁止填 0 冒充已打分。
                   旧行不重写，按 trace_id 幂等跳过。

用法:
  python3 gen_semantic_events.py --backfill
  python3 gen_semantic_events.py --live
  python3 gen_semantic_events.py --source events
"""

import argparse
import importlib.util
import json
import os
import re

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

TRADER_LOG = "/home/luke/logs/yijing/trader.log"
OUT_PATH = os.path.join(_SYS_DIR, "semantic_events.jsonl")
STATE_PATH = os.path.join(_SYS_DIR, ".semantic_events_state.json")
EVENTS_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center", "events", "events.jsonl")
# P1-A：中文财经正文外置存储（事件 body_ref → bodies.jsonl#<id>）
BODIES_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center", "events", "bodies.jsonl")
SENTIMENT_ENGINE_PATH = os.path.join(_REPO, "9-基本面分析", "engines", "sentiment_engine.py")

# 事件类型 → 半衰期（小时），与 SPEC §3.3 表格一致；未列出的走 24h
HALF_LIFE_H = {
    "earnings": 24,
    "guidance": 24,
    "fomc": 24,
    "rate_decision": 24,
    "cpi": 24,
    "nfp": 24,
    "macro_other": 24,
    "mna": 48,
    "buyback": 48,
    "dividend": 48,
    "regulatory": 48,
    "product": 48,
    "legal": 48,
}

_sentiment_engine = None

# 术语事件模式（术语 → 正则，含分组提取取值）
# 结构约定: 时间戳后固定 [INFO]，再取 [标的]，避免非贪婪误匹配 [INFO]
EVENT_PATTERNS = {
    "BCRM连续性": re.compile(r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?BCRM连续=(\w+)\(([\d.]+)\)"),
    "三层弹性放行": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?方案C 三层弹性放行 \| P1=(\w+) Elder=(\w+) BCRM连续=(\w+) Score_B=([\d.]+)"
    ),
    "弹性门控试错仓": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?ElasticGate3L 将给 ?([\d.]+) ?试错仓"
    ),
    "BDSM仓位兜底": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?BDSM 最低仓位兜底 \| ([\d.]+)U→([\d.]+)U"
    ),
    "P1趋势过滤": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?P1长多趋势过滤 \| 共振(成功|失败)"
    ),
    "反向信号软权重": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[[\w\-]+\] (\w+).*?反向信号软权重.*?仓位 ×([\d.]+)"
    ),
    "开仓事件": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\] 开仓成功 \| ordId=([\w]+) \| 入场价≈([\d.]+)"
    ),
    "置信度信号": re.compile(r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?置信度=([\d.]+) 方向=(\w+)"),
}


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"processed_lines": 0}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _emit(events, term, ts, symbol, values, raw):
    events.append(
        {
            "term": term,
            "timestamp": ts.strip(),
            "symbol": symbol,
            "values": values,
            "raw": raw[:200],
            "source": "trader.log",
        }
    )


def scan(start_line=0, max_lines=500000):
    """从指定行号扫描日志，生成语义事件列表。"""
    events = []
    processed = 0
    try:
        with open(TRADER_LOG, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                if i - start_line >= max_lines:
                    break
                processed += 1
                for term, pat in EVENT_PATTERNS.items():
                    m = pat.search(line)
                    if m:
                        g = m.groups()
                        # 通用结构: (时间, 标的, *取值)
                        ts, symbol = g[0], g[1]
                        values = list(g[2:])
                        _emit(events, term, ts, symbol, values, line.strip())
                        # 同一行可含多个术语事件（如 P1过滤+弹性门控），各自独立记录
    except FileNotFoundError:
        pass
    return events, processed


def _load_scorer():
    """懒加载 9 域情绪引擎（模型生命周期留在 9，39 只调用稳定函数，不 import torch）。"""
    global _sentiment_engine
    if _sentiment_engine is None:
        spec = importlib.util.spec_from_file_location(
            "dreambuddy_sentiment_engine", SENTIMENT_ENGINE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _sentiment_engine = module.SentimentEngine()
    return _sentiment_engine


# 中文模型标记：必须整词/带分隔符匹配，不能用裸 "zh" 子串
# （否则本地路径 /Users/zhangjiangtao/... 会把英文模型误判成中文模型）
_ZH_MODEL_RE = re.compile(r"(chinese|finbert[-_]?zh|(^|[/_\-])zh($|[/_\-]))")


def _normalize_model(raw):
    """§7.7：落库 model 归一化为四值，避免同一模型多种写法。"""
    if not raw:
        return "unavailable"
    low = str(raw).lower()
    if "rule" in low:
        return "rule_fallback"
    if _ZH_MODEL_RE.search(low):
        return "finbert-tone-chinese"
    if "finbert" in low:
        return "ProsusAI/finbert"
    return "unavailable"


def _score_text(text, half_life_h=24):
    """调用 9 域 FinBERT 打分服务；异常 → None（sentiment=null 合法，禁止填 0 冒充）。"""
    try:
        res = _load_scorer().analyze_text(text, with_meta=True)
    except Exception:
        return None
    if not isinstance(res, dict):
        return None
    return {
        "score": round(float(res.get("score", 0.0)), 4),
        "confidence": res.get("confidence"),
        "model": _normalize_model(res.get("model")),
        "half_life_h": half_life_h,
    }


def _load_bodies(path=None):
    """读取正文快照（body_id → content_text）；缺失返回空 dict（FAIL-OPEN）。"""
    path = path or os.environ.get("EMERGENCE_BODIES_PATH") or BODIES_PATH
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("id"):
                    out[str(row["id"])] = str(row.get("content_text") or "")
    except OSError:
        return {}
    return out


def _resolve_body(ev, bodies):
    """事件正文：兼容内联 body（旧行）与 body_ref（P1-A 正文外置）。"""
    inline = str(ev.get("body") or "").strip()
    if inline:
        return inline
    ref = ev.get("body_ref")
    if not ref or not bodies:
        return ""
    return str(bodies.get(str(ref).split("#")[-1].strip()) or "").strip()


def _event_to_line(ev, scorer=_score_text, bodies=None):
    """canonical EventRecord → 39 语义事件行（新增 sentiment / event / trace_id）。"""
    etype = ev.get("type") or "macro_other"
    title = str(ev.get("title") or "").strip()
    body = _resolve_body(ev, bodies or {})
    text = f"{title}。{body}".strip("。 ") if title else ""
    sentiment = scorer(text, HALF_LIFE_H.get(etype, 24)) if text else None
    symbols = [str(s) for s in (ev.get("symbols") or []) if s]
    return {
        "term": title[:80] or etype,
        "timestamp": ev.get("available_at") or ev.get("event_time") or "",
        "symbol": symbols[0] if symbols else "MACRO",
        "values": [f"{sentiment['score']:.4f}"] if sentiment else [],
        "raw": title[:200],
        "source": "events.jsonl",
        "sentiment": sentiment,
        "event": {
            "type": etype,
            "surprise": ev.get("surprise"),
            "surprise_unit": ev.get("surprise_unit"),
        },
        "trace_id": ev.get("event_id"),
    }


def emit_from_events(events_path=None, out_path=None, scorer=None, bodies_path=None):
    """把 canonical EventRecord 转成 39 语义事件行；按 trace_id 幂等，旧行不重写。"""
    events_path = events_path or os.environ.get("EMERGENCE_EVENTS_PATH") or EVENTS_PATH
    out_path = out_path or OUT_PATH
    scorer = scorer or _score_text
    bodies = _load_bodies(bodies_path)
    if not os.path.isfile(events_path):
        print(f"[WARN] 事件文件不存在，跳过：{events_path}")
        return [], 0

    seen = set()
    if os.path.isfile(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("source") == "events.jsonl" and row.get("trace_id"):
                    seen.add(row["trace_id"])

    emitted, skipped = [], 0
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event_id") in seen:
                skipped += 1
                continue
            emitted.append(_event_to_line(ev, scorer, bodies))
            seen.add(ev.get("event_id"))

    if emitted:
        with open(out_path, "a", encoding="utf-8") as f:
            for e in emitted:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return emitted, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="回填模式：全量扫描历史日志")
    parser.add_argument("--live", action="store_true", help="增量模式：只处理新增行")
    parser.add_argument(
        "--source", choices=["trader", "events"], default="trader", help="事件源（P0-A）"
    )
    parser.add_argument("--events-path", default=None, help="canonical events.jsonl 路径")
    args = parser.parse_args()

    if args.source == "events":
        emitted, skipped = emit_from_events(args.events_path)
        print(f"[OK] 事件源：新增 {len(emitted)} 条，跳过已处理 {skipped} 条 → {OUT_PATH}")
        return

    if args.backfill:
        start = 0
    elif args.live:
        start = _load_state().get("processed_lines", 0)
        # ── 轮转检测（2026-10-29）：日志轮转后行数小于已处理行数 → 自动重置从头扫描 ──
        # 防止轮转导致状态错位、增量模式静默停更（10-25 轮转事故复盘）
        try:
            with open(TRADER_LOG, "r", encoding="utf-8", errors="ignore") as f:
                total_lines = sum(1 for _ in f)
            if start > total_lines:
                print(
                    f"[WARN] 检测到日志轮转：已处理 {start} 行 > 当前 {total_lines} 行，重置状态从头扫描"
                )
                start = 0
        except FileNotFoundError:
            pass
    else:
        parser.error("需指定 --backfill 或 --live")

    events, processed = scan(start)
    if events:
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    _save_state({"processed_lines": start + processed})

    print(
        f"[OK] 模式={'backfill' if args.backfill else 'live'} "
        f"扫描 {processed} 行, 产出 {len(events)} 条语义事件 → {OUT_PATH}"
    )
    if events:
        by_term = {}
        for e in events:
            by_term[e["term"]] = by_term.get(e["term"], 0) + 1
        for t, n in sorted(by_term.items(), key=lambda kv: -kv[1]):
            print(f"     {t}: {n} 条")


if __name__ == "__main__":
    main()
