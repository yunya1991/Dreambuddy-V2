#!/usr/bin/env python3
"""
Level 1.5 A2增量更新脚本 v1.0
================================
功能: 当Level 1.5 SIGNIFICANT_SHIFT触发时，生成A2矛盾图谱增量更新
触发: A6 Phase 2 检测到T1-T4任一条件满足时
位置: ~/.workbuddy/skills/dream-intelligence-monitor/scripts/level15_a2_incremental_updater.py

使用方式:
    python level15_a2_incremental_updater.py --trigger T1 --si -25 --edge -35
    python level15_a2_incremental_updater.py --trigger T2 --si -20 --edge 0
    python level15_a2_incremental_updater.py --trigger T4 --funding_flip negative

修复问题:
    - Level 1.5检测正确但未生成A2增量文件
    - A2矛盾图谱未随市场变化更新
"""

import os
import sys
import json
import glob
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# 配置路径
WORKSPACE = Path("/Users/zhangjiangtao/WorkBuddy/20260415144304")
REPORTS_DIR = WORKSPACE / "reports"
MONITORING_DIR = WORKSPACE / "monitoring"
A0_DIR = MONITORING_DIR / "a0"

# 确保目录存在
A0_DIR.mkdir(parents=True, exist_ok=True)


def find_latest_a2_contradiction():
    """查找最新的A2矛盾图谱文件"""
    patterns = [
        REPORTS_DIR / "a2_contradiction_*.json",
        REPORTS_DIR / "trading" / "a2_contradiction_*.json",
    ]

    for pattern in patterns:
        files = glob.glob(str(pattern))
        if files:
            return max(files, key=os.path.getmtime)

    return None


def find_latest_a2_incremental():
    """查找最新的A2增量文件"""
    patterns = [
        REPORTS_DIR / "a2_contradiction_incremental_*.json",
        REPORTS_DIR / "trading" / "a2_contradiction_incremental_*.json",
    ]

    for pattern in patterns:
        files = glob.glob(str(pattern))
        if files:
            return max(files, key=os.path.getmtime)

    return None


def load_latest_a2():
    """加载最新的A2矛盾图谱"""
    a2_file = find_latest_a2_contradiction()

    if not a2_file:
        print("⚠️ 未找到A2矛盾图谱文件，创建默认版本")
        return {
            "bull_pct": 50,
            "bear_pct": 50,
            "primary_contradiction": "N/A",
            "contradictions": []
        }

    try:
        with open(a2_file, 'r') as f:
            data = json.load(f)
        print(f"📄 已加载A2矛盾图谱: {os.path.basename(a2_file)}")
        return data
    except Exception as e:
        print(f"❌ 加载A2文件失败: {e}")
        return {
            "bull_pct": 50,
            "bear_pct": 50,
            "primary_contradiction": "N/A",
            "contradictions": []
        }


def get_last_a2_update_time() -> Optional[datetime]:
    """获取上次A2更新时间"""
    incremental = find_latest_a2_incremental()

    if incremental:
        try:
            with open(incremental, 'r') as f:
                data = json.load(f)
            timestamp = data.get("timestamp")
            if timestamp:
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except:
            pass

    # 如果没有增量文件，查找原始A2文件
    a2_file = find_latest_a2_contradiction()
    if a2_file:
        return datetime.fromtimestamp(os.path.getmtime(a2_file))

    return None


def calculate_updated_assessment(a2_data: Dict, trigger: str, si_delta: float,
                                edge_delta: float, funding_flip: str = None) -> Dict:
    """计算更新后的矛盾评估"""

    # 基础概率
    bull_pct = a2_data.get("bull_pct", 50)
    bear_pct = a2_data.get("bear_pct", 50)

    # 根据触发条件调整概率
    adjustments = []

    if trigger == "T1":
        # T1: Edge从≥+20变为≤-10，信号方向剧变
        if edge_delta <= -15:
            # 信号剧烈转空
            shift = min(abs(edge_delta) * 0.5, 15)
            bull_pct -= shift
            bear_pct += shift
            adjustments.append(f"Edge剧变({edge_delta:+.0f})→空头信号增强")
        elif edge_delta >= 15:
            shift = min(abs(edge_delta) * 0.5, 15)
            bull_pct += shift
            bear_pct -= shift
            adjustments.append(f"Edge剧变({edge_delta:+.0f})→多头信号增强")

    elif trigger == "T2":
        # T2: SI_Index从≥+30变为≤+10，信号强度骤降
        if si_delta <= -20:
            # 信号强度大幅下降
            shift = min(abs(si_delta) * 0.3, 12)
            bull_pct -= shift
            bear_pct += shift
            adjustments.append(f"SI骤降({si_delta:+.0f})→不确定性增加")
        elif si_delta >= 20:
            shift = min(abs(si_delta) * 0.3, 12)
            bull_pct += shift
            bear_pct -= shift
            adjustments.append(f"SI骤升({si_delta:+.0f})→信号强度增加")

    elif trigger == "T3":
        # T3: 1H趋势与日线趋势背离
        adjustments.append("1H与日线趋势背离→短期噪声主导")

    elif trigger == "T4":
        # T4: 费率翻转
        if funding_flip == "negative_to_positive":
            bull_pct += 8
            bear_pct -= 8
            adjustments.append("费率转正(负→正)→多头平仓信号")
        elif funding_flip == "positive_to_negative":
            bull_pct -= 8
            bear_pct += 8
            adjustments.append("费率转负(正→负)→空头平仓信号")

    # 确保概率和为100
    total = bull_pct + bear_pct
    if total != 100:
        factor = 100 / total
        bull_pct *= factor
        bear_pct *= factor

    # 确定主导方向
    direction = "bull_dominant" if bull_pct > bear_pct else "bear_dominant" if bear_pct > bull_pct else "neutral"

    return {
        "bull_pct": round(bull_pct, 1),
        "bear_pct": round(bear_pct, 1),
        "direction": direction,
        "adjustments": adjustments,
        "trigger": trigger,
        "si_delta": si_delta,
        "edge_delta": edge_delta
    }


def generate_a2_incremental(trigger: str, si_delta: float = 0, edge_delta: float = 0,
                            funding_flip: str = None, reason: str = None) -> str:
    """生成A2增量更新文件"""

    timestamp = datetime.now()
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M")
    filename = f"a2_contradiction_incremental_{timestamp_str}.json"

    # 加载最新A2
    a2_data = load_latest_a2()

    # 计算更新后的评估
    updated = calculate_updated_assessment(a2_data, trigger, si_delta, edge_delta, funding_flip)

    # 构建增量文件内容
    incremental_data = {
        "type": "A2_INCREMENTAL_UPDATE",
        "trigger": "Level_1.5_SIGNIFICANT_SHIFT",
        "timestamp": timestamp.isoformat() + "Z",
        "trigger_condition": trigger,
        "delta_values": {
            "si_index": si_delta,
            "edge": edge_delta
        },
        "previous_assessment": {
            "bull_pct": a2_data.get("bull_pct", 50),
            "bear_pct": a2_data.get("bear_pct", 50),
            "primary_contradiction": a2_data.get("primary_contradiction", "N/A"),
            "source_report": os.path.basename(find_latest_a2_contradiction()) if find_latest_a2_contradiction() else "N/A"
        },
        "updated_assessment": {
            "bull_pct": updated["bull_pct"],
            "bear_pct": updated["bear_pct"],
            "primary_contradiction": a2_data.get("primary_contradiction", "N/A"),
            "direction": updated["direction"]
        },
        "change_reason": reason or f"{trigger}触发: SI={si_delta:+.0f}, Edge={edge_delta:+.0f}",
        "trigger_conditions_met": [trigger],
        "adjustments_applied": updated["adjustments"],
        "evidence_refs": [],
        "ledger_entry": f"A6-EP (Level_1.5_{timestamp_str})"
    }

    # 保存增量文件
    output_path = REPORTS_DIR / filename
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(incremental_data, f, indent=2, ensure_ascii=False)

    print(f"✅ A2增量文件已生成: {filename}")

    # 同时保存到trading子目录
    trading_dir = REPORTS_DIR / "trading"
    trading_dir.mkdir(exist_ok=True)
    trading_path = trading_dir / filename
    with open(trading_path, 'w', encoding='utf-8') as f:
        json.dump(incremental_data, f, indent=2, ensure_ascii=False)

    print(f"✅ 已同步到trading目录: {filename}")

    # 保存到monitoring/a0目录
    a0_path = A0_DIR / f"{timestamp.strftime('%Y%m%d_%H%M')}.json"
    with open(a0_path, 'w', encoding='utf-8') as f:
        json.dump({
            "type": "A0_CALL_RECORD",
            "skill": "dream-intelligence-monitor",
            "action": "Level_1.5_A2_INCREMENTAL_UPDATE",
            "timestamp": timestamp.isoformat() + "Z",
            "trigger": trigger,
            "source": "a6_phase2_significant_shift_check"
        }, f, indent=2, ensure_ascii=False)

    print(f"✅ A0调用记录已保存: {a0_path.name}")

    return filename


def check_anti_shake() -> Dict:
    """检查防抖条件"""
    last_update = get_last_a2_update_time()

    if not last_update:
        return {
            "can_trigger": True,
            "reason": "首次A2更新，无历史记录"
        }

    hours_since = (datetime.now() - last_update).total_seconds() / 3600

    if hours_since >= 2:
        return {
            "can_trigger": True,
            "hours_since": round(hours_since, 1),
            "reason": f"距上次A2更新{hours_since:.1f}小时 > 2小时阈值"
        }
    else:
        return {
            "can_trigger": False,
            "hours_since": round(hours_since, 1),
            "reason": f"距上次A2更新仅{hours_since:.1f}小时 < 2小时，需等待"
        }


def main():
    parser = argparse.ArgumentParser(description="Level 1.5 A2增量更新脚本")
    parser.add_argument("--trigger", required=True,
                        choices=["T1", "T2", "T3", "T4"],
                        help="触发条件: T1=Edge剧变, T2=SI骤降, T3=1H/日线背离, T4=费率翻转")
    parser.add_argument("--si", type=float, default=0, help="SI变化量 (如: -20)")
    parser.add_argument("--edge", type=float, default=0, help="Edge变化量 (如: -35)")
    parser.add_argument("--funding_flip", choices=["negative_to_positive", "positive_to_negative"],
                        help="费率翻转方向(T4专用)")
    parser.add_argument("--reason", type=str, help="变化原因描述")
    parser.add_argument("--force", action="store_true", help="强制执行(忽略防抖检查)")

    args = parser.parse_args()

    print("=" * 60)
    print("🔔 Level 1.5 A2增量更新")
    print("=" * 60)
    print(f"\n触发条件: {args.trigger}")
    print(f"SI变化量: {args.si_delta if hasattr(args, 'si_delta') else args.si}")
    print(f"Edge变化量: {args.edge if hasattr(args, 'edge') else args.edge}")

    # 防抖检查
    if not args.force:
        anti_shake = check_anti_shake()
        print(f"\n🔍 防抖检查:")
        print(f"   {anti_shake['reason']}")

        if not anti_shake["can_trigger"]:
            print("\n❌ 防抖未通过，Level 1.5暂不触发")
            print("   使用 --force 强制执行")
            return False

        print("   ✅ 防抖通过")

    # 生成增量文件
    filename = generate_a2_incremental(
        trigger=args.trigger,
        si_delta=args.si,
        edge_delta=args.edge,
        funding_flip=args.funding_flip,
        reason=args.reason
    )

    print(f"\n✅ Level 1.5 A2增量更新完成!")
    print(f"   文件: {filename}")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
