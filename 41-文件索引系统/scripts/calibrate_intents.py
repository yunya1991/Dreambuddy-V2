#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calibrate_intents.py — L1 语义意图校准（P2+P3，SPEC-41-L1 §2.5/§5）

P2 全局阈值校准：对 golden set 跑 ROC，确定 SEMANTIC_THRESHOLD_ZH，
  目标：正例通过率 ≥95%，反例误命中率 ≤2%。

P3 per-intent 校准 + uplift：对每个意图可评估单元跑 calibration
  （TPR≥95% / FPR≤2%）和 uplift 度量（有/无该意图向量的准确率差），
  uplift<0.02 标记待裁剪。

用法:
    python scripts/calibrate_intents.py
    python scripts/calibrate_intents.py --target-fpr 0.02 --min-tpr 0.95
    python scripts/calibrate_intents.py --json out.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_INDEX_ROOT = _HERE.parent
if str(_INDEX_ROOT) not in sys.path:
    sys.path.insert(0, str(_INDEX_ROOT))

from core.embedder_bridge import embed  # noqa: E402
from core.intent_calibrator import format_report, report_to_json, run_full_calibration  # noqa: E402
from core.intent_matcher import SEMANTIC_THRESHOLD_ZH, detect_lang  # noqa: E402
from core.intent_vector_store import IntentVectorStore  # noqa: E402

_GOLDEN = _INDEX_ROOT.parent / "34-前端应用训练系统" / "l1_intent_golden.jsonl"


def load_golden():
    """加载 golden set，返回 (positives, negatives)。

    positives: [(message, golden_intent), ...]
    negatives: [message, ...]  (intent == "unknown")
    """
    positives = []
    negatives = []
    with open(_GOLDEN, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            intent = obj.get("intent", "")
            msg = obj.get("message", "").strip()
            if not msg or len(msg) < 5:  # 对齐 detect_intent 的短消息门控
                continue
            if intent == "unknown":
                negatives.append(msg)
            else:
                positives.append((msg, intent))
    return positives, negatives


_REGEX_DETECTOR_SCRIPT = r"""
import json, os, sys
scripts_dir = sys.argv[1]
sys.path.insert(0, scripts_dir)
os.environ["L1_SEMANTIC_MATCH"] = "0"  # 纯正则模式，禁用语义通道
import l1_route_signal as lrs  # noqa: E402
msgs = json.loads(sys.stdin.read() or "[]")
out = [lrs.detect_intent(m) for m in msgs]
sys.stdout.write(json.dumps(out, ensure_ascii=False))
"""


def get_regex_detector(messages, python_bin=None):
    """通过子进程调用 l1_route_signal.detect_intent（纯正则模式）。

    用子进程而非直接 import，是为了避开 34/41 两个 `core` 包的命名空间冲突
    （calibrate_intents 已加载 41 的 core，l1_route_signal 需要 34 的 core）。
    子进程内设置 L1_SEMANTIC_MATCH=0，detect_intent 仅走正则通道。

    返回与 messages 等长的列表，元素为命中的 intent 字符串，未命中为 ""。
    """
    import shutil

    if python_bin is None:
        # 优先用与 l1_route_signal 测试一致的解释器（系统 anaconda python）
        python_bin = shutil.which("python3") or sys.executable
    scripts_dir = str(_INDEX_ROOT.parent / "3.1-FRONTEND" / "scripts")
    proc = subprocess.run(
        [python_bin, "-c", _REGEX_DETECTOR_SCRIPT, scripts_dir],
        input=json.dumps(messages, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"regex detector 子进程失败 (exit={proc.returncode}):\n{proc.stderr}")
    return json.loads(proc.stdout)


def compute_scores(positives, negatives, store):
    """对每条示例计算 max_sim（所有意图中最高余弦相似度）。"""
    pos_scores = []  # (message, golden_intent, max_sim, top1_intent)
    neg_scores = []  # (message, max_sim, top1_intent)

    for msg, golden_intent in positives:
        lang = detect_lang(msg)
        vec = embed(msg, lang=lang)
        if not vec:
            continue
        results = store.search(vec, lang=lang, top_k=3)
        if results:
            max_sim = results[0][1]
            top1 = results[0][0]
        else:
            max_sim = 0.0
            top1 = None
        pos_scores.append((msg, golden_intent, max_sim, top1))

    for msg in negatives:
        lang = detect_lang(msg)
        vec = embed(msg, lang=lang)
        if not vec:
            continue
        results = store.search(vec, lang=lang, top_k=3)
        if results:
            max_sim = results[0][1]
            top1 = results[0][0]
        else:
            max_sim = 0.0
            top1 = None
        neg_scores.append((msg, max_sim, top1))

    return pos_scores, neg_scores


def roc_analysis(pos_scores, neg_scores, thresholds=None):
    """ROC 分析：对每个阈值计算 TPR/FPR。"""
    if thresholds is None:
        thresholds = [i / 100 for i in range(30, 96)]  # 0.30 ~ 0.95

    pos_sims = [s[2] for s in pos_scores]
    neg_sims = [s[1] for s in neg_scores]

    results = []
    for t in thresholds:
        tpr = sum(1 for s in pos_sims if s >= t) / len(pos_sims) if pos_sims else 0
        fpr = sum(1 for s in neg_sims if s >= t) / len(neg_sims) if neg_sims else 0
        results.append((round(t, 2), round(tpr, 4), round(fpr, 4)))
    return results


def find_optimal_threshold(roc, min_tpr=0.95, max_fpr=0.02):
    """找最优阈值：满足 TPR ≥ min_tpr 且 FPR ≤ max_fpr 的最大 TPR。"""
    candidates = [r for r in roc if r[1] >= min_tpr and r[2] <= max_fpr]
    if not candidates:
        # 放宽约束：找 FPR ≤ max_fpr 中 TPR 最高的
        candidates = [r for r in roc if r[2] <= max_fpr]
    if not candidates:
        # 再放宽：找 TPR ≥ min_tpr 中 FPR 最低的
        candidates = [r for r in roc if r[1] >= min_tpr]
    if not candidates:
        return None
    # 优先 TPR 最高，其次 FPR 最低
    candidates.sort(key=lambda x: (-x[1], x[2]))
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description="L1 语义意图校准（P2 全局阈值 + P3 per-intent）")
    parser.add_argument("--min-tpr", type=float, default=0.95, help="最小正例通过率")
    parser.add_argument("--max-fpr", type=float, default=0.02, help="最大反例误命中率")
    parser.add_argument(
        "--threshold",
        type=float,
        default=SEMANTIC_THRESHOLD_ZH,
        help=f"per-intent 校准用的语义阈值（默认 {SEMANTIC_THRESHOLD_ZH}）",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        metavar="OUT.json",
        help="输出 per-intent calibration + uplift JSON 报表到指定文件",
    )
    parser.add_argument(
        "--skip-roc", action="store_true", help="跳过 P2 全局 ROC 分析，仅跑 P3 per-intent 校准"
    )
    args = parser.parse_args()

    print("加载 golden set...")
    positives, negatives = load_golden()
    print(f"  正例（已知意图）: {len(positives)} 条")
    print(f"  反例（unknown）: {len(negatives)} 条")

    # 先跑正则通道，区分正例中哪些被正则命中（不需要语义兜底）
    print("\n运行正则通道（纯正则模式，L1_SEMANTIC_MATCH=0）...")
    pos_messages = [p[0] for p in positives]
    regex_hits = get_regex_detector(pos_messages)
    regex_missed_idx = [i for i, h in enumerate(regex_hits) if not h]
    n_regex_hit = len(positives) - len(regex_missed_idx)
    print(f"  正则命中: {n_regex_hit} 条（占正例 {n_regex_hit/len(positives):.1%}）")
    print(f"  正则漏过: {len(regex_missed_idx)} 条（语义通道需兜底的正例）")

    # 构建 {message: regex_intent} 字典（正例 + 反例全量），供 per-intent 校准计入正则命中
    all_messages = pos_messages + list(negatives)
    all_regex = get_regex_detector(all_messages)
    regex_results = dict(zip(all_messages, all_regex, strict=True))

    print("\n计算语义相似度...")
    store = IntentVectorStore()
    store.load()
    pos_scores, neg_scores = compute_scores(positives, negatives, store)

    if not args.skip_roc:
        _run_p2_roc(args, positives, negatives, regex_hits, pos_scores, neg_scores)

    # ===== P3: per-intent calibration + uplift =====
    print(f"\n{'='*80}")
    print("P3: per-intent 校准 + uplift（阈值={:.2f}）".format(args.threshold))
    print("=" * 80)
    calib_results = run_full_calibration(
        store=store,
        threshold=args.threshold,
        lang="zh",
        regex_results=regex_results,
    )
    print(format_report(calib_results))

    if args.json:
        out_path = Path(args.json)
        out_path.write_text(
            json.dumps(report_to_json(calib_results), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON 报表已写入: {out_path}")


def _run_p2_roc(args, positives, negatives, regex_hits, pos_scores, neg_scores):
    """P2 全局 ROC 分析（阈值校准）。"""
    regex_missed_idx = [i for i, h in enumerate(regex_hits) if not h]
    n_regex_hit = len(positives) - len(regex_missed_idx)

    # 有效正例 = 正则漏过的正例（语义通道真正需要接住的）
    eff_pos_scores = [pos_scores[i] for i in regex_missed_idx]
    print(
        f"\n正例 max_sim 统计（全部 {len(pos_scores)} 条）: "
        f"min={min(s[2] for s in pos_scores):.3f}, "
        f"max={max(s[2] for s in pos_scores):.3f}, "
        f"mean={sum(s[2] for s in pos_scores)/len(pos_scores):.3f}"
    )
    if eff_pos_scores:
        print(
            f"有效正例 max_sim 统计（正则漏过 {len(eff_pos_scores)} 条）: "
            f"min={min(s[2] for s in eff_pos_scores):.3f}, "
            f"max={max(s[2] for s in eff_pos_scores):.3f}, "
            f"mean={sum(s[2] for s in eff_pos_scores)/len(eff_pos_scores):.3f}"
        )
    print(
        f"反例 max_sim 统计: min={min(s[1] for s in neg_scores):.3f}, "
        f"max={max(s[1] for s in neg_scores):.3f}, "
        f"mean={sum(s[1] for s in neg_scores)/len(neg_scores):.3f}"
    )

    print("\n=== ROC 分析（有效正例 = 正则漏过的正例）===")
    print("语义通道只在正则未命中时触发，因此 TPR 只统计正则漏过的正例。")
    roc = roc_analysis(eff_pos_scores, neg_scores)
    for t, tpr, fpr in roc:
        marker = ""
        if tpr >= args.min_tpr and fpr <= args.max_fpr:
            marker = "  <-- 满足约束"
        elif tpr >= args.min_tpr:
            marker = "  (TPR达标, FPR超)"
        elif fpr <= args.max_fpr:
            marker = "  (FPR达标, TPR不足)"
        print(f"  {t:.2f} → TPR={tpr:.4f}, FPR={fpr:.4f}{marker}")

    optimal = find_optimal_threshold(roc, min_tpr=args.min_tpr, max_fpr=args.max_fpr)
    if optimal:
        t, tpr, fpr = optimal
        print(f"\n{'='*60}")
        print(f"最优阈值: {t:.2f}")
        print(f"  有效 TPR={tpr:.4f} (正则漏过正例的语义命中率, 目标≥{args.min_tpr})")
        print(f"  FPR={fpr:.4f} (反例误命中率, 目标≤{args.max_fpr})")
        regex_cov = n_regex_hit / len(positives)
        e2e_cov = regex_cov + (1 - regex_cov) * tpr
        print(
            f"  端到端正例覆盖率 = 正则{regex_cov:.1%} + 语义兜底{(1-regex_cov)*tpr:.1%} = {e2e_cov:.1%}"
        )
        print(f"{'='*60}")
    else:
        print(f"\n未找到满足约束的阈值（min_tpr={args.min_tpr}, max_fpr={args.max_fpr}）")

    print("\n反例误命中详情（max_sim 排序，用于补充负例训练）:")
    neg_sorted = sorted(neg_scores, key=lambda x: x[1], reverse=True)
    for msg, sim, top1 in neg_sorted[:10]:
        print(f'  [{sim:.3f}] {top1:20s} ← "{msg}"')


if __name__ == "__main__":
    main()
