# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P1 语义事件流生成（SPEC §7.2，零 token）

将交易日志中的术语出现记录升级为语义事件：
  语义事件 = {术语, 时间戳, 标的, 取值, 市场上下文, 后续结果}

产出: semantic_events.jsonl（持续追加流，供 P3 复杂语义衍生与 34 训练消费）

运行模式:
  --backfill  回填模式：扫描历史 trader.log，生成历史事件（一次性）
  --live      增量模式：只处理上次运行后的新增日志行（配合定时任务持续追加）

用法:
  python3 gen_semantic_events.py --backfill
  python3 gen_semantic_events.py --live
"""
import argparse
import json
import os
import re

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)

TRADER_LOG = "/home/luke/logs/yijing/trader.log"
OUT_PATH = os.path.join(_SYS_DIR, "semantic_events.jsonl")
STATE_PATH = os.path.join(_SYS_DIR, ".semantic_events_state.json")

# 术语事件模式（术语 → 正则，含分组提取取值）
# 结构约定: 时间戳后固定 [INFO]，再取 [标的]，避免非贪婪误匹配 [INFO]
EVENT_PATTERNS = {
    "BCRM连续性": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?BCRM连续=(\w+)\(([\d.]+)\)"),
    "三层弹性放行": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?方案C 三层弹性放行 \| P1=(\w+) Elder=(\w+) BCRM连续=(\w+) Score_B=([\d.]+)"),
    "弹性门控试错仓": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?ElasticGate3L 将给 ?([\d.]+) ?试错仓"),
    "BDSM仓位兜底": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?BDSM 最低仓位兜底 \| ([\d.]+)U→([\d.]+)U"),
    "P1趋势过滤": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?P1长多趋势过滤 \| 共振(成功|失败)"),
    "反向信号软权重": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[[\w\-]+\] (\w+).*?反向信号软权重.*?仓位 ×([\d.]+)"),
    "开仓事件": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\] 开仓成功 \| ordId=([\w]+) \| 入场价≈([\d.]+)"),
    "置信度信号": re.compile(
        r"\[([\d:\- ]+)\] \[INFO\] \[(\w+)\].*?置信度=([\d.]+) 方向=(\w+)"),
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
    events.append({
        "term": term,
        "timestamp": ts.strip(),
        "symbol": symbol,
        "values": values,
        "raw": raw[:200],
        "source": "trader.log",
    })


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="回填模式：全量扫描历史日志")
    parser.add_argument("--live", action="store_true", help="增量模式：只处理新增行")
    args = parser.parse_args()

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
                print(f"[WARN] 检测到日志轮转：已处理 {start} 行 > 当前 {total_lines} 行，重置状态从头扫描")
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

    print(f"[OK] 模式={'backfill' if args.backfill else 'live'} "
          f"扫描 {processed} 行, 产出 {len(events)} 条语义事件 → {OUT_PATH}")
    if events:
        by_term = {}
        for e in events:
            by_term[e["term"]] = by_term.get(e["term"], 0) + 1
        for t, n in sorted(by_term.items(), key=lambda kv: -kv[1]):
            print(f"     {t}: {n} 条")


if __name__ == "__main__":
    main()
