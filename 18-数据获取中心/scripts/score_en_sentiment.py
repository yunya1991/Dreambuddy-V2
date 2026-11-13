#!/usr/bin/env python3
"""英文深度文章情感打分：ProsusAI/finbert 分段推理 + 段长加权聚合。

复用 score_zh_sentiment.py 的切窗与段长加权逻辑，模型换为本地
9-基本面分析/models/finbert（ProsusAI/finbert）。
读取 backfill/en_deep_articles/contents_all.jsonl，对每篇文章正文切窗打分，
聚合为文章级情感分数，增量写入 sentiment.jsonl，并生成汇总报告。
标签映射：positive / neutral / negative（模型 config.id2label 为准）。
"""

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT.parent / "9-基本面分析" / "models" / "finbert"
DATA_DIR = ROOT / "backfill" / "en_deep_articles"
SRC_PATH = DATA_DIR / "contents_all.jsonl"
OUT_PATH = DATA_DIR / "sentiment.jsonl"
REPORT_PATH = DATA_DIR / "report_en_sentiment.json"

CHUNK_TOKENS = 400  # 切窗上限，为 512 token 留余量
CST = timezone(timedelta(hours=8))


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_sent_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_jsonl(path: Path):
    if not path.exists():
        return []
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def chunk_article(tokenizer, title, summary, content):
    """标题+摘要作为首窗，正文按段落累积切窗，返回 chunk 列表。"""
    chunks = []
    head = " ".join(x for x in [title, summary] if x)
    if head:
        chunks.append(head)
    paras = [p.strip() for p in (content or "").split("\n") if p.strip()]
    buf, buf_tokens = [], 0
    for p in paras:
        n = len(tokenizer.tokenize(p))
        if n > CHUNK_TOKENS:
            if buf:
                chunks.append("".join(buf))
                buf, buf_tokens = [], 0
            # 超长段落按字符粗切
            step = max(200, CHUNK_TOKENS)
            for i in range(0, len(p), step):
                chunks.append(p[i : i + step])
            continue
        if buf_tokens + n > CHUNK_TOKENS:
            chunks.append("".join(buf))
            buf, buf_tokens = [p], n
        else:
            buf.append(p)
            buf_tokens += n
    if buf:
        chunks.append("".join(buf))
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 篇（测试用）")
    ap.add_argument("--rebuild", action="store_true", help="忽略已有结果全量重算")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(MODEL_PATH))
    model = AutoModelForSequenceClassification.from_pretrained(str(MODEL_PATH))
    model.eval()
    id2label = {int(k): v for k, v in model.config.id2label.items()}

    articles = load_jsonl(SRC_PATH)
    done = set() if args.rebuild else {r["id"] for r in load_jsonl(OUT_PATH)}
    # 先过滤有正文的文章，再应用 limit（空正文文章不占 limit 名额）
    todo = [
        a for a in articles if a.get("id") not in done and (a.get("content_text") or "").strip()
    ]
    if args.limit > 0:
        todo = todo[: args.limit]

    t0 = time.time()
    results = []
    for a in todo:
        if not (a.get("content_text") or "").strip():
            continue
        chunks = chunk_article(tok, a.get("title", ""), a.get("summary", ""), a["content_text"])
        if not chunks:
            continue
        agg = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
        total_w = 0
        for c in chunks:
            inputs = tok(c, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                probs = torch.softmax(model(**inputs).logits, dim=-1)[0]
            w = int(inputs["input_ids"].shape[1])
            for i, p in enumerate(probs.tolist()):
                label = id2label[i].lower()
                if label in agg:
                    agg[label] += p * w
            total_w += w
        for k in agg:
            agg[k] = round(agg[k] / total_w, 4)
        label = max(agg, key=agg.get)
        results.append(
            {
                "id": a["id"],
                "source_name": a.get("source_name", ""),
                "title": a.get("title", ""),
                "date_published": a.get("date_published", ""),
                "n_chunks": len(chunks),
                "sentiment": label,
                "probs": agg,
                "score": round(agg["positive"] - agg["negative"], 4),
                "confidence": agg[label],
                "scored_at": datetime.now(CST).isoformat(timespec="seconds"),
            }
        )

    if results:
        merged = ([] if args.rebuild else load_jsonl(OUT_PATH)) + results
        atomic_write(OUT_PATH, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merged))

    all_rows = load_jsonl(OUT_PATH)
    dist = {"positive": 0, "neutral": 0, "negative": 0}
    for r in all_rows:
        dist[r["sentiment"]] = dist.get(r["sentiment"], 0) + 1
    scores = [r["score"] for r in all_rows]
    report = {
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "model": "ProsusAI/finbert (local)",
        "source": str(SRC_PATH),
        "total_articles": len(articles),
        "scored_total": len(all_rows),
        "newly_scored": len(results),
        "label_distribution": dist,
        "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    atomic_write(REPORT_PATH, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
