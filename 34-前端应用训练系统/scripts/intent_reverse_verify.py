#!/usr/bin/env python3
"""intent_reverse_verify.py — P2 逆向验证管线（spec v0.5 §5③/§7 P2）
======================================================================
四个子命令（stdin JSON → stdout JSON，FAIL-OPEN）：

1. conflict-detect：规则冲突检测
   解析 fallback-engine.ts 规则表 → 关键词重叠分析 → 泛化词抢占检测
   （防『超预期』类边界重叠复发：短词/泛化词被多条规则共享即告警）

2. misidentify-attribution：误识别归因
   输入 {message, expected_intent} → 回放规则命中链路 → 定位抢先命中的
   冲突规则 → 输出修复建议（关键词收紧/顺序调整）

3. negative-grow：负例自动生长（M4）
   归因产出 → 自动转化为回归负例 → 追加 intent-regression.jsonl
   （人工审核：追加行带 auto_generated: true 标记）

4. replay-simulate：回放模拟训练（FreqAI backtesting 机制）
   历史案例库按时间序重放 → 模拟多轮扩展闭环 → 各轮通过率趋势报告
   （检测闭环持续运行后的模型退化与自增强偏差走向）

5. rule-hit-stats：规则命中率统计
   案例库中各 hc_* 规则命中计数 → 长期零命中规则进入废弃评审名单
"""
import json
import os
import re
import sys
from datetime import datetime

FE_PATH = "/home/luke/dreambuddy/3.1-FRONTEND/src/lib/intent/fallback-engine.ts"
REGRESSION_PATH = "/home/luke/dreambuddy/3.1-FRONTEND/tests/data/intent-regression.jsonl"
CASE_STORE = "/home/luke/dreambuddy/34-前端应用训练系统/l1_case_store.jsonl"

# 泛化词黑名单：单字/双字高频词易抢占具体意图（源自 market_query 泛化词修复经验）
GENERIC_WORD_MAX_LEN = 2
# 强意图动作词白名单：交易动作动词，单一规则独占（hc_execute_trade）、
# 回归案例正确归因（买入1个BTC/做空SOL 均正确命中）、无跨规则抢占，不视为泛化词
STRONG_ACTION_WORDS = {'开仓', '下单', '买入', '卖出', '做多', '做空', '加仓', '减仓', '平仓'}


def parse_rules() -> list:
    """解析 fallback-engine.ts 的 HARDCODED_INTENT_RULES 规则表。"""
    with open(FE_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    rules = []
    # 逐规则块：id → intent → keywords
    for m in re.finditer(
        r"\{\s*id:\s*'(hc_[a-z_]+)',\s*intent:\s*'([a-z_]+)',.*?keywords:\s*\[([^\]]*)\]",
        src, re.S,
    ):
        rid, intent, kw_raw = m.groups()
        keywords = re.findall(r"'([^']+)'", kw_raw)
        rules.append({"id": rid, "intent": intent, "keywords": keywords})
    return rules


def match_engine(message: str, rules: list):
    """回放规则引擎顺序匹配（对齐 matchRuleEngine：lower.includes 顺序命中）。"""
    lower = message.lower()
    for rule in rules:
        for kw in rule["keywords"]:
            if kw.lower() in lower:
                return {"matched_rule": rule["id"], "matched_intent": rule["intent"],
                        "matched_keyword": kw, "position": rule["keywords"].index(kw)}
    return None


def cmd_conflict_detect(req: dict) -> dict:
    """规则冲突检测：关键词重叠 + 泛化词抢占。"""
    rules = parse_rules()
    if len(rules) < 10:
        return {"success": False, "error": f"规则表解析异常：仅 {len(rules)} 条"}
    findings = []
    # 1. 关键词重叠：同一关键词出现在多条规则
    kw_owners = {}
    for r in rules:
        for kw in r["keywords"]:
            kw_owners.setdefault(kw, []).append(r["id"])
    for kw, owners in kw_owners.items():
        if len(owners) > 1:
            findings.append({"type": "keyword_overlap", "keyword": kw, "rules": owners,
                             "severity": "high" if len(owners) > 2 else "medium"})
    # 2. 泛化词抢占：短泛化词（≤2 字）作为命中关键词
    for r in rules:
        for kw in r["keywords"]:
            if 0 < len(kw) <= GENERIC_WORD_MAX_LEN and not kw.isascii() and kw not in STRONG_ACTION_WORDS:
                findings.append({"type": "generic_word", "keyword": kw, "rule": r["id"],
                                 "severity": "medium",
                                 "suggestion": f"{r['id']} 的关键词『{kw}』过短易抢占具体意图，建议收紧"})
    # 3. 子串包含：某规则关键词是另一规则关键词的子串（短词先命中抢占长词）
    for a in rules:
        for b in rules:
            if a["id"] == b["id"]:
                continue
            for ka in a["keywords"]:
                for kb in b["keywords"]:
                    if ka != kb and ka in kb and len(ka) >= 2:
                        findings.append({"type": "substring_preempt", "short": ka, "long": kb,
                                         "short_rule": a["id"], "long_rule": b["id"],
                                         "severity": "low"})
    return {"success": True, "rules_parsed": len(rules), "findings": findings,
            "summary": {"keyword_overlap": sum(1 for f in findings if f["type"] == "keyword_overlap"),
                        "generic_word": sum(1 for f in findings if f["type"] == "generic_word"),
                        "substring_preempt": sum(1 for f in findings if f["type"] == "substring_preempt")}}


def cmd_misidentify_attribution(req: dict) -> dict:
    """误识别归因：回放命中链路，定位冲突规则。"""
    message = str(req.get("message") or "").strip()
    expected = str(req.get("expected_intent") or "").strip()
    if not message or not expected:
        return {"success": False, "error": "missing message/expected_intent"}
    rules = parse_rules()
    hit = match_engine(message, rules)
    if hit is None:
        return {"success": True, "message": message, "expected_intent": expected,
                "actual": None, "attribution": "无规则命中（走 LLM/澄清链路），非规则冲突"}
    if hit["matched_intent"] == expected:
        return {"success": True, "message": message, "expected_intent": expected,
                "actual": hit, "attribution": "识别正确，无需归因"}
    # 定位冲突：期望意图的规则中哪些关键词也在消息中（被抢先规则遮蔽）
    expected_rules = [r for r in rules if r["intent"] == expected]
    masked = []
    lower = message.lower()
    for r in expected_rules:
        for kw in r["keywords"]:
            if kw.lower() in lower:
                masked.append({"rule": r["id"], "keyword": kw})
    suggestion = None
    if hit["matched_keyword"] and len(hit["matched_keyword"]) <= GENERIC_WORD_MAX_LEN:
        suggestion = f"抢先规则 {hit['matched_rule']} 的关键词『{hit['matched_keyword']}』为泛化词，建议移除或收紧"
    elif masked:
        suggestion = f"期望意图规则 {masked[0]['rule']} 排序靠后被遮蔽，建议调整规则顺序"
    return {"success": True, "message": message, "expected_intent": expected,
            "actual": hit, "masked_expected_rules": masked, "suggestion": suggestion}


def cmd_negative_grow(req: dict) -> dict:
    """负例自动生长：归因产出 → 回归测试集追加（auto_generated 标记，人工审核）。"""
    message = str(req.get("message") or "").strip()
    expected = str(req.get("expected_intent") or "").strip()
    note = str(req.get("note") or "误识别归因产出")
    if not message or not expected:
        return {"success": False, "error": "missing message/expected_intent"}
    case = {"schema_version": "v1", "case_type": "negative", "intent": expected,
            "message": message, "expected_entities": {}, "holdout": False,
            "auto_generated": True, "note": note,
            "generated_at": datetime.now().isoformat(timespec="seconds")}
    with open(REGRESSION_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(case, ensure_ascii=False) + "\n")
    return {"success": True, "appended": True, "case": case,
            "note": "已追加（auto_generated 标记），请人工审核后保留"}


def cmd_replay_simulate(req: dict) -> dict:
    """回放模拟训练：历史案例库按时间序重放，各轮通过率趋势。"""
    rules = parse_rules()
    cases = []
    if os.path.exists(CASE_STORE):
        with open(CASE_STORE, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    c = json.loads(ln)
                except Exception:
                    continue
                if c.get("intent") and c.get("message"):
                    cases.append(c)
    if not cases:
        return {"success": False, "error": "案例库无可重放案例"}
    # 按时间序分轮重放（每轮 20 条），统计规则引擎通过率趋势
    batch, rounds, per = 20, [], 0
    for i in range(0, len(cases), batch):
        chunk = cases[i:i + batch]
        hit_ok = sum(1 for c in chunk
                     if (h := match_engine(c["message"], rules)) and h["matched_intent"] == c.get("intent"))
        rounds.append({"round": per + 1, "cases": len(chunk), "rule_hits": hit_ok,
                       "pass_rate": round(hit_ok / len(chunk), 4) if chunk else 0.0})
        per += 1
    trend = [r["pass_rate"] for r in rounds]
    return {"success": True, "total_cases": len(cases), "rounds": rounds,
            "trend": trend,
            "trend_direction": "improving" if len(trend) >= 2 and trend[-1] > trend[0] else
                               ("declining" if len(trend) >= 2 and trend[-1] < trend[0] else "stable")}


def cmd_rule_hit_stats(req: dict) -> dict:
    """规则命中率统计：案例库各规则命中计数，零命中规则进废弃评审名单。"""
    rules = parse_rules()
    if os.path.exists(CASE_STORE):
        with open(CASE_STORE, "r", encoding="utf-8") as f:
            cases = [json.loads(ln) for ln in f if ln.strip()]
    else:
        cases = []
    hit_counts = {r["id"]: 0 for r in rules}
    for c in cases:
        h = match_engine(str(c.get("message") or ""), rules)
        if h:
            hit_counts[h["matched_rule"]] = hit_counts.get(h["matched_rule"], 0) + 1
    zero_hit = [rid for rid, n in hit_counts.items() if n == 0]
    return {"success": True, "total_cases": len(cases), "hit_counts": hit_counts,
            "zero_hit_rules": zero_hit,
            "deprecation_review": zero_hit,
            "note": "零命中规则进入废弃评审名单（人工评审后处置）"}


_COMMANDS = {
    "conflict-detect": cmd_conflict_detect,
    "misidentify-attribution": cmd_misidentify_attribution,
    "negative-grow": cmd_negative_grow,
    "replay-simulate": cmd_replay_simulate,
    "rule-hit-stats": cmd_rule_hit_stats,
}


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "invalid json"}))
        return 1
    cmd = str(req.get("cmd") or "").strip()
    fn = _COMMANDS.get(cmd)
    if fn is None:
        print(json.dumps({"success": False, "error": f"unknown cmd: {cmd}",
                         "available": sorted(_COMMANDS)}))
        return 1
    try:
        print(json.dumps(fn(req), ensure_ascii=False))
        return 0
    except Exception as e:  # FAIL-OPEN
        print(json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
