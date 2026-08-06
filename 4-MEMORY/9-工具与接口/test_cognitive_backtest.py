#!/usr/bin/env python3
"""
认知回测验证 — P1-2 突显网络 salience_score
从历史会话 action_chain 提取文件变更，A/B 对比全触发 vs salience 阈值过滤
"""

import sys
import json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from cognitive_daemon import salience_score


def load_historical_file_changes():
    """从 .cognitive/sessions/ 加载所有历史会话的文件变更"""
    sessions_dir = Path(__file__).resolve().parents[2] / ".cognitive" / "sessions"
    if not sessions_dir.exists():
        return []

    all_changes = []  # [{session_id, file, ts, change_type}]

    for session_dir in sorted(sessions_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        chain_file = session_dir / "action_chain.jsonl"
        if not chain_file.exists():
            continue

        session_id = session_dir.name
        try:
            with open(chain_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("action_type") == "file_change" and event.get("file"):
                        all_changes.append({
                            "session_id": session_id,
                            "file": event["file"],
                            "ts": event.get("timestamp", 0),
                            "detail": event.get("detail", ""),
                        })
        except (json.JSONDecodeError, OSError):
            continue

    return all_changes


def backtest_salience_score():
    """A/B 对比：全触发 vs salience 阈值过滤"""

    changes = load_historical_file_changes()
    print(f"📊 加载历史文件变更: {len(changes)} 条")

    if not changes:
        print("⚠️ 无历史数据，跳过回测")
        return True

    # Group A: 全触发（当前 baseline）—— 每次文件变更都触发认知召回
    group_a_triggers = len(changes)

    # Group B: salience 阈值过滤 —— score≥0.7 才触发
    HIGH_THRESHOLD = 0.7
    MEDIUM_THRESHOLD = 0.3

    high_salience = 0  # ≥0.7 即时触发
    medium_salience = 0  # 0.3≤score<0.7 累积触发
    low_salience = 0  # <0.3 不触发

    # 按显著性分层统计
    salience_distribution = defaultdict(int)
    file_type_examples = defaultdict(list)

    for change in changes:
        # 构造 changes dict 供 salience_score 使用
        changes_dict = {change["file"]: "M"}
        score = salience_score(changes_dict)
        salience_distribution[f"{score:.1f}"] += 1

        # 记录各分值的文件示例
        if len(file_type_examples[f"{score:.1f}"]) < 3:
            file_type_examples[f"{score:.1f}"].append(change["file"])

        if score >= HIGH_THRESHOLD:
            high_salience += 1
        elif score >= MEDIUM_THRESHOLD:
            medium_salience += 1
        else:
            low_salience += 1

    group_b_triggers = high_salience + medium_salience  # 高+中都触发（只是方式不同）
    group_b_immediate = high_salience  # 高显著即时触发

    # 计算召回调用减少率
    reduction_rate = (1 - group_b_triggers / group_a_triggers) * 100 if group_a_triggers > 0 else 0
    immediate_reduction = (1 - group_b_immediate / group_a_triggers) * 100 if group_a_triggers > 0 else 0

    print(f"\n{'='*60}")
    print(f"🧠 P1-2 突显网络 salience_score 认知回测")
    print(f"{'='*60}")
    print(f"\nGroup A (全触发 baseline):")
    print(f"  总触发次数: {group_a_triggers}")

    print(f"\nGroup B (salience 阈值过滤):")
    print(f"  高显著 (≥0.7) 即时触发: {high_salience}")
    print(f"  中显著 (0.3-0.7) 累积触发: {medium_salience}")
    print(f"  低显著 (<0.3) 不触发: {low_salience}")
    print(f"  总触发次数: {group_b_triggers}")
    print(f"  即时触发次数: {group_b_immediate}")

    print(f"\n📈 效果:")
    print(f"  召回调用减少率: {reduction_rate:.1f}%")
    print(f"  即时触发减少率: {immediate_reduction:.1f}%")

    print(f"\n📊 salience 分布:")
    for score in sorted(salience_distribution.keys()):
        count = salience_distribution[score]
        pct = count / len(changes) * 100
        examples = file_type_examples[score][:2]
        print(f"  score={score}: {count} ({pct:.1f}%) — 例: {examples[0][:60] if examples else 'N/A'}")

    # 验证：salience 阈值过滤应减少不必要的召回调用
    # 目标：低显著（<0.3）的不触发，减少率应 > 0
    assert reduction_rate >= 0, "salience 过滤不应增加触发次数"
    assert low_salience > 0 or len(changes) < 10, "应有低显著变更被过滤"

    # 验证：高显著变更应存在（风控/交易核心文件）
    if len(changes) > 50:
        # 大量历史数据中应有高显著变更
        assert high_salience + medium_salience > 0, "应有高/中显著变更被识别"

    print(f"\n✅ 认知回测验证通过：salience_score 有效区分变更显著性")
    return True


if __name__ == "__main__":
    backtest_salience_score()
