# -*- coding: utf-8 -*-
"""E1 测试集复核 Agent（SPEC v1.6 §2.2 / §7 P0）。

职责：对 `eval/e1_cases.jsonl` 做**可复现的机器复核**，把 `ai_draft` 推进到
`agent_verified` 或 `needs_review`，并输出人工可读报告。

复核项（全部确定性，零 LLM）：
  1. 标签一致性：`detect_intent_regex(message)` 与 `expected_intent` 是否一致；
  2. 路由一致性：`expected_route=L1` 但意图无执行器 → 冲突；
  3. 复合一致性：`segment=compound` 但 D5 判为非复合 → 冲突；
  4. 完全重复：归一化后同文；
  5. 近重复：字符 3-gram Jaccard ≥ 0.85（集内 + 与 intent_units 示例）；
  6. 配额统计：按分段/意图报告覆盖量。

用法：
  python3 34-前端应用训练系统/scripts/review_e1_cases.py            # 只出报告
  python3 34-前端应用训练系统/scripts/review_e1_cases.py --apply    # 另存复核后数据集
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_TRAIN_DIR = os.path.abspath(os.path.join(_HERE, ".."))
_ROOT = os.path.abspath(os.path.join(_TRAIN_DIR, ".."))
_SCRIPTS_DIR = os.path.join(_ROOT, "3.1-FRONTEND", "scripts")
for _p in (_TRAIN_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import l1_route_signal as lrs  # noqa: E402

CASES = os.path.join(_TRAIN_DIR, "eval", "e1_cases.jsonl")
OUT_DIR = os.path.join(_TRAIN_DIR, "eval", "review")
UNITS = os.path.join(_ROOT, "41-文件索引系统", "intent_units")
NEAR_DUP = 0.85
_PUNCT = re.compile(r"[\s，。、；：！？,.;:!?\"'“”‘’（）()\[\]【】<>《》]")


def _norm(s: str) -> str:
    return _PUNCT.sub("", (s or "").lower())


def _grams(s: str) -> set[str]:
    s = _norm(s)
    return {s[i : i + 3] for i in range(max(0, len(s) - 2))}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _near_dup(a: str, b: str) -> bool:
    """短文本（归一化后 <6 字）3-gram 噪声极大，不做近重复判定。"""
    if len(_norm(a)) < 6 or len(_norm(b)) < 6:
        return False
    return _jaccard(_grams(a), _grams(b)) >= NEAR_DUP


def _read_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_unit_messages() -> list[tuple[str, str]]:
    out = []
    if not os.path.isdir(UNITS):
        return out
    for name in os.listdir(UNITS):
        for fn in ("examples_zh.jsonl", "negatives_zh.jsonl"):
            path = os.path.join(UNITS, name, fn)
            if not os.path.exists(path):
                continue
            for r in _read_jsonl(path):
                msg = r.get("message", "")
                if msg:
                    out.append((name, msg))
    return out


def review(cases: list[dict], unit_msgs: list[tuple[str, str]]) -> list[dict]:
    norm_counter = Counter(_norm(c["message"]) for c in cases)
    unit_grams = [(name, msg, _grams(msg)) for name, msg in unit_msgs]
    out = []
    for c in cases:
        msg = c["message"]
        reasons: list[str] = []
        regex_intent = lrs.detect_intent_regex(msg)
        expected = c.get("expected_intent") or ""

        # 1) 标签一致性（按分段语义判定）
        seg = c.get("segment") or ""
        if expected:
            if seg == "semantic":
                # 口语段的设计前提：正则不应命中；命中说明分段标错（其实是数据类）
                if regex_intent:
                    reasons.append(f"regex_should_not_match:{regex_intent}")
            elif regex_intent == expected:
                pass
            elif regex_intent:
                reasons.append(f"intent_conflict:regex={regex_intent}")
            else:
                reasons.append("no_regex_match")

        # 2) 路由一致性
        if c.get("expected_route") == "L1":
            if expected and expected not in lrs.EXECUTORS:
                reasons.append("l1_without_executor")

        # 3) 复合一致性
        if c.get("segment") == "compound" and not lrs.is_compound_query(msg):
            reasons.append("compound_not_detected")

        # 4) 完全重复
        if norm_counter[_norm(msg)] > 1:
            reasons.append("exact_duplicate")

        # 5) 近重复（集内 + 意图单元）
        #    OOD 段（semantic/compound/trap/out_of_scope）禁止与样例撞车；
        #    data/clarify/regression 允许覆盖样例（in-distribution 回归保护）。
        ood_segment = seg in ("semantic", "compound", "trap", "out_of_scope")
        for other in cases:
            if other is c or _norm(other["message"]) == _norm(msg):
                continue
            if _near_dup(msg, other["message"]):
                reasons.append(f"near_dup_in_set:{other['id']}")
                break
        if ood_segment:
            for name, umsg, _ug in unit_grams:
                if _near_dup(msg, umsg):
                    reasons.append(f"near_dup_unit:{name}")
                    break

        out.append(
            {
                **c,
                "regex_intent": regex_intent,
                "review_reasons": reasons,
                "review_verdict": "agent_verified" if not reasons else "needs_review",
            }
        )
    return out


def report(rows: list[dict]) -> str:
    n = len(rows)
    ok = sum(1 for r in rows if r["review_verdict"] == "agent_verified")
    by_reason = Counter(reason.split(":")[0] for r in rows for reason in r["review_reasons"])
    by_seg = defaultdict(lambda: [0, 0])
    for r in rows:
        seg = by_seg[r["segment"]]
        seg[0] += 1
        if r["review_verdict"] == "agent_verified":
            seg[1] += 1
    lines = [
        "# E1 测试集复核报告（Agent）",
        "",
        f"- 样本数：{n}",
        f"- 通过：{ok}（{ok / n:.1%}）",
        f"- 待人工复核：{n - ok}（{(n - ok) / n:.1%}）",
        "",
        "## 按分段",
        "",
        "| 分段 | 总数 | 通过 | 通过率 |",
        "|---|---|---|---|",
    ]
    for seg, (total, passed) in sorted(by_seg.items()):
        lines.append(f"| {seg} | {total} | {passed} | {passed / total:.1%} |")
    lines += ["", "## 待复核原因分布", "", "| 原因 | 数量 |", "|---|---|"]
    for reason, cnt in by_reason.most_common():
        lines.append(f"| {reason} | {cnt} |")
    lines += ["", "## 待复核样例（最多 20 条）", ""]
    for r in [x for x in rows if x["review_verdict"] != "agent_verified"][:20]:
        lines.append(f"- `{r['id']}` {r['message']} → {', '.join(r['review_reasons'])}")
    lines += ["", "> 说明：复核结论由确定性规则产出；`golden` 仍需 10% 抽检人工确认。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="输出复核后数据集 e1_cases_reviewed.jsonl")
    args = ap.parse_args()

    cases = _read_jsonl(CASES)
    rows = review(cases, _load_unit_messages())
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(os.path.join(OUT_DIR, "e1_review.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    text = report(rows)
    with open(os.path.join(OUT_DIR, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)

    if args.apply:
        path = os.path.join(_TRAIN_DIR, "eval", "e1_cases_reviewed.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                r = dict(r)
                r["label_status"] = (
                    "agent_verified" if r["review_verdict"] == "agent_verified" else "needs_review"
                )
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"已输出: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
