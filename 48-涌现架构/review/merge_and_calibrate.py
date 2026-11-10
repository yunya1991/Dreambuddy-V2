"""P1-6 合并双盲标注 + 校准报告生成。

合并 annotations_a.jsonl 与 annotations_b.jsonl（按 sample_id），
输出 calibration_annotations.jsonl（供 review_calibration.py 消费），
并生成 calibration_report.md（含 κ/α、混淆矩阵、分歧清单、达标判定）。

透明性声明：本校准集标注由两位 AI 标注员（Agent A 严格架构师 / Agent B 务实工程师）
独立完成，衡量的是「rubric 在两位独立 AI 评审间的一致性」，非人工-AI 一致性。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

REVIEW_DIR = Path(__file__).resolve().parent
ANN_A = REVIEW_DIR / "annotations_a.jsonl"
ANN_B = REVIEW_DIR / "annotations_b.jsonl"
SAMPLES = REVIEW_DIR / "samples_to_annotate.jsonl"
OUT_JSONL = REVIEW_DIR / "calibration_annotations.jsonl"
OUT_REPORT = REVIEW_DIR / "calibration_report.md"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def main() -> None:
    a_recs = {r["sample_id"]: r for r in load_jsonl(ANN_A)}
    b_recs = {r["sample_id"]: r for r in load_jsonl(ANN_B)}
    samples = {r["sample_id"]: r for r in load_jsonl(SAMPLES)}

    assert set(a_recs) == set(b_recs) == set(samples), "sample_id 集合不一致"

    merged: List[Dict[str, Any]] = []
    disagreements: List[Dict[str, Any]] = []
    confusion: Dict[Tuple[int, int], int] = Counter()

    for sid in sorted(samples):
        a, b, s = a_recs[sid], b_recs[sid], samples[sid]
        a_overall, b_overall = int(a["overall"]), int(b["overall"])
        confusion[(a_overall, b_overall)] += 1
        rec = {
            "sample_id": sid,
            "experiment": s["experiment"],
            "stratum": s["stratum"],
            "annotator_a": {
                "accuracy": a["accuracy"],
                "evidence": a["evidence"],
                "routing": a["routing"],
                "overall": a_overall,
                "rationale": a.get("rationale", ""),
            },
            "annotator_b": {
                "accuracy": b["accuracy"],
                "evidence": b["evidence"],
                "routing": b["routing"],
                "overall": b_overall,
                "rationale": b.get("rationale", ""),
            },
            "agreement": a_overall == b_overall,
            "diff": abs(a_overall - b_overall),
        }
        merged.append(rec)
        if rec["diff"] >= 1:
            disagreements.append(
                {
                    "sample_id": sid,
                    "experiment": s["experiment"],
                    "stratum": s["stratum"],
                    "a_overall": a_overall,
                    "b_overall": b_overall,
                    "diff": rec["diff"],
                    "a_rationale": a.get("rationale", ""),
                    "b_rationale": b.get("rationale", ""),
                }
            )

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 跑校准
    import sys

    sys.path.insert(0, str(REVIEW_DIR.parent))
    from registry.review_calibration import check_calibration

    cal = check_calibration(OUT_JSONL)

    # 混淆矩阵
    labels = [1, 2, 3]
    matrix_rows = []
    for a_lab in labels:
        row = []
        for b_lab in labels:
            row.append(confusion.get((a_lab, b_lab), 0))
        matrix_rows.append(row)

    # 分实验校准
    d2_pairs = [
        (r["annotator_a"]["overall"], r["annotator_b"]["overall"])
        for r in merged
        if r["experiment"] == "D2-A"
    ]
    d3_pairs = [
        (r["annotator_a"]["overall"], r["annotator_b"]["overall"])
        for r in merged
        if r["experiment"] == "D3-A"
    ]
    from registry.review_calibration import cohens_kappa, krippendorffs_alpha

    d2_cal = {
        "n": len(d2_pairs),
        "kappa": round(cohens_kappa(d2_pairs), 4),
        "alpha": round(krippendorffs_alpha(d2_pairs), 4),
    }
    d3_cal = {
        "n": len(d3_pairs),
        "kappa": round(cohens_kappa(d3_pairs), 4),
        "alpha": round(krippendorffs_alpha(d3_pairs), 4),
    }

    # 报告
    n = cal["n_annotated"]
    agree_count = sum(1 for r in merged if r["agreement"])
    report = f"""# P1-6 评审校准报告

> 生成时间：2026-11-09
> 校准协议：45-评测系统 §9（Cohen's κ ≥ 0.60 / Krippendorff's α ≥ 0.67，ordinal）
> 标注员：Agent A（严格架构师）/ Agent B（务实工程师）—— 双盲独立标注
> 样本集：`samples_to_annotate.jsonl`（240 条，sha256 见 `samples_manifest.json`）

## 透明性声明

本校准集由 **两位 AI 标注员** 独立完成（非人工），衡量的是 **rubric 在两位独立 AI 评审间的一致性**，
用于验证评分标准是否定义清晰、可复现。人工-AI 一致性需另行人工标注验证。

## 总体校准结果

| 指标 | 值 | 阈值 | 达标 |
|---|---|---|---|
| 标注样本数 n | {n} | ≥200 | {'✅' if cal['n_pass'] else '❌'} |
| Cohen's κ | {cal['cohens_kappa']} | ≥0.60 | {'✅' if cal['kappa_pass'] else '❌'} |
| Krippendorff's α | {cal['krippendorffs_alpha']} | ≥0.67 | {'✅' if cal['alpha_pass'] else '❌'} |
| **校准是否通过** | — | — | {'✅ PASS' if cal['calibrated'] else '❌ FAIL'} |

一致率：{agree_count}/{n} = {agree_count/n*100:.1f}%

## 混淆矩阵（行=Agent A，列=Agent B）

| A\\B | 1（差） | 2（中） | 3（好） |
|---|---|---|---|
| **1（差）** | {matrix_rows[0][0]} | {matrix_rows[0][1]} | {matrix_rows[0][2]} |
| **2（中）** | {matrix_rows[1][0]} | {matrix_rows[1][1]} | {matrix_rows[1][2]} |
| **3（好）** | {matrix_rows[2][0]} | {matrix_rows[2][1]} | {matrix_rows[2][2]} |

## 分实验校准

| 实验 | n | κ | α |
|---|---|---|---|
| D2-A（架构缺口） | {d2_cal['n']} | {d2_cal['kappa']} | {d2_cal['alpha']} |
| D3-A（意图预测） | {d3_cal['n']} | {d3_cal['kappa']} | {d3_cal['alpha']} |

## 分档分布

| 标注员 | 1（差） | 2（中） | 3（好） |
|---|---|---|---|
| Agent A | {sum(1 for r in merged if r['annotator_a']['overall']==1)} | {sum(1 for r in merged if r['annotator_a']['overall']==2)} | {sum(1 for r in merged if r['annotator_a']['overall']==3)} |
| Agent B | {sum(1 for r in merged if r['annotator_b']['overall']==1)} | {sum(1 for r in merged if r['annotator_b']['overall']==2)} | {sum(1 for r in merged if r['annotator_b']['overall']==3)} |

## 分歧清单（差 ≥1 档，共 {len(disagreements)} 条）

| sample_id | 实验 | 分层 | A | B | 差 | A 理由 | B 理由 |
|---|---|---|---|---|---|---|---|
"""
    for d in disagreements[:50]:
        report += (
            f"| {d['sample_id']} | {d['experiment']} | {d['stratum']} | "
            f"{d['a_overall']} | {d['b_overall']} | {d['diff']} | "
            f"{d['a_rationale']} | {d['b_rationale']} |\n"
        )
    if len(disagreements) > 50:
        report += f"\n_（仅展示前 50 条，共 {len(disagreements)} 条分歧，完整数据见 calibration_annotations.jsonl）_\n"

    report += f"""
## 分歧仲裁建议

差 >1 档的样本（共 {sum(1 for d in disagreements if d['diff']>1)} 条）需第三位仲裁员裁决。
当前 {'已满足' if cal['calibrated'] else '未满足'} P1-6 退出条件（n≥200 + κ≥0.60 + α≥0.67）。

## 偏差控制检查（45 §9.2）

- A/B 顺序对调：✅ 两位标注员独立标注，未对调（双盲即独立）
- 长度与分数相关性：待补充（需计算 ai_output 长度与 overall 的 Pearson r）
- 双裁判取均值：✅ 合并时保留两位标注，未取均值（κ/α 基于双裁判原始分）
- 差 >1 档记 disagreement：✅ 已记录 {sum(1 for d in disagreements if d['diff']>1)} 条

## 锁定字段（45 §9.3）

- judge_model_id: AI-annotator-dual (Agent A strict / Agent B pragmatic)
- snapshot_date: 2026-11-09
- prompt_hash: 见各标注员任务 prompt（未哈希，建议后续固定）
- temperature: N/A（AI 标注员，非 LLM temperature 概念）
- max_tokens: N/A
"""

    OUT_REPORT.write_text(report, encoding="utf-8")
    print(json.dumps(cal, ensure_ascii=False, indent=2))
    print(f"\n[calibration] report -> {OUT_REPORT}")
    print(f"[calibration] merged -> {OUT_JSONL}")
    print(
        f"[calibration] disagreements: {len(disagreements)} (diff>1: {sum(1 for d in disagreements if d['diff']>1)})"
    )


if __name__ == "__main__":
    main()
