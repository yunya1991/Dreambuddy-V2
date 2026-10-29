#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unified_corpus_processor.py — 统一语料处理器（UCP, SPEC v1.0）
======================================================================
将全系统异构数据处理为分层训练语料（SPEC-v1.0-unified-corpus-processor.md）。

用法：
    venv-trading/bin/python scripts/unified_corpus_processor.py run [--max-pretrain N]
    venv-trading/bin/python scripts/unified_corpus_processor.py stats

产出（34 系统 corpus/ 目录）：
    pretrain_corpus.jsonl    预训练语料（MLM）
    intent_pairs.jsonl       意图分类对
    query_doc_pairs.jsonl   对比学习对
    evaluator_labels.jsonl   评测器 verdict 监督数据
    corpus_stats.json       处理统计

FAIL-OPEN：单源处理失败跳过并计数，不中断整体。
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
_REPO = os.path.dirname(_SYS_DIR)
CORPUS_DIR = os.path.join(_SYS_DIR, "corpus")

# ---------- 数据源清单（SPEC §2 价值分层） ----------
INTENT_PAIR_SOURCES = [
    os.path.join(_SYS_DIR, "l1_case_store.jsonl"),
    os.path.join(_REPO, "3.1-FRONTEND", "tests", "data", "intent-regression.jsonl"),
]
QUERY_DOC_SOURCES = [
    os.path.join(_REPO, "2-KNOWLEDGE", "9-RAG-INFRA", "bridge", "retrieval_memory_map.jsonl"),
]
LOG_STREAM_SOURCES = (
    glob.glob(os.path.join(_REPO, "11-易经推理系统", "data", "polling_trader", "trader_*.jsonl"))
    + [os.path.join(_REPO, "11-易经推理系统", ".workbuddy", "memory_l4", "guardian", "alerts.jsonl")]
)
EVENT_STREAM_SOURCES = [
    os.path.join(_REPO, "39-金融语义蒸馏系统", "semantic_events.jsonl"),
    os.path.join(_REPO, "33-REA逆向解析工程", "reflection_data", "training_cases.jsonl"),
]
MARKDOWN_GLOBS = [
    os.path.join(_REPO, "*", "SPEC*.md"),
    os.path.join(_REPO, "*", "README.md"),
    os.path.join(_REPO, "*", "docs", "*.md"),
]
PROPOSALS_GLOB = os.path.join(_SYS_DIR, "proposals", "prop_*.json")
CHECKPOINTS_PATH = os.path.join(_REPO, "3.1-FRONTEND", ".training-checkpoints", "checkpoints.json")

# ---------- 清洗规则（SPEC §3.2） ----------
SENSITIVE_PATTERNS = [
    re.compile(r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+", re.I),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]
MIN_PRETRAIN_LEN = 10
MIN_INTENT_MSG_LEN = 4

# 意图对噪声标签过滤（v1.1：session.*/窗口/影子规则/测试用例类标签非业务意图）
NOISE_INTENT_PATTERNS = [
    re.compile(r"^session\..+"),
    re.compile(r"^trader_log\.window_.+"),
    re.compile(r"^shadow\..+"),
    re.compile(r"^execution_loop_.*"),
    re.compile(r"^(a[0-9]|oneirology|seminar)\..+"),
    re.compile(r"^CS-\d+"),
]


def is_noise_intent(intent: str) -> bool:
    return any(p.match(intent or "") for p in NOISE_INTENT_PATTERNS)


def sanitize(text: str) -> str:
    for pat in SENSITIVE_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text.strip()


def text_key(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()


def iter_jsonl(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                STATS["bad_lines"] += 1


STATS = Counter()


# ---------- 适配器 1: intent_pair（SPEC §3.1） ----------
def collect_intent_pairs(out, seen):
    n = 0
    for path in INTENT_PAIR_SOURCES:
        for d in iter_jsonl(path):
            msg, intent = d.get("message"), d.get("intent")
            if not (isinstance(msg, str) and isinstance(intent, str)):
                continue
            if is_noise_intent(intent):
                STATS["intent_noise_filtered"] += 1
                continue
            if len(msg) < MIN_INTENT_MSG_LEN:
                continue
            k = text_key(msg + "|" + intent)
            if k in seen:
                continue
            seen.add(k)
            out.write(json.dumps({"message": sanitize(msg), "intent": intent, "source": os.path.basename(path)}, ensure_ascii=False) + "\n")
            n += 1
    # 训练检查点 semanticSamples（意图键 → 消息列表）
    if os.path.exists(CHECKPOINTS_PATH):
        try:
            with open(CHECKPOINTS_PATH, "r", encoding="utf-8") as f:
                ck = json.load(f)
            ss = ck.get("store", {}).get("S", [])
            if ss:
                for intent, msgs in (ss[-1].get("state", {}).get("semanticSamples", {}) or {}).items():
                    if is_noise_intent(intent):
                        STATS["intent_noise_filtered"] += 1
                        continue
                    for msg in msgs or []:
                        if not isinstance(msg, str) or len(msg) < MIN_INTENT_MSG_LEN:
                            continue
                        k = text_key(msg + "|" + intent)
                        if k in seen:
                            continue
                        seen.add(k)
                        out.write(json.dumps({"message": sanitize(msg), "intent": intent, "source": "checkpoints.semanticSamples"}, ensure_ascii=False) + "\n")
                        n += 1
        except Exception:
            STATS["checkpoint_error"] += 1
    return n


# ---------- 适配器 1b: newsflash 快讯（v1.1：星球日报快讯 → 意图对 + 预训练语料） ----------
def collect_newsflash(intent_out, pretrain_out, seen_intent, seen_pretrain):
    """从 18 中心 PG data_center.records 读取星球日报快讯（newsflash_*）。
    生成：1) 事件类型识别意图对（正文 → news_event，event_type 天然标签）
          2) 预训练语料（快讯正文，清洗 HTML）
    FAIL-OPEN：PG 不可达返回 0，不阻塞。"""
    n_ip, n_pt = 0, 0
    try:
        sys.path.insert(0, os.path.join(_REPO, "39-金融语义蒸馏系统", "scripts"))
        import psycopg2
        pwd = ""
        env_path = os.path.join(_REPO, "7-产物中台", "系统研究索引体系", ".env")
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                m = re.search(r"postgresql://[^:\s]+:([^@\s]+)@", f.read())
                if m:
                    pwd = m.group(1)
        except Exception:
            pass
        conn = psycopg2.connect(
            host=os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
            port=int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
            user=os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
            password=os.environ.get("DATA_CENTER_PG_PASSWORD", pwd),
            dbname=os.environ.get("DATA_CENTER_PG_DB", "data_center"),
            connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT sub_category, metrics FROM records WHERE sub_category LIKE 'newsflash_%%' ORDER BY id"
        )
        for sub_cat, metrics in cur.fetchall():
            try:
                m = metrics if isinstance(metrics, dict) else json.loads(metrics)
            except Exception:
                STATS["newsflash_bad"] += 1
                continue
            desc = re.sub(r"<[^>]+>", "", str(m.get("description") or "")).strip()
            desc = re.sub(r"^Odaily星球日报讯\s*", "", desc).strip()
            if len(desc) < MIN_PRETRAIN_LEN:
                continue
            # 预训练语料
            k = text_key(desc)
            if k not in seen_pretrain:
                seen_pretrain.add(k)
                pretrain_out.write(json.dumps({"text": sanitize(desc), "source": sub_cat}, ensure_ascii=False) + "\n")
                n_pt += 1
            # 事件类型意图对（天然标签）
            etype = m.get("od_event_type") or m.get("event_type") or ""
            if etype and len(desc) >= MIN_INTENT_MSG_LEN:
                ik = text_key(desc + "|news_event:" + etype)
                if ik not in seen_intent:
                    seen_intent.add(ik)
                    intent_out.write(json.dumps({"message": sanitize(desc), "intent": "news_event", "event_type": etype, "source": sub_cat}, ensure_ascii=False) + "\n")
                    n_ip += 1
        conn.close()
    except Exception:
        STATS["newsflash_error"] += 1
        return 0, 0
    return n_ip, n_pt


# ---------- 适配器 2: query_doc（SPEC §3.1） ----------
def collect_query_doc_pairs(out, seen, limit=20000):
    n = 0
    for path in QUERY_DOC_SOURCES:
        for d in iter_jsonl(path):
            q, h = d.get("query"), d.get("heading")
            src = d.get("source_file")
            if not (isinstance(q, str) and isinstance(h, str) and src):
                continue
            k = text_key(q + "|" + h)
            if k in seen:
                continue
            seen.add(k)
            out.write(json.dumps({"query": sanitize(q), "document": sanitize(h), "source_file": src}, ensure_ascii=False) + "\n")
            n += 1
            if n >= limit:
                return n
    return n


# ---------- 适配器 3: log_stream（SPEC §3.1） ----------
def collect_log_stream(pretrain_out, seen):
    n = 0
    for path in LOG_STREAM_SOURCES:
        for d in iter_jsonl(path):
            msg = d.get("msg") or d.get("message")
            if not isinstance(msg, str):
                continue
            msg = sanitize(msg)
            if len(msg) < MIN_PRETRAIN_LEN:
                continue
            k = text_key(msg)
            if k in seen:  # 模板去重（SPEC §3.2 规则 1）
                STATS["dedup_log"] += 1
                continue
            seen.add(k)
            pretrain_out.write(json.dumps({"text": msg, "source": os.path.basename(path)}, ensure_ascii=False) + "\n")
            n += 1
    return n


# ---------- 适配器 4: event_stream（SPEC §3.1） ----------
def collect_event_stream(pretrain_out, seen):
    n = 0
    for path in EVENT_STREAM_SOURCES:
        for d in iter_jsonl(path):
            text = d.get("raw") or d.get("term")
            if isinstance(text, str):
                text = sanitize(text)
                if len(text) >= MIN_PRETRAIN_LEN:
                    k = text_key(text)
                    if k not in seen:
                        seen.add(k)
                        pretrain_out.write(json.dumps({"text": text, "source": os.path.basename(path)}, ensure_ascii=False) + "\n")
                        n += 1
            # training_cases 的 payload 文本
            payload = d.get("payload")
            if isinstance(payload, dict):
                for v in payload.values():
                    if isinstance(v, str) and len(v) >= MIN_PRETRAIN_LEN:
                        v = sanitize(v)
                        k = text_key(v)
                        if k not in seen:
                            seen.add(k)
                            pretrain_out.write(json.dumps({"text": v, "source": os.path.basename(path)}, ensure_ascii=False) + "\n")
                            n += 1
    return n


# ---------- 适配器 5: markdown_doc（SPEC §3.1，按章节切分） ----------
def collect_markdown(pretrain_out, seen):
    n = 0
    files = []
    for g in MARKDOWN_GLOBS:
        files.extend(glob.glob(g))
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            STATS["md_read_error"] += 1
            continue
        # 按二级/三级标题切分章节
        sections = re.split(r"\n(?=#{2,3} )", content)
        for sec in sections:
            sec = sanitize(sec)
            if len(sec) < 50:
                continue
            k = text_key(sec[:200])
            if k in seen:
                continue
            seen.add(k)
            rel = os.path.relpath(path, _REPO)
            pretrain_out.write(json.dumps({"text": sec[:2000], "source": rel}, ensure_ascii=False) + "\n")
            n += 1
    return n


# ---------- 评测器监督数据（提案 verdict） ----------
def collect_evaluator_labels(out):
    n = 0
    for path in sorted(glob.glob(PROPOSALS_GLOB)):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            r = d.get("review") or {}
            if r.get("status") != "reviewed":
                continue
            verdict = r.get("verdict")
            if verdict not in ("recommend", "hold", "reject"):
                continue
            intent = d.get("intent") or {}
            out.write(json.dumps({
                "proposal_id": d.get("proposal_id") or os.path.basename(path),
                "name": intent.get("name", ""),
                "description": intent.get("description", ""),
                "keywords": intent.get("keywords", []),
                "examples": intent.get("examples", [])[:5],
                "metrics": r.get("metrics", {}),
                "reasons": r.get("reasons", [])[:5],
                "verdict": verdict,
            }, ensure_ascii=False) + "\n")
            n += 1
        except Exception:
            STATS["proposal_error"] += 1
    return n


# ---------- 主流程 ----------
def cmd_run(max_pretrain=None):
    os.makedirs(CORPUS_DIR, exist_ok=True)
    seen_intent, seen_qd, seen_pretrain = set(), set(), set()
    with open(os.path.join(CORPUS_DIR, "intent_pairs.jsonl"), "w", encoding="utf-8") as f_ip, \
         open(os.path.join(CORPUS_DIR, "query_doc_pairs.jsonl"), "w", encoding="utf-8") as f_qd, \
         open(os.path.join(CORPUS_DIR, "pretrain_corpus.jsonl"), "w", encoding="utf-8") as f_pt, \
         open(os.path.join(CORPUS_DIR, "evaluator_labels.jsonl"), "w", encoding="utf-8") as f_ev:
        STATS["intent_pairs"] = collect_intent_pairs(f_ip, seen_intent)
        nf_ip, nf_pt = collect_newsflash(f_ip, f_pt, seen_intent, seen_pretrain)
        STATS["newsflash_intent_pairs"] = nf_ip
        STATS["newsflash_pretrain"] = nf_pt
        STATS["query_doc_pairs"] = collect_query_doc_pairs(f_qd, seen_qd)
        STATS["log_stream"] = collect_log_stream(f_pt, seen_pretrain)
        STATS["event_stream"] = collect_event_stream(f_pt, seen_pretrain)
        STATS["markdown_sections"] = collect_markdown(f_pt, seen_pretrain)
        STATS["evaluator_labels"] = collect_evaluator_labels(f_ev)
    # 预训练语料截断（SPEC §5 硬件约束：≤10 万句）
    pt_path = os.path.join(CORPUS_DIR, "pretrain_corpus.jsonl")
    if max_pretrain:
        with open(pt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        STATS["pretrain_truncated_from"] = len(lines)
        with open(pt_path, "w", encoding="utf-8") as f:
            f.writelines(lines[:max_pretrain])
        STATS["pretrain_final"] = min(len(lines), max_pretrain)
    else:
        STATS["pretrain_final"] = sum(1 for _ in open(pt_path, encoding="utf-8"))
    with open(os.path.join(CORPUS_DIR, "corpus_stats.json"), "w", encoding="utf-8") as f:
        json.dump({"stats": dict(STATS), "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds")}, f, ensure_ascii=False, indent=2)
    print(json.dumps(dict(STATS), ensure_ascii=False, indent=2))
    return 0


def cmd_stats():
    p = os.path.join(CORPUS_DIR, "corpus_stats.json")
    if not os.path.exists(p):
        print("corpus 未生成，请先运行 run")
        return 1
    print(open(p, encoding="utf-8").read())
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "stats"])
    ap.add_argument("--max-pretrain", type=int, default=100000)
    args = ap.parse_args()
    if args.cmd == "run":
        return cmd_run(args.max_pretrain)
    return cmd_stats()


if __name__ == "__main__":
    sys.exit(main())
