#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战略层五维评分相关矩阵诊断（P1 诊断脚本，只计算不降权）。

目的：检测五维评分（dao/tian/di/jiang/fa）之间是否存在共线性。
若某两个维度的历史 Pearson 相关系数 |corr| > 0.8，标记为共线性嫌疑，
后续可考虑降权或合并。本脚本只诊断，不修改任何生产代码。

数据来源：复用 five_domain_ic_analysis._get_daily_snapshots 获取历史 coin_data 快照，
再用 FiveDomainFeatureComputer 计算五维评分时间序列。

用法：
    python five_domain_correlation_matrix.py
输出：
    runtime/five_domain_correlation_report.json
    runtime/five_domain_correlation_report.csv
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_RUNTIME = _HERE / "runtime"
_REPORT_JSON = _RUNTIME / "five_domain_correlation_report.json"
_REPORT_CSV = _RUNTIME / "five_domain_correlation_report.csv"

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from five_domain_ic_analysis import _get_daily_snapshots  # noqa: E402
from five_domain_feature_computer import FiveDomainFeatureComputer  # noqa: E402

# 共线性嫌疑阈值（|Pearson corr| > 此值 → 标记）
COLLINEARITY_THRESHOLD = 0.8

DIMENSIONS = ("dao", "tian", "di", "jiang", "fa")


def _compute_daily_scores() -> Dict[str, List[Dict[str, int]]]:
    """遍历历史快照，计算每类资产每天的五维评分。

    返回 {cls: [{dao, tian, di, jiang, fa}, ...]} 按日期升序。
    """
    snapshots = _get_daily_snapshots(_REPO / "18-数据获取中心" / "data_center.db")
    n_days = len(snapshots)
    print(f"[Corr] 快照天数: {n_days}")

    if n_days == 0:
        return {}

    computer = FiveDomainFeatureComputer(enable=True)
    result: Dict[str, List[Dict[str, int]]] = {}

    for date_str, coin_data_by_cls in snapshots:
        try:
            scores_by_cls = computer.compute(coin_data=coin_data_by_cls)
        except Exception:  # noqa: BLE001 — FAIL-OPEN：单天异常跳过
            continue
        for cls, scores in scores_by_cls.items():
            result.setdefault(cls, []).append(dict(scores))

    return result


def _pearson_corr(x: np.ndarray, y: np.ndarray) -> float:
    """计算 Pearson 相关系数。"""
    if len(x) < 3 or len(y) < 3:
        return 0.0
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    if len(x) < 3:
        return 0.0
    std_x, std_y = np.std(x), np.std(y)
    if std_x < 1e-9 or std_y < 1e-9:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def analyze_correlation() -> Dict[str, Any]:
    """主分析：计算每类资产的五维相关矩阵 + 共线性嫌疑对。"""
    daily_scores = _compute_daily_scores()

    report: Dict[str, Any] = {
        "n_days": sum(len(v) for v in daily_scores.values()) // max(len(daily_scores), 1),
        "collinearity_threshold": COLLINEARITY_THRESHOLD,
        "per_class": {},
        "summary": {"collinear_pairs": [], "total_pairs_checked": 0},
    }

    for cls, scores_list in daily_scores.items():
        if len(scores_list) < 5:
            report["per_class"][cls] = {
                "n_samples": len(scores_list),
                "correlation_matrix": None,
                "collinear_pairs": [],
                "note": f"样本不足（{len(scores_list)}<5），无法计算相关矩阵",
            }
            continue

        # 构造五维评分矩阵（行=日期，列=维度）
        dim_arrays: Dict[str, np.ndarray] = {}
        for dim in DIMENSIONS:
            dim_arrays[dim] = np.array([s[dim] for s in scores_list], dtype=float)

        # 计算相关矩阵
        corr_matrix: Dict[str, Dict[str, float]] = {}
        collinear_pairs: List[Dict[str, Any]] = []
        for i, d1 in enumerate(DIMENSIONS):
            corr_matrix[d1] = {}
            for d2 in DIMENSIONS:
                if d1 == d2:
                    corr_matrix[d1][d2] = 1.0
                elif d2 in corr_matrix and d1 in corr_matrix.get(d2, {}):
                    corr_matrix[d1][d2] = corr_matrix[d2][d1]
                else:
                    c = _pearson_corr(dim_arrays[d1], dim_arrays[d2])
                    corr_matrix[d1][d2] = round(c, 4)
                    if abs(c) > COLLINEARITY_THRESHOLD and i < DIMENSIONS.index(d2):
                        collinear_pairs.append({
                            "dim1": d1, "dim2": d2,
                            "correlation": round(c, 4),
                            "abs_correlation": round(abs(c), 4),
                        })

        report["per_class"][cls] = {
            "n_samples": len(scores_list),
            "correlation_matrix": corr_matrix,
            "collinear_pairs": collinear_pairs,
            "note": f"共线性嫌疑对: {len(collinear_pairs)}" if collinear_pairs else "无共线性嫌疑",
        }
        report["summary"]["collinear_pairs"].extend(
            {"asset_class": cls, **p} for p in collinear_pairs
        )

    report["summary"]["total_pairs_checked"] = sum(
        len(cls_data.get("collinear_pairs", []))
        for cls_data in report["per_class"].values()
    )
    return report


def save_report(report: Dict[str, Any]) -> tuple:
    """保存报告到 JSON + CSV。"""
    _RUNTIME.mkdir(parents=True, exist_ok=True)
    with open(_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # CSV 扁平化
    import csv
    rows = []
    for cls, cls_data in report["per_class"].items():
        matrix = cls_data.get("correlation_matrix") or {}
        for d1 in DIMENSIONS:
            row = {"asset_class": cls, "dimension": d1}
            for d2 in DIMENSIONS:
                row[d2] = matrix.get(d1, {}).get(d2)
            rows.append(row)
    if rows:
        with open(_REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["asset_class", "dimension"] + list(DIMENSIONS))
            writer.writeheader()
            writer.writerows(rows)

    return _REPORT_JSON, _REPORT_CSV


def print_summary(report: Dict[str, Any]) -> None:
    """打印诊断摘要。"""
    print("\n" + "=" * 80)
    print("战略层五维评分相关矩阵诊断报告")
    print("=" * 80)
    print(f"样本天数: {report['n_days']}")
    print(f"共线性阈值: |Pearson corr| > {report['collinearity_threshold']}")
    print("-" * 80)

    for cls, cls_data in report["per_class"].items():
        print(f"\n【{cls}】n={cls_data['n_samples']} — {cls_data['note']}")
        matrix = cls_data.get("correlation_matrix")
        if matrix:
            # 打印相关矩阵
            header = f"{'':>8}" + "".join(f"{d:>8}" for d in DIMENSIONS)
            print(header)
            for d1 in DIMENSIONS:
                row = f"{d1:>8}" + "".join(
                    f"{matrix[d1][d2]:>8.2f}" for d2 in DIMENSIONS
                )
                print(row)
            # 打印共线性嫌疑对
            for p in cls_data["collinear_pairs"]:
                print(f"  ⚠️  共线性嫌疑: {p['dim1']} ↔ {p['dim2']} = {p['correlation']:.4f}")

    print("-" * 80)
    total = report["summary"]["total_pairs_checked"]
    print(f"共线性嫌疑对总数: {total}")
    if total == 0:
        print("结论: 五维评分无显著共线性，无需降权。")
    else:
        print("结论: 存在共线性嫌疑，建议进一步评估降权或合并维度。")
    print(f"JSON 报告: {_REPORT_JSON}")
    print(f"CSV  报告: {_REPORT_CSV}")
    print("=" * 80)


if __name__ == "__main__":
    report = analyze_correlation()
    json_path, csv_path = save_report(report)
    print_summary(report)
    print(f"\n[Corr] 报告已保存: {json_path}")
