# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P2：术语-语义广泛对应（零 token）

对五大术语表（indicator/strategy/theory/finance/algorithm，共 1454 条）做
真实交易日志全文检索，统计每条术语的实操活跃度，产出 term_semantic_map.json：
  - 每条术语挂接：文档定义（第一圈）+ 实操语义（第二圈 practical_semantics）+ 日志出现次数
  - 活跃度三层分层：
      high_freq  高频实操（occurrences >= 100，优先深化）
      documented 文档术语（1 <= occurrences < 100，日志低频出现）
      dormant    零活跃（occurrences = 0，候选清理）

数据源：
  - /home/luke/logs/yijing/trader.log（真实交易主日志）
  - practical_semantics.json（第二圈实操语义归纳产物）

产出: term_semantic_map.json
用法: python3 gen_term_semantic_map.py
"""
import json
import os
import subprocess
import sys
from collections import defaultdict

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)

TERM_FILES = [
    "indicator_terms.json",
    "strategy_terms.json",
    "theory_terms.json",
    "finance_terms.json",
    "algorithm_terms.json",
    "people_terms.json",
    "tokenomics_terms.json",
    "sector_terms.json",
    "macro_terms.json",
]
TRADER_LOG = "/home/luke/logs/yijing/trader.log"
PRACTICAL_PATH = os.path.join(_SYS_DIR, "practical_semantics.json")
OUT_PATH = os.path.join(_SYS_DIR, "term_semantic_map.json")

HIGH_FREQ_THRESHOLD = 100  # 高频实操阈值


def load_terms():
    """读取五大术语表，返回 [(domain, term, definition, source, quality)]"""
    all_terms = []
    for fname in TERM_FILES:
        path = os.path.join(_SYS_DIR, fname)
        if not os.path.exists(path):
            print(f"[WARN] 术语表缺失: {fname}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        domain = data.get("domain", fname.split("_terms")[0])
        for t in data.get("terms", []):
            all_terms.append((
                domain,
                t.get("term", ""),
                t.get("definition", ""),
                t.get("source", ""),
                t.get("quality", ""),
            ))
    return all_terms


def count_occurrences(terms):
    """用 grep -o -F -f 对 trader.log 做固定字符串多模式计数。

    术语含正则元字符，必须用 -F；多模式 grep 走 Aho-Corasick，209M 日志可分钟级完成。
    过滤长度 < 2 的术语（单字符误匹配率高）。
    """
    counts = defaultdict(int)
    patterns = [t for t in terms if len(t) >= 2]
    skipped = [t for t in terms if len(t) < 2]
    if skipped:
        print(f"[WARN] 跳过 {len(skipped)} 条长度<2 的术语（误匹配风险）: {skipped[:5]}")
    if not os.path.exists(TRADER_LOG):
        print(f"[ERROR] 日志不存在: {TRADER_LOG}")
        sys.exit(1)
    tmp = os.path.join(_THIS_DIR, ".term_patterns.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(patterns))
    try:
        proc = subprocess.Popen(
            ["grep", "-o", "-F", "-f", tmp, TRADER_LOG],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        n_lines = 0
        for raw in proc.stdout:
            term = raw.decode("utf-8", errors="ignore").rstrip("\n")
            if term:
                counts[term] += 1
                n_lines += 1
        proc.wait()
        print(f"[OK] 日志扫描完成: 匹配输出 {n_lines} 行")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return counts


def main():
    all_terms = load_terms()
    print(f"[OK] 载入术语 {len(all_terms)} 条")
    counts = count_occurrences([t[1] for t in all_terms])

    practical = {}
    if os.path.exists(PRACTICAL_PATH):
        with open(PRACTICAL_PATH, "r", encoding="utf-8") as f:
            practical = json.load(f).get("terms", {})

    layers = {"high_freq": [], "documented": [], "dormant": []}
    entries = []
    for domain, term, definition, source, quality in all_terms:
        occ = counts.get(term, 0)
        if occ >= HIGH_FREQ_THRESHOLD:
            layer = "high_freq"
        elif occ >= 1:
            layer = "documented"
        else:
            layer = "dormant"
        entry = {
            "term": term,
            "domain": domain,
            "definition": definition,
            "doc_source": source,
            "doc_quality": quality,
            "log_occurrences": occ,
            "activity_layer": layer,
        }
        if term in practical:
            p = practical[term]
            entry["practical_semantics"] = {
                "occurrences": p.get("occurrences"),
                "top_values": p.get("top_values"),
                "source": p.get("source"),
            }
        entries.append(entry)
        layers[layer].append(term)

    out = {
        "generated_at": "2026-10-20",
        "log_source": TRADER_LOG,
        "total_terms": len(entries),
        "layer_definition": {
            "high_freq": f"log_occurrences >= {HIGH_FREQ_THRESHOLD}（高频实操，优先深化）",
            "documented": "1 <= log_occurrences < 100（文档术语，日志低频出现）",
            "dormant": "log_occurrences = 0（零活跃，候选清理）",
        },
        "layer_summary": {
            "high_freq": len(layers["high_freq"]),
            "documented": len(layers["documented"]),
            "dormant": len(layers["dormant"]),
        },
        "terms": entries,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[OK] P2 术语-语义广泛对应完成: {len(entries)} 条 -> {OUT_PATH}")
    print(f"     高频实操: {len(layers['high_freq'])} | 文档术语: {len(layers['documented'])} | 零活跃: {len(layers['dormant'])}")
    dormant_by_domain = defaultdict(int)
    for e in entries:
        if e["activity_layer"] == "dormant":
            dormant_by_domain[e["domain"]] += 1
    for d, n in sorted(dormant_by_domain.items(), key=lambda kv: -kv[1]):
        print(f"     零活跃[{d}]: {n} 条")
    top = sorted(entries, key=lambda e: -e["log_occurrences"])[:10]
    print("     高频 top10: " + ", ".join(f"{e['term']}({e['log_occurrences']})" for e in top))


if __name__ == "__main__":
    main()
