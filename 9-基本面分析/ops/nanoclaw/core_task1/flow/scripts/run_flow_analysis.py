#!/usr/bin/env python3
"""
加密市场资金流分析 - 主执行入口

功能：
1. 执行完整数据采集（三层状态机）
2. 计算各层信号
3. 生成 Regime 输出
4. 保存结果到指定目录

使用方法：
    python scripts/run_flow_analysis.py
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent))
# 添加 data_center 包路径
sys.path.insert(0, str(Path(__file__).resolve().parents[6] / "18-数据获取中心"))

from data_center.compat import run_full_collection
from regime_classifier import run_regime_classification
from storage import (
    save_layer_raw,
    save_output,
    save_analysis_report,
    HistoryRecorder,
    timestamp
)

# =============================================================================
# 配置
# =============================================================================

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "raw"
OUTPUT_DIR = BASE_DIR / "outputs"

# 确保目录存在
RAW_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# 主流程
# =============================================================================

def run_flow_analysis() -> dict:
    """
    执行完整的资金流分析流程

    Returns:
        完整分析结果字典
    """
    print("=" * 60)
    print("加密市场资金流分析系统 v2.1.0")
    print("=" * 60)

    results = {
        "analysis_timestamp": timestamp(),
        "layers": {},
        "regime_output": None,
        "steps": []
    }

    # ==========================================================================
    # Step 1: 数据采集
    # ==========================================================================
    print("\n[STEP 1] 执行数据采集...")
    step_start = datetime.now()

    try:
        collection_result = run_full_collection()
        results["layers"] = collection_result.get("layers", {})

        # 保存各层原始数据
        for layer_name, layer_data in results["layers"].items():
            save_layer_raw(layer_name, layer_data)

        step_duration = (datetime.now() - step_start).total_seconds()
        results["steps"].append({
            "step": "data_collection",
            "status": "ok",
            "duration_sec": round(step_duration, 2)
        })
        print(f"[STEP 1] ✅ 数据采集完成 ({step_duration:.2f}s)")

    except Exception as e:
        results["steps"].append({
            "step": "data_collection",
            "status": "failed",
            "error": str(e)
        })
        print(f"[STEP 1] ❌ 数据采集失败：{e}")
        raise

    # ==========================================================================
    # Step 2: 信号计算与 Regime 分类
    # ==========================================================================
    print("\n[STEP 2] 执行信号计算与 Regime 分类...")
    step_start = datetime.now()

    try:
        regime_result = run_regime_classification(collection_result=results["layers"])
        results["regime_output"] = regime_result

        step_duration = (datetime.now() - step_start).total_seconds()
        results["steps"].append({
            "step": "regime_classification",
            "status": "ok",
            "duration_sec": round(step_duration, 2)
        })
        print(f"[STEP 2] ✅ Regime 分类完成 ({step_duration:.2f}s)")

    except Exception as e:
        results["steps"].append({
            "step": "regime_classification",
            "status": "failed",
            "error": str(e)
        })
        print(f"[STEP 2] ❌ Regime 分类失败：{e}")
        raise

    # ==========================================================================
    # Step 3: 保存结果
    # ==========================================================================
    print("\n[STEP 3] 保存分析结果...")
    step_start = datetime.now()

    try:
        # 保存 JSON 结果
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        json_file = f"flow_regime_{ts}.json"
        save_output(json_file, results["regime_output"])

        # 保存 Markdown 报告
        regime = results["regime_output"]["regime_output"]
        save_analysis_report(
            composite=results["regime_output"]["composite"],
            bias=regime["bias"],
            filter_status=regime["filter"],
            risk_off=regime["risk_off"],
            confidence=results["regime_output"]["confidence"],
            layer_signals=results["regime_output"]["layer_signals"]
        )

        # 追加历史记录
        recorder = HistoryRecorder("regime_history")
        recorder.append({
            "timestamp": results["analysis_timestamp"],
            "composite": results["regime_output"]["composite"],
            "bias": regime["bias"],
            "filter": regime["filter"],
            "risk_off": regime["risk_off"],
            "confidence": results["regime_output"]["confidence"]
        })

        step_duration = (datetime.now() - step_start).total_seconds()
        results["steps"].append({
            "step": "save_results",
            "status": "ok",
            "duration_sec": round(step_duration, 2)
        })
        print(f"[STEP 3] ✅ 结果保存完成 ({step_duration:.2f}s)")

    except Exception as e:
        results["steps"].append({
            "step": "save_results",
            "status": "failed",
            "error": str(e)
        })
        print(f"[STEP 3] ❌ 结果保存失败：{e}")
        raise

    # ==========================================================================
    # 输出摘要
    # ==========================================================================
    print("\n" + "=" * 60)
    print("分析完成!")
    print("=" * 60)

    regime = results["regime_output"]["regime_output"]
    print(f"""
┌─────────────────────────────────────────────────────┐
│              资金流分析结果摘要                       │
├─────────────────────────────────────────────────────┤
│  综合信号 (Composite): {results["regime_output"]["composite"]:+.4f}                    │
│  置信度 (Confidence):  {results["regime_output"]["confidence"]:.2f}                      │
├─────────────────────────────────────────────────────┤
│  Bias (偏向):   {regime["bias"]:<10}                              │
│  Filter (过滤): {regime["filter"]:<10}                              │
│  Risk-Off:      {str(regime["risk_off"]):<10}                            │
├─────────────────────────────────────────────────────┤
│  外生资金层：{results["regime_output"]["layer_signals"]["exogenous"]:+.4f}                            │
│  内生杠杆层：{results["regime_output"]["layer_signals"]["leverage"]:+.4f}                            │
│  链上行为层：{results["regime_output"]["layer_signals"]["onchain"]:+.4f}                            │
└─────────────────────────────────────────────────────┘

输出文件：
  - JSON: {OUTPUT_DIR}/flow_regime_*.json
  - Markdown: {OUTPUT_DIR}/flow_analysis_*.md
  - 历史记录: {BASE_DIR}/historical_data/regime_history.jsonl
""")

    return results

# =============================================================================
# 命令行入口
# =============================================================================

if __name__ == "__main__":
    try:
        results = run_flow_analysis()
        print("\n✅ 资金流分析成功完成!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 资金流分析失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
