#!/usr/bin/env python3
"""
加密市场资金流分析 - 数据存储模块

负责：
1. 原始数据落盘（JSON 格式）
2. 历史记录管理（JSONL 格式）
3. 数据版本控制
4. 查询与回溯支持
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# =============================================================================
# 目录配置
# =============================================================================

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "raw"
OUTPUT_DIR = BASE_DIR / "outputs"
HISTORICAL_DIR = BASE_DIR / "historical_data"

# 确保目录存在
for d in [RAW_DIR, OUTPUT_DIR, HISTORICAL_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# =============================================================================
# 工具函数
# =============================================================================

def timestamp() -> str:
    """获取当前 UTC 时间戳字符串"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def datestamp(fmt: str = "%Y%m%d") -> str:
    """获取当前日期字符串"""
    return datetime.now(timezone.utc).strftime(fmt)

def timestamp_filename(prefix: str, ext: str = "json") -> str:
    """生成带时间戳的文件名"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return f"{prefix}_{ts}.{ext}"

# =============================================================================
# 原始数据落盘
# =============================================================================

def save_raw_data(filename: str, data: dict, subdir: str = None) -> str:
    """
    保存原始数据到 raw 目录

    Args:
        filename: 文件名（不含路径）
        data: 要保存的数据字典
        subdir: 可选子目录（如 "exogenous", "leverage", "onchain"）

    Returns:
        保存后的完整路径
    """
    if subdir:
        dir_path = RAW_DIR / subdir
        dir_path.mkdir(parents=True, exist_ok=True)
    else:
        dir_path = RAW_DIR

    filepath = dir_path / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[STORAGE] Saved raw data: {filepath}")
    return str(filepath)

def save_layer_raw(layer_name: str, data: dict) -> str:
    """
    保存某一层原始数据

    Args:
        layer_name: 层名称 ("exogenous", "leverage", "onchain")
        data: 层数据

    Returns:
        保存后的路径
    """
    filename = timestamp_filename(f"{layer_name}_flow")
    return save_raw_data(filename, data, subdir=layer_name)

# =============================================================================
# JSONL 历史记录（事件账本风格）
# =============================================================================

class HistoryRecorder:
    """
    JSONL 格式历史记录器

    用于：
    - 记录每日/每次分析结果
    - 支持回测数据查询
    - 避免前视偏差（每条记录包含采集时间戳）
    """

    def __init__(self, filename: str, subdir: str = "historical_data"):
        """
        初始化历史记录器

        Args:
            filename: JSONL 文件名（不含路径和扩展名）
            subdir: 子目录名
        """
        self.dir_path = HISTORICAL_DIR / subdir
        self.dir_path.mkdir(parents=True, exist_ok=True)
        self.filepath = self.dir_path / f"{filename}.jsonl"

    def append(self, record: dict) -> str:
        """
        追加一条记录到 JSONL 文件

        Args:
            record: 要追加的记录（必须是可 JSON 序列化的字典）

        Returns:
            文件路径
        """
        # 添加元数据
        record["_stored_at"] = timestamp()

        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return str(self.filepath)

    def read_all(self) -> list:
        """
        读取所有历史记录

        Returns:
            记录列表
        """
        if not self.filepath.exists():
            return []

        records = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        return records

    def read_since(self, since_date: str) -> list:
        """
        读取指定日期之后的记录

        Args:
            since_date: 日期字符串 (YYYY-MM-DD)

        Returns:
            符合条件的记录列表
        """
        all_records = self.read_all()
        filtered = []

        for rec in all_records:
            rec_date = rec.get("_stored_at", "")[:10]
            if rec_date >= since_date:
                filtered.append(rec)

        return filtered

    def count(self) -> int:
        """返回记录总数"""
        return len(self.read_all())

    def latest(self, n: int = 1) -> list:
        """
        获取最新 N 条记录

        Args:
            n: 记录数量

        Returns:
            最新 N 条记录列表
        """
        all_records = self.read_all()
        return all_records[-n:] if all_records else []

# =============================================================================
# 输出文件管理
# =============================================================================

def save_output(filename: str, data: dict | str, fmt: str = "json") -> str:
    """
    保存输出文件到 outputs 目录

    Args:
        filename: 文件名
        data: 数据（字典或字符串）
        fmt: 格式 ("json" 或 "md")

    Returns:
        保存后的路径
    """
    filepath = OUTPUT_DIR / filename

    if fmt == "json":
        if isinstance(data, dict):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            # 尝试解析 JSON 字符串
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(data)
    elif fmt == "md":
        with open(filepath, "w", encoding="utf-8") as f:
            if isinstance(data, dict):
                f.write(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                f.write(data)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    print(f"[STORAGE] Saved output: {filepath}")
    return str(filepath)

def save_analysis_report(composite: float, bias: str, filter_status: str,
                         risk_off: bool, confidence: float, layer_signals: dict,
                         extra_notes: str = None) -> str:
    """
    生成并保存 Markdown 分析报告

    Args:
        composite: 综合信号值
        bias: 偏向 ("bullish", "bearish", "neutral")
        filter_status: 过滤器状态 ("enable", "disable")
        risk_off: 是否风险关闭
        confidence: 置信度
        layer_signals: 各层信号字典
        extra_notes: 额外注释

    Returns:
        报告路径
    """
    ts = timestamp()
    filename = timestamp_filename("flow_analysis", ext="md")

    # 解读文本
    bias_interpretation = {
        "bullish": "资金流一致看多，建议积极配置",
        "bearish": "资金流一致看空，建议防守为主",
        "neutral": "信号分歧或中性，建议观望"
    }.get(bias, "未知状态")

    filter_interpretation = {
        "enable": "信号有效，可参考操作",
        "disable": "信号无效，建议忽略"
    }.get(filter_status, "未知状态")

    risk_off_text = "是" if risk_off else "否"
    risk_off_advice = "⚠️ 检测到风险事件，建议降低风险敞口" if risk_off else "✅ 无重大风险信号"

    # 生成额外说明部分
    extra_section = ""
    if extra_notes:
        extra_section = f"## 额外说明\n\n{extra_notes}\n\n"

    # 生成报告
    report = f"""# 加密市场资金流分析报告

**生成时间**: {ts}
**综合信号**: {composite:+.4f}
**置信度**: {confidence:.2f}

---

## Regime 输出

| 指标 | 值 | 解读 |
|------|-----|------|
| **bias** | {bias} | {bias_interpretation} |
| **filter** | {filter_status} | {filter_interpretation} |
| **risk_off** | {risk_off_text} | {risk_off_advice} |

---

## 各层信号

| 层级 | 得分 | 解读 |
|------|------|------|
| 外生资金层 | {layer_signals.get('exogenous', 0):+.4f} | {"资金流入" if layer_signals.get('exogenous', 0) > 0 else "资金流出"} |
| 内生杠杆层 | {layer_signals.get('leverage', 0):+.4f} | {"杠杆偏高" if layer_signals.get('leverage', 0) > 0 else "杠杆偏低"} |
| 链上行为层 | {layer_signals.get('onchain', 0):+.4f} | {"链上活跃" if layer_signals.get('onchain', 0) > 0 else "链上低迷"} |

---

## 操作建议

**建议仓位**: {get_position_recommendation(bias, filter_status, confidence)}

{extra_section}
*本报告由 crypto-flow-analysis skill 生成 | 仅供研究参考*
"""

    return save_output(filename, report, fmt="md")

def get_position_recommendation(bias: str, filter_status: str, confidence: float) -> str:
    """
    根据信号生成仓位建议

    Returns:
        仓位建议字符串
    """
    if filter_status == "disable":
        return "50% (信号禁用，保持中性)"

    if bias == "bullish":
        if confidence > 0.7:
            return "70-80% (强烈看多)"
        elif confidence > 0.5:
            return "60-70% (看多)"
        else:
            return "55-60% (谨慎看多)"
    elif bias == "bearish":
        if confidence > 0.7:
            return "10-20% (强烈看空)"
        elif confidence > 0.5:
            return "20-30% (看空)"
        else:
            return "30-40% (谨慎看空)"
    else:
        return "50% (中性观望)"

# =============================================================================
# 步骤审计日志
# =============================================================================

def save_step_audit(steps: list, collection_timestamp: str) -> str:
    """
    保存执行步骤审计日志

    Args:
        steps: 步骤列表 [{"step": "...", "status": "...", "duration_ms": ...}, ...]
        collection_timestamp: 采集时间戳

    Returns:
        保存路径
    """
    audit_data = {
        "collection_timestamp": collection_timestamp,
        "steps": steps,
        "total_steps": len(steps),
        "success_count": sum(1 for s in steps if s.get("status") == "ok"),
        "failed_count": sum(1 for s in steps if s.get("status") == "failed")
    }

    filename = timestamp_filename("step_audit")
    return save_raw_data(filename, audit_data)

# =============================================================================
# 数据查询工具
# =============================================================================

def get_latest_collection() -> dict | None:
    """
    获取最新一次采集结果

    Returns:
        最新采集数据字典，或 None（如果没有数据）
    """
    # 查找最新的 flow_collection_*.json 文件
    files = sorted(RAW_DIR.glob("flow_collection_*.json"), reverse=True)

    if not files:
        return None

    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)

def get_historical_regime_records(days: int = 30) -> list:
    """
    获取指定天数内的 Regime 记录

    Args:
        days: 天数

    Returns:
        记录列表
    """
    recorder = HistoryRecorder("regime_history")
    since_date = (datetime.now(timezone.utc).date() - __import__('datetime').timedelta(days=days)).isoformat()
    return recorder.read_since(since_date)

# =============================================================================
# 主函数示例
# =============================================================================

if __name__ == "__main__":
    # 示例：保存一些测试数据
    print("[STORAGE] Testing storage module...")

    # 1. 保存原始数据
    test_data = {
        "timestamp": timestamp(),
        "test_value": 123.45,
        "layer": "test"
    }
    save_layer_raw("test", test_data)

    # 2. 追加历史记录
    recorder = HistoryRecorder("regime_history")
    recorder.append({
        "composite": 0.35,
        "bias": "bullish",
        "filter": "enable",
        "risk_off": False
    })
    print(f"[STORAGE] History records: {recorder.count()}")

    # 3. 保存输出报告
    save_analysis_report(
        composite=0.35,
        bias="bullish",
        filter_status="enable",
        risk_off=False,
        confidence=0.75,
        layer_signals={"exogenous": 0.4, "leverage": 0.3, "onchain": 0.35}
    )

    print("[STORAGE] Storage module test completed.")
