#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 影子比对：11 系统原位置战略层 vs 43 模块（迁移等价性验证）。

方法：同输入并行运行两侧 FiveDomainFeatureComputer.compute()，
逐资产类逐维度比对五维分数，计算一致率。
退出标准（SPEC v1.1 §六 P3）：一致率 >= 85%。
前提：CYCLE_STATE_BRIDGE 未设置（43 侧承接开关关闭，验证纯迁移等价性）。
"""
import importlib.util
import json
import os
import sys

# 43 侧：以正规包方式导入（承接开关默认关闭，相对导入不触发）
_43_ROOT = "/home/luke/dreambuddy/43-战略承接推演层"
if _43_ROOT not in sys.path:
    sys.path.insert(0, _43_ROOT)
from strategic_extension.five_domain_feature_computer import FiveDomainFeatureComputer as FDC43  # noqa: E402

# 11 侧：原位置以正规模块方式导入（其内部依赖同目录 strategy_algo_layer 等模块）
_11_DIR = "/home/luke/dreambuddy/11-易经推理系统/scripts/memory_l4"
if _11_DIR not in sys.path:
    sys.path.insert(0, _11_DIR)
import five_domain_feature_computer as _m11  # noqa: E402
FDC11 = _m11.FiveDomainFeatureComputer

ASSET_CLASSES = ("crypto_usdt", "us_stock", "precious_metal")
DOMAINS = ("dao", "tian", "di", "jiang", "fa")

# ── 比对用例集：覆盖空输入/扁平/分层/边界值/典型业务值 ──
CASES = [
    ("空输入", {}, {}),
    ("空coin_data", None, {}),
    ("空system_state", {}, None),
    ("双None", None, None),
    (
        "扁平-典型值",
        {
            "merrill_phase": "recovery", "atr_percentile": 0.7, "liquidity_score": 0.6,
            "regime": "trend_up", "ma200_distance_percentile": 0.65,
            "fedfunds_rate": 3.75, "stablecoin_mcap_bln": 182.0,
            "policy_sentiment_score": 0.7, "cycle4y_t_rel": 0.6,
        },
        {
            "factor_coverage_pct": 0.8, "win_rate": 0.55, "profit_factor": 1.4,
            "position_pct": 0.02, "max_consecutive_losses": 3, "auto_execute": True,
        },
    ),
    (
        "扁平-极端值",
        {
            "merrill_phase": "REFLATION", "atr_percentile": 0.0, "liquidity_score": 0.0,
            "regime": "trend_down", "ma200_distance_percentile": 0.0,
            "fedfunds_rate": 7.0, "stablecoin_mcap_bln": 50.0,
            "policy_sentiment_score": 0.1, "cycle4y_t_rel": 0.1,
        },
        {
            "factor_coverage_pct": 0.1, "win_rate": 0.3, "profit_factor": 0.6,
            "position_pct": 0.5, "max_consecutive_losses": 20, "auto_execute": False,
        },
    ),
    (
        "分层-三类差异化",
        {
            "crypto_usdt": {"merrill_phase": "overheat", "regime": "breakout", "ma200_distance_percentile": 0.8},
            "us_stock": {"merrill_phase": "stagflation", "regime": "ranging", "ma200_distance_percentile": 0.4},
            "precious_metal": {"merrill_phase": "recovery", "regime": "high_volatility", "ma200_distance_percentile": 0.55},
        },
        {"crypto_usdt": {"win_rate": 0.6}, "us_stock": {"win_rate": 0.45}, "precious_metal": {"win_rate": 0.52}},
    ),
    (
        "分层-部分类缺失",
        {
            "crypto_usdt": {"merrill_phase": "recovery", "regime": "trend_up"},
        },
        {"factor_coverage_pct": 0.9},
    ),
    (
        "脏数据-类型错误",
        {
            "merrill_phase": 123, "atr_percentile": "abc", "liquidity_score": None,
            "regime": [], "ma200_distance_percentile": {}, "fedfunds_rate": "x",
        },
        {"factor_coverage_pct": "bad", "win_rate": None, "auto_execute": "yes"},
    ),
]


def main() -> int:
    # 前置检查：43 侧承接开关必须关闭（纯迁移等价性验证）
    if os.environ.get("CYCLE_STATE_BRIDGE", "").lower() in ("1", "true", "yes"):
        print("[ABORT] CYCLE_STATE_BRIDGE 已打开，P3 影子比对要求关闭（验证纯迁移等价性）")
        return 2

    c11 = FDC11()
    c43 = FDC43()

    total = 0
    match = 0
    mismatches = []
    per_case = []

    for case_name, coin_data, system_state in CASES:
        r11 = c11.compute(coin_data, system_state)
        r43 = c43.compute(coin_data, system_state)
        case_total = 0
        case_match = 0
        for cls in ASSET_CLASSES:
            for dom in DOMAINS:
                total += 1
                case_total += 1
                v11 = (r11.get(cls) or {}).get(dom)
                v43 = (r43.get(cls) or {}).get(dom)
                if v11 == v43:
                    match += 1
                    case_match += 1
                else:
                    mismatches.append({
                        "case": case_name, "asset_class": cls, "domain": dom,
                        "v11": v11, "v43": v43,
                    })
        per_case.append({
            "case": case_name,
            "match": case_match,
            "total": case_total,
            "rate": round(case_match / case_total, 4) if case_total else 1.0,
        })

    rate = match / total if total else 1.0
    report = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "module": "P3 影子比对（11 原位置 vs 43 模块，迁移等价性）",
        "bridge_switch": "off",
        "cases": len(CASES),
        "comparisons": total,
        "matches": match,
        "consistency_rate": round(rate, 4),
        "threshold": 0.85,
        "passed": rate >= 0.85,
        "per_case": per_case,
        "mismatches": mismatches[:20],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if rate >= 0.85 else 1


if __name__ == "__main__":
    sys.exit(main())
