#!/usr/bin/env python3
"""intent_expansion_proposer.py — R-1 意图扩展提案器（spec v0.5 §7 P3）
====================================================================
未覆盖意图发现 → 案例聚类 → 候选意图提案全自动生成（P3 验收：案例聚类到提案全自动）。

子命令（stdin JSON → stdout JSON，FAIL-OPEN）：

1. discover：未覆盖意图发现
   案例库中 intent 为 need_clarification/simple_qa 或规则引擎无命中的案例
   → 提取高频特征词 → 关键词共现聚类 → 输出候选意图簇

2. propose：候选意图提案生成
   输入候选簇（discover 产出或人工指定）→ 生成提案文档
   （id/name/description/keywords/examples/规则 hc_*/澄清选项/所属分层）
   → 写入提案目录（proposals/，待人工评审，合入保留人工批准）

3. full：discover + propose 一键全链路（P3 验收演示）
"""
import json
import os
import re
import sys
from datetime import datetime

CASE_STORE = "/home/luke/dreambuddy/34-前端应用训练系统/l1_case_store.jsonl"
FE_PATH = "/home/luke/dreambuddy/3.1-FRONTEND/src/lib/intent/fallback-engine.ts"
PROPOSAL_DIR = "/home/luke/dreambuddy/34-前端应用训练系统/proposals"

# 未覆盖意图标记：这些意图的案例代表识别系统未能分派到具体意图
UNCOVERED_INTENTS = {"need_clarification", "simple_qa"}

# 停用词（聚类时排除）
STOPWORDS = {"的", "了", "是", "我", "你", "他", "她", "它", "们", "在", "有", "和", "与",
             "或", "也", "就", "都", "而", "及", "把", "被", "这个", "那个", "什么", "怎么",
             "帮我", "一下", "看看", "请问", "还是", "可以", "能", "会", "要", "想"}


def parse_rules() -> list:
    with open(FE_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    rules = []
    for m in re.finditer(
        r"\{\s*id:\s*'(hc_[a-z_]+)',\s*intent:\s*'([a-z_]+)',.*?keywords:\s*\[([^\]]*)\]",
        src, re.S,
    ):
        rid, intent, kw_raw = m.groups()
        rules.append({"id": rid, "intent": intent,
                      "keywords": re.findall(r"'([^']+)'", kw_raw)})
    return rules


def match_engine(message: str, rules: list):
    lower = message.lower()
    for rule in rules:
        for kw in rule["keywords"]:
            if kw.lower() in lower:
                return rule["intent"]
    return None


def extract_terms(message: str) -> list:
    """中文分词：jieba 分词 + 停用词过滤（消除 n-gram 滑窗碎片词噪声）。

    FAIL-OPEN：jieba 不可用时回退 2-4 字滑窗（零依赖兜底）。
    """
    try:
        import jieba
        words = [w.strip() for w in jieba.lcut(message) if w.strip()]
        # 过滤：停用词、单字、纯数字、纯 ASCII 单字母
        terms = [w for w in words
                 if w not in STOPWORDS and len(w) >= 2 and not w.isdigit()]
        return terms
    except ImportError:
        # FAIL-OPEN：回退滑窗
        terms = []
        for n in (2, 3, 4):
            for i in range(len(message) - n + 1):
                t = message[i:i + n]
                if t not in STOPWORDS and not t.isdigit():
                    terms.append(t)
        return terms


def load_uncovered_cases() -> list:
    """加载未覆盖意图案例：UNCOVERED_INTENTS 标记 + 规则引擎无命中。"""
    rules = parse_rules()
    cases = []
    if not os.path.exists(CASE_STORE):
        return cases
    with open(CASE_STORE, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                c = json.loads(ln)
            except Exception:
                continue
            msg = str(c.get("message") or "").strip()
            if not msg:
                continue
            intent = c.get("intent") or ""
            if intent in UNCOVERED_INTENTS:
                cases.append({"message": msg, "intent": intent, "reason": "uncovered_intent"})
            elif intent and match_engine(msg, rules) is None:
                cases.append({"message": msg, "intent": intent, "reason": "no_rule_hit"})
    return cases


def cmd_discover(req: dict) -> dict:
    """未覆盖意图发现：特征词共现聚类 → 候选意图簇。"""
    min_cluster = int(req.get("min_cluster") or 3)
    cases = load_uncovered_cases()
    if not cases:
        return {"success": True, "uncovered_cases": 0, "clusters": [],
                "note": "无未覆盖意图案例"}
    # 特征词频统计
    term_msgs = {}
    for c in cases:
        for t in set(extract_terms(c["message"])):
            term_msgs.setdefault(t, []).append(c["message"])
    # 候选簇：特征词出现在 ≥min_cluster 条消息中
    clusters = []
    used = set()
    for term, msgs in sorted(term_msgs.items(), key=lambda x: -len(x[1])):
        if len(msgs) < min_cluster or term in used:
            continue
        # 合并消息重叠度高的簇（Jaccard > 0.5 视为同簇）
        merged = False
        for cl in clusters:
            overlap = len(set(msgs) & set(cl["messages"])) / max(1, len(set(msgs) | set(cl["messages"])))
            if overlap > 0.5:
                cl["terms"].append(term)
                used.add(term)
                merged = True
                break
        if not merged:
            clusters.append({"terms": [term], "messages": list(dict.fromkeys(msgs))})
    return {"success": True, "uncovered_cases": len(cases),
            "min_cluster": min_cluster,
            "clusters": [{"terms": cl["terms"], "case_count": len(cl["messages"]),
                         "samples": cl["messages"][:5]} for cl in clusters]}


def _gen_intent_id(terms: list, seq: int) -> str:
    """从特征词生成候选意图 id（非 ASCII 时用序号兜底）。"""
    base = re.sub(r"[^a-z0-9]", "", (terms[0] if terms else "new").lower()[:8])
    return f"candidate_{base or 'intent'}_{seq}"


def cmd_propose(req: dict) -> dict:
    """候选意图提案生成：簇 → 提案文档（写入 proposals/，待人工评审）。"""
    clusters = req.get("clusters") or []
    if not clusters:
        return {"success": False, "error": "missing clusters"}
    os.makedirs(PROPOSAL_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    proposals = []
    for i, cl in enumerate(clusters, 1):
        terms = cl.get("terms") or []
        messages = cl.get("messages") or cl.get("samples") or []
        if not terms or not messages:
            continue
        intent_id = _gen_intent_id(terms, i)
        proposal = {
            "proposal_id": f"prop_{ts}_{i}",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "R-1 intent_expansion_proposer（自动生成，待人工评审）",
            "intent": {
                "id": intent_id,
                "name": f"候选意图：{terms[0]}相关",
                "description": f"从 {len(messages)} 条未覆盖案例聚类发现，特征词：{'、'.join(terms[:5])}。描述待人工评审补充。",
                "keywords": terms[:8],
                "examples": messages[:4],
                "rule": {"id": f"hc_{intent_id}", "keywords": terms[:8],
                         "confidence": 0.8, "complexity": "simple"},
                "layer": "L0",
            },
            "evidence": {"case_count": cl.get("case_count") or len(messages),
                         "samples": messages[:5]},
            "review": {"status": "pending", "reviewer": None,
                       "checklist": ["描述完备性", "与现有 15 种意图边界无重叠",
                                     "回归测试全绿（含 holdout）"]},
        }
        path = os.path.join(PROPOSAL_DIR, f"{proposal['proposal_id']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(proposal, f, ensure_ascii=False, indent=2)
        proposals.append({"proposal_id": proposal["proposal_id"],
                          "intent_id": intent_id, "path": path})
    return {"success": True, "proposals": proposals,
            "note": "提案已写入 proposals/ 目录，合入需人工评审批准（spec §5④）"}


def cmd_full(req: dict) -> dict:
    """全链路：discover → propose（P3 验收演示）。"""
    disc = cmd_discover(req)
    if not disc.get("success"):
        return disc
    if not disc.get("clusters"):
        return {"success": True, "stage": "discover", "result": disc,
                "note": "无候选簇，提案跳过"}
    prop = cmd_propose({"clusters": disc["clusters"]})
    return {"success": prop.get("success", False), "stage": "full",
            "discover": {"uncovered_cases": disc.get("uncovered_cases"),
                         "cluster_count": len(disc.get("clusters") or [])},
            "propose": prop}


_COMMANDS = {"discover": cmd_discover, "propose": cmd_propose, "full": cmd_full}


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
