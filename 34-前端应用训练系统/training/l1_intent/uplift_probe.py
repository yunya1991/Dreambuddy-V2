# -*- coding: utf-8 -*-
"""P4 前置：线性探针 uplift 验证（SPEC v1.6 §7 P4）。

目的：在不动 bge 主干、不引入 GPU 训练的前提下，判断「同一套 embedding 上
换更强的判别头」能否显著提升 OOD 意图识别。若线性探针都拿不到 uplift，
则领域微调的性价比极低，P4 应终止。

基线：kNN（生产向量检索的近似）——最近邻样本投票得 top1/top3。
候选：LogisticRegression（21 意图 + none 拒识类）在同一 embedding 上训练。
判定：OOD top1 uplift ≥ 0.02 且 McNemar p < 0.05 → 值得微调。

用法：python3 34-前端应用训练系统/training/l1_intent/uplift_probe.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_TRAIN_DIR = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ROOT = os.path.abspath(os.path.join(_TRAIN_DIR, ".."))
for _p in (os.path.join(_ROOT, "3.1-FRONTEND", "scripts"), os.path.join(_ROOT, "41-文件索引系统")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import l1_route_signal as lrs  # noqa: E402

# l1_route_signal 以独立包名加载 41 core，复用同一实例避免重复加载模型
embed_batch = sys.modules["_l1_semantic_core.embedder_bridge"].embed_batch

DATASETS = os.path.join(_HERE, "datasets")
OUT = os.path.join(_HERE, "snapshots", date.today().strftime("%Y%m%d"))


def _read(name: str) -> list[dict]:
    path = os.path.join(DATASETS, name)
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def _embed(msgs: list[str], cache: dict[str, list[float]]) -> np.ndarray:
    todo = sorted({m for m in msgs if m not in cache})
    for i in range(0, len(todo), 64):
        chunk = todo[i : i + 64]
        vecs = embed_batch([lrs.normalize_aliases(m) for m in chunk], lang="zh")
        for m, v in zip(chunk, vecs, strict=False):
            cache[m] = v
    arr = np.array([cache[m] for m in msgs], dtype=np.float32)
    return arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)


def _knn_topk(
    train_x: np.ndarray, train_y: list[str], x: np.ndarray, k: int = 3
) -> list[list[str]]:
    sims = x @ train_x.T  # (n, m)
    out = []
    for row in sims:
        best: dict[str, float] = {}
        for idx in np.argsort(-row)[: max(10, k * 3)]:
            label = train_y[int(idx)]
            best[label] = max(best.get(label, -1.0), float(row[int(idx)]))
        out.append([i for i, _ in sorted(best.items(), key=lambda kv: -kv[1])][:k])
    return out


def _mcnemar_p(b: int, c: int) -> float:
    from scipy.stats import binomtest

    if b + c == 0:
        return 1.0
    return binomtest(min(b, c), b + c, 0.5).pvalue


def main() -> int:
    cache: dict[str, list[float]] = {}
    train_rows = [r for r in _read("in_dist.jsonl") if r.get("expected_intent")]
    ood = [r for r in _read("ood_spoken.jsonl") if r.get("expected_intent")]
    hold = [r for r in _read("holdout.jsonl") if r.get("expected_intent")]

    tr_x = _embed([r["message"] for r in train_rows], cache)
    tr_y = [r["expected_intent"] for r in train_rows]

    from sklearn.linear_model import LogisticRegression

    clf = LogisticRegression(max_iter=3000, C=4.0, class_weight="balanced")
    clf.fit(tr_x, tr_y)
    classes = list(clf.classes_)

    def probe(x: np.ndarray, k: int = 3) -> list[list[str]]:
        proba = clf.predict_proba(x)
        idx = np.argsort(-proba, axis=1)[:, :k]
        return [[classes[int(j)] for j in row] for row in idx]

    result = {"date": date.today().isoformat(), "n_train": len(train_rows)}
    base_acc = {}
    for name, rows in (("ood", ood), ("holdout", hold)):
        x = _embed([r["message"] for r in rows], cache)
        y = [r["expected_intent"] for r in rows]
        base = _knn_topk(tr_x, tr_y, x)
        cand = probe(x)
        b1 = np.mean([p[0] == t for p, t in zip(base, y, strict=False)])
        c1 = np.mean([p[0] == t for p, t in zip(cand, y, strict=False)])
        b3 = np.mean([t in p[:3] for p, t in zip(base, y, strict=False)])
        c3 = np.mean([t in p[:3] for p, t in zip(cand, y, strict=False)])
        # McNemar
        b = sum(1 for pb, pc, t in zip(base, cand, y, strict=False) if pb[0] != t and pc[0] == t)
        c = sum(1 for pb, pc, t in zip(base, cand, y, strict=False) if pb[0] == t and pc[0] != t)
        base_acc[name] = {
            "n": len(y),
            "knn_top1": round(float(b1), 4),
            "probe_top1": round(float(c1), 4),
            "knn_top3": round(float(b3), 4),
            "probe_top3": round(float(c3), 4),
            "uplift_top1": round(float(c1 - b1), 4),
            "uplift_top3": round(float(c3 - b3), 4),
            "mcnemar_b": b,
            "mcnemar_c": c,
            "p_value": round(float(_mcnemar_p(b, c)), 4),
        }
    result["metrics"] = base_acc

    o = base_acc["ood"]
    result["decision"] = {
        "uplift_ok": o["uplift_top1"] >= 0.02,
        "significant": o["p_value"] < 0.05,
        "verdict": (
            "值得微调" if (o["uplift_top1"] >= 0.02 and o["p_value"] < 0.05) else "不建议微调"
        ),
    }

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "uplift_probe.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    lines = [
        "# P4 线性探针 uplift 报告",
        "",
        f"训练样本：{len(train_rows)}（in_dist 正例）",
        "",
        "| 集 | n | kNN top1 | 探针 top1 | uplift | kNN top3 | 探针 top3 | McNemar p |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in ("ood", "holdout"):
        m = base_acc[name]
        lines.append(
            f"| {name} | {m['n']} | {m['knn_top1']:.1%} | {m['probe_top1']:.1%} | "
            f"{m['uplift_top1']:+.1%} | {m['knn_top3']:.1%} | {m['probe_top3']:.1%} | {m['p_value']} |"
        )
    lines += ["", f"**结论：{result['decision']['verdict']}**"]
    with open(os.path.join(OUT, "UPLIFT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
