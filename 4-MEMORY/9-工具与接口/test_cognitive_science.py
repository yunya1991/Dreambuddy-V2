#!/usr/bin/env python3
"""
P1 认知科学完善测试 — TDD 红阶段
验证 L0 情景缓冲器、突显网络触发器、全局广播
"""

import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))


# ============================================================
# P1-1: L0 情景缓冲器（episodic_block）
# ============================================================

def test_episodic_block_exists():
    """P1-1: WorkingMemoryManager 应有 episodic_block"""
    from working_memory_manager import WorkingMemoryManager

    wm = WorkingMemoryManager(task_id="test-episodic")
    assert hasattr(wm, "episodic_block"), "WorkingMemoryManager 应有 episodic_block 属性"
    assert wm.episodic_block.name == "episodic", f"block 名称应为 episodic，实际 {wm.episodic_block.name}"

    print("✅ test_episodic_block_exists 通过")
    return True


def test_append_episode():
    """P1-1: append_episode 应记录决策事件（stage/decision/rationale）"""
    from working_memory_manager import WorkingMemoryManager

    wm = WorkingMemoryManager(task_id="test-append-episode")
    wm.append_episode(
        stage="A0_矛盾分析",
        decision="做多BTC",
        rationale="多头矛盾占优，资金流入+情绪偏多",
        evidence_refs=["FGI=72", "资金费率=0.01%"],
    )
    assert len(wm.episodic_block.items) > 0, "append_episode 后 episodic_block 应非空"

    # 验证内容可读
    prompt = wm.get_prompt_context()
    assert "决策事件序列" in prompt, "get_prompt_context 应包含决策事件序列段"
    assert "A0_矛盾分析" in prompt or "A0" in prompt, "应包含阶段名"

    print("✅ test_append_episode 通过")
    return True


def test_episodic_block_in_checkpoint():
    """P1-1: checkpoint 应序列化 episodic_block"""
    from working_memory_manager import WorkingMemoryManager

    with tempfile.TemporaryDirectory() as tmpdir:
        wm = WorkingMemoryManager(task_id="test-cp-episodic", checkpoint_dir=Path(tmpdir))
        wm.append_episode(stage="A3_战略", decision="减仓50%", rationale="RSI超买")
        cp = wm.checkpoint("episodic_test")

        data = json.loads(cp.read_text(encoding="utf-8"))
        assert "episodic_block" in data, "checkpoint 数据应包含 episodic_block"
        assert len(data["episodic_block"]["items"]) > 0, "episodic_block items 应非空"

    print("✅ test_episodic_block_in_checkpoint 通过")
    return True


# ============================================================
# P1-2: 突显网络触发器（salience_score）
# ============================================================

def test_salience_score_function_exists():
    """P1-2: cognitive_daemon 应有 salience_score 函数"""
    from cognitive_daemon import salience_score

    score = salience_score({})
    assert isinstance(score, float), f"salience_score 应返回 float，实际 {type(score)}"
    assert 0.0 <= score <= 1.0, f"salience_score 应在 [0,1]，实际 {score}"

    print("✅ test_salience_score_function_exists 通过")
    return True


def test_salience_score_risk_files_high():
    """P1-2: 风控文件变更应得高分（≥0.7）"""
    from cognitive_daemon import salience_score

    changes = {"13-通用风控模块/core/a7_gate.py": "M"}
    score = salience_score(changes)
    assert score >= 0.7, f"风控文件应≥0.7，实际 {score}"

    print("✅ test_salience_score_risk_files_high 通过")
    return True


def test_salience_score_config_files_low():
    """P1-2: 配置文件变更应得低分（<0.3）"""
    from cognitive_daemon import salience_score

    changes = {"some_config.json": "M", "params.yaml": "A"}
    score = salience_score(changes)
    assert score < 0.3, f"配置文件应<0.3，实际 {score}"

    print("✅ test_salience_score_config_files_low 通过")
    return True


def test_salience_score_empty():
    """P1-2: 空变更应得 0 分"""
    from cognitive_daemon import salience_score

    assert salience_score({}) == 0.0

    print("✅ test_salience_score_empty 通过")
    return True


# ============================================================
# P1-3: 全局广播（trading_recall → shared_memory_bus）
# ============================================================

def test_cognitive_recall_broadcast():
    """P1-3: trading_recall 结果应发布到 shared_memory_bus"""
    from cognitive_loop_entry import trading_recall

    with patch("cognitive_loop_entry._publish_cognitive_recall_broadcast") as mock_pub:
        trading_recall(
            context="BTC 做多 矛盾分析",
            coin="BTC-USDT-SWAP",
            direction="LONG",
            task_type="strategy-execution",
        )

        # 验证 _publish_cognitive_recall_broadcast 被调用
        assert mock_pub.called, "trading_recall 应调用 _publish_cognitive_recall_broadcast"

    print("✅ test_cognitive_recall_broadcast 通过")
    return True


def test_cognitive_recall_broadcast_payload():
    """P1-3: 广播 payload 应含 coin/direction"""
    from cognitive_loop_entry import trading_recall, _publish_cognitive_recall_broadcast

    captured_payload = {}

    def capture_pub(coin, direction, context, recall_result):
        captured_payload["coin"] = coin
        captured_payload["direction"] = direction
        captured_payload["context"] = context

    with patch("cognitive_loop_entry._publish_cognitive_recall_broadcast", side_effect=capture_pub):
        trading_recall(
            context="BTC 做多",
            coin="BTC-USDT-SWAP",
            direction="LONG",
            task_type="strategy-execution",
        )

        assert captured_payload.get("coin") == "BTC-USDT-SWAP", \
            f"payload 应含 coin=BTC-USDT-SWAP，实际 {captured_payload.get('coin')}"
        assert captured_payload.get("direction") == "LONG", \
            f"payload 应含 direction=LONG，实际 {captured_payload.get('direction')}"

    print("✅ test_cognitive_recall_broadcast_payload 通过")
    return True


def test_cognitive_recall_broadcast_fail_safe():
    """P1-3: 广播失败不应影响 trading_recall 主流程"""
    from cognitive_loop_entry import trading_recall

    with patch("cognitive_loop_entry._publish_cognitive_recall_broadcast") as mock_pub:
        mock_pub.side_effect = Exception("bus unavailable")

        # 不应抛异常（trading_recall 内部 try/except 包裹了广播调用）
        result = trading_recall(
            context="BTC 做多",
            coin="BTC-USDT-SWAP",
            direction="LONG",
            task_type="strategy-execution",
        )
        assert result is not None, "广播失败时 trading_recall 仍应返回结果"
        assert "ok" in result, "结果应含 ok 字段"

    print("✅ test_cognitive_recall_broadcast_fail_safe 通过")
    return True


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    tests = [
        test_episodic_block_exists,
        test_append_episode,
        test_episodic_block_in_checkpoint,
        test_salience_score_function_exists,
        test_salience_score_risk_files_high,
        test_salience_score_config_files_low,
        test_salience_score_empty,
        test_cognitive_recall_broadcast,
        test_cognitive_recall_broadcast_payload,
        test_cognitive_recall_broadcast_fail_safe,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            if t():
                passed += 1
            else:
                failed += 1
                print(f"❌ {t.__name__} 返回 False")
        except Exception as e:
            failed += 1
            print(f"❌ {t.__name__} 异常: {e}")
    print(f"\n{'='*60}")
    print(f"P1 认知科学完善测试: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(0 if failed == 0 else 1)
