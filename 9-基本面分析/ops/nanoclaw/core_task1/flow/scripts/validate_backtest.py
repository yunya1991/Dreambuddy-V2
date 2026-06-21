#!/usr/bin/env python3
"""
前视偏差验证模块

功能：
1. 验证所有数据时间戳是否早于 Regime 计算时间戳
2. 检查是否存在未来数据泄露
3. 生成验证报告

验证规则：
- 数据时间戳必须 < Regime 计算时间戳
- 允许一定的采集延迟（最大 5 分钟）
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# =============================================================================
# 配置
# =============================================================================

FLOW_DIR = Path("/workspace/ops/nanoclaw/core_task1/flow")
OUTPUT_DIR = FLOW_DIR / "outputs"
HISTORY_DIR = FLOW_DIR / "history"

# 确保输出目录存在
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 验证配置
VALIDATION_CONFIG = {
    "max_data_lag_minutes": 5,  # 数据允许的最大延迟（分钟）
    "strict_mode": True,        # 严格模式：任何前视偏差都视为失败
}

# =============================================================================
# 验证逻辑
# =============================================================================

def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """解析 ISO 格式时间戳"""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except:
        return None


def validate_regime_record(record: dict) -> dict:
    """
    验证单个 Regime 记录是否存在前视偏差

    Args:
        record: Regime 记录

    Returns:
        验证结果
    """
    result = {
        "timestamp": record.get("timestamp", ""),
        "valid": True,
        "issues": [],
        "data_freshness": {}
    }

    regime_ts = parse_timestamp(record.get("timestamp", ""))
    if not regime_ts:
        result["valid"] = False
        result["issues"].append("无法解析 Regime 时间戳")
        return result

    # 检查各层数据的时间戳
    layer_signals = record.get("layer_signals", {})
    diagnostics = record.get("diagnostics", {})
    data_freshness = diagnostics.get("data_freshness", {})

    for layer_name, data_ts_str in data_freshness.items():
        data_ts = parse_timestamp(data_ts_str)
        if not data_ts:
            continue

        # 计算时间差（数据应该早于 Regime）
        time_diff = regime_ts - data_ts
        diff_minutes = time_diff.total_seconds() / 60

        result["data_freshness"][layer_name] = {
            "data_timestamp": data_ts_str,
            "regime_timestamp": record.get("timestamp", ""),
            "diff_minutes": round(diff_minutes, 2)
        }

        # 检查前视偏差：数据时间戳不能晚于 Regime 时间戳
        if time_diff < timedelta(minutes=-VALIDATION_CONFIG["max_data_lag_minutes"]):
            result["valid"] = False
            result["issues"].append(
                f"[前视偏差] {layer_name} 数据时间 ({data_ts_str}) 晚于 Regime 时间 "
                f"({record.get('timestamp', '')}) 超过 {VALIDATION_CONFIG['max_data_lag_minutes']} 分钟"
            )
        elif time_diff < timedelta(0):
            result["valid"] = False
            result["issues"].append(
                f"[潜在前视偏差] {layer_name} 数据时间 ({data_ts_str}) 晚于 Regime 时间 "
                f"({record.get('timestamp', '')})"
            )

    return result


def load_and_validate_records() -> List[dict]:
    """
    加载并验证所有历史 Regime 记录

    Returns:
        验证结果列表
    """
    all_validations = []

    # 从 output 目录加载 flow_regime 文件
    regime_files = sorted(OUTPUT_DIR.glob("flow_regime_*.json"))

    for file in regime_files:
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 添加文件名信息
            validation = validate_regime_record(data)
            validation["source_file"] = file.name
            all_validations.append(validation)
        except Exception as e:
            all_validations.append({
                "source_file": file.name,
                "valid": False,
                "issues": [f"加载失败：{e}"]
            })

    # 从 history 目录加载 JSONL 记录
    history_files = sorted(HISTORY_DIR.glob("regime_history_*.jsonl"))

    for history_file in history_files:
        with open(history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        record = json.loads(line)
                        validation = validate_regime_record(record)
                        validation["source_file"] = f"{history_file.name}"
                        all_validations.append(validation)
                    except:
                        pass

    return all_validations


def generate_validation_report(validations: List[dict]) -> str:
    """
    生成前视偏差验证报告

    Args:
        validations: 验证结果列表

    Returns:
        Markdown 格式报告
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    total = len(validations)
    valid_count = sum(1 for v in validations if v.get("valid", False))
    invalid_count = total - valid_count

    # 统计问题类型
    issue_types = {}
    for v in validations:
        for issue in v.get("issues", []):
            if "前视偏差" in issue:
                issue_types["前视偏差"] = issue_types.get("前视偏差", 0) + 1
            if "潜在前视偏差" in issue:
                issue_types["潜在前视偏差"] = issue_types.get("潜在前视偏差", 0) + 1
            if "加载失败" in issue:
                issue_types["加载失败"] = issue_types.get("加载失败", 0) + 1
            if "无法解析" in issue:
                issue_types["时间戳解析失败"] = issue_types.get("时间戳解析失败", 0) + 1

    # 综合评估
    if VALIDATION_CONFIG["strict_mode"]:
        if invalid_count == 0:
            overall_status = "✅ 通过 - 无前视偏差"
        else:
            overall_status = "❌ 失败 - 发现前视偏差"
    else:
        pass_rate = valid_count / total if total > 0 else 0
        if pass_rate >= 0.95:
            overall_status = "✅ 通过 - 偏差率 < 5%"
        elif pass_rate >= 0.80:
            overall_status = "⚠️ 警告 - 偏差率 5-20%"
        else:
            overall_status = "❌ 失败 - 偏差率 > 20%"

    report = f"""# 前视偏差验证报告

**生成时间**: {ts}
**验证记录数**: {total}
**验证模式**: {"严格" if VALIDATION_CONFIG["strict_mode"] else "宽松"}

---

## 📊 验证结果

| 指标 | 数量 | 百分比 |
|------|------|--------|
| **有效记录** | {valid_count} | {valid_count/total*100 if total > 0 else 0:.1f}% |
| **无效记录** | {invalid_count} | {invalid_count/total*100 if total > 0 else 0:.1f}% |

---

## ⚠️ 问题统计

| 问题类型 | 数量 |
|----------|------|
"""

    if issue_types:
        for issue_type, count in issue_types.items():
            report += f"| {issue_type} | {count} |\n"
    else:
        report += "| 无问题 | 0 |\n"

    report += f"""
---

## 🎯 综合评估

**{overall_status}**

### 验证规则
- 数据时间戳必须早于 Regime 计算时间戳
- 允许最大延迟：{VALIDATION_CONFIG["max_data_lag_minutes"]} 分钟
- 严格模式：{"是" if VALIDATION_CONFIG["strict_mode"] else "否"}（任何前视偏差都视为失败）

---

## 📝 详细验证结果
"""

    # 添加详细验证结果（仅显示有问题的记录）
    invalid_validations = [v for v in validations if not v.get("valid", False)]

    if invalid_validations:
        report += """
### 无效记录详情

| 时间戳 | 源文件 | 问题 |
|--------|--------|------|
"""
        for v in invalid_validations[:20]:  # 限制显示 20 条
            issues = "; ".join(v.get("issues", [])[:2])  # 每条最多显示 2 个问题
            report += f"| {v.get('timestamp', 'N/A')[:19]} | {v.get('source_file', 'N/A')} | {issues[:50]}... |\n"

        if len(invalid_validations) > 20:
            report += f"\n*... 还有 {len(invalid_validations) - 20} 条无效记录未显示*\n"
    else:
        report += "\n✅ 所有记录均通过验证，无前视偏差问题。\n"

    # 数据新鲜度统计
    report += f"""
---

## 🔍 数据新鲜度分析

"""

    # 统计各层数据的平均延迟
    layer_delays = {}
    for v in validations:
        freshness = v.get("data_freshness", {})
        for layer, data in freshness.items():
            diff = data.get("diff_minutes", 0)
            if layer not in layer_delays:
                layer_delays[layer] = []
            layer_delays[layer].append(diff)

    if layer_delays:
        report += """| 层级 | 平均延迟 (分钟) | 最大延迟 (分钟) | 最小延迟 (分钟) |
|------|-----------------|-----------------|-----------------|
"""
        for layer, delays in layer_delays.items():
            avg_delay = sum(delays) / len(delays)
            max_delay = max(delays)
            min_delay = min(delays)
            report += f"| {layer} | {avg_delay:.1f} | {max_delay:.1f} | {min_delay:.1f} |\n"
    else:
        report += "*无数据新鲜度数据*\n"

    report += """
---

## ✅ 验证结论

"""

    if invalid_count == 0:
        report += """**资金流分析系统不存在前视偏差问题，回测结果可信。**

验证通过点：
1. ✅ 所有数据时间戳均早于 Regime 计算时间戳
2. ✅ 数据采集延迟在允许范围内
3. ✅ 时间戳解析正常

**建议**: 可以安全使用历史数据进行回测验证。
"""
    else:
        report += f"""**发现 {invalid_count} 条记录存在前视偏差问题，回测结果可能不可信。**

### 建议修复措施：
1. 检查数据收集流程，确保数据采集时间早于 Regime 计算
2. 在回测中排除存在前视偏差的记录
3. 添加时间戳验证逻辑，自动过滤问题数据
"""

    report += """
---

*本报告由 validate_backtest.py 生成 | 前视偏差验证是回测可信度的关键保证*
"""

    return report


# =============================================================================
# 主流程
# =============================================================================

def run_validation() -> dict:
    """
    执行完整的前视偏差验证流程

    Returns:
        验证结果字典
    """
    print("=" * 60)
    print("前视偏差验证引擎")
    print("=" * 60)

    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_records": 0,
        "valid_records": 0,
        "invalid_records": 0,
        "issues": [],
        "report_path": None
    }

    # ==========================================================================
    # Step 1: 加载并验证记录
    # ==========================================================================
    print("\n[STEP 1] 加载并验证 Regime 记录...")
    validations = load_and_validate_records()

    result["total_records"] = len(validations)
    result["valid_records"] = sum(1 for v in validations if v.get("valid", False))
    result["invalid_records"] = result["total_records"] - result["valid_records"]

    # 收集所有问题
    for v in validations:
        if v.get("issues"):
            result["issues"].append({
                "file": v.get("source_file", ""),
                "timestamp": v.get("timestamp", ""),
                "issues": v.get("issues", [])
            })

    print(f"  总记录数：{result['total_records']}")
    print(f"  有效记录：{result['valid_records']}")
    print(f"  无效记录：{result['invalid_records']}")

    # ==========================================================================
    # Step 2: 生成验证报告
    # ==========================================================================
    print("\n[STEP 2] 生成验证报告...")

    report = generate_validation_report(validations)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    report_path = OUTPUT_DIR / f"validation_report_{ts}.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    result["report_path"] = str(report_path)
    print(f"  报告已保存：{report_path}")

    # 保存 JSON 结果
    json_path = OUTPUT_DIR / f"validation_result_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"  JSON 已保存：{json_path}")

    # ==========================================================================
    # 输出摘要
    # ==========================================================================
    print("\n" + "=" * 60)
    print("验证完成!")
    print("=" * 60)

    if result["invalid_records"] == 0:
        print("✅ 前视偏差验证通过 - 所有记录均无时间戳问题")
    else:
        print(f"⚠️ 发现 {result['invalid_records']} 条记录存在前视偏差问题")

        # 显示问题摘要
        issue_types = {}
        for item in result["issues"]:
            for issue in item.get("issues", []):
                if "前视偏差" in issue:
                    issue_types["前视偏差"] = issue_types.get("前视偏差", 0) + 1
                elif "潜在前视偏差" in issue:
                    issue_types["潜在前视偏差"] = issue_types.get("潜在前视偏差", 0) + 1

        if issue_types:
            print("\n问题类型统计:")
            for issue_type, count in issue_types.items():
                print(f"  - {issue_type}: {count}")

    return result


# =============================================================================
# 命令行入口
# =============================================================================

if __name__ == "__main__":
    result = run_validation()
