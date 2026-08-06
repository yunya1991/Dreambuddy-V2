#!/usr/bin/env python3
"""
双通道决策模块测试 — TDD 验证

覆盖：
  1. CorpusCallosum 三种整合场景
  2. DualChannelRunner 环境就绪度
  3. ABComparison 回测对比
"""
import sys
from pathlib import Path

# 注入 ab-trading core 路径
_AB_CORE = Path(__file__).resolve().parents[1]
if str(_AB_CORE) not in sys.path:
    sys.path.insert(0, str(_AB_CORE))


def test_corpus_callosum_full_consensus():
    """场景1: 三者一致 → 高置信标准仓"""
    from core.dual_channel.corpus_callosum import (
        CorpusCallosum, ChannelResult, AgreementLevel
    )
    cc = CorpusCallosum(gate_threshold=0.65)
    left = ChannelResult(direction="LONG", confidence=0.70, source="left_brain")
    right = ChannelResult(direction="LONG", confidence=0.68, source="yijing")

    result = cc.integrate(left, right, a0_direction="LONG")

    assert result.agreement_level == AgreementLevel.FULL_CONSENSUS
    assert result.direction == "LONG"
    assert result.confidence > 0.70  # 有加成
    assert result.gate_passed is True
    assert not result.divergence_flag
    print(f"✅ test_corpus_callosum_full_consensus 通过 (conf={result.confidence:.2f})")
    return True


def test_corpus_callosum_lr_consensus_vs_a0():
    """场景2: 左右一致但与A0相反 → 取A0方向 + 降置信"""
    from core.dual_channel.corpus_callosum import (
        CorpusCallosum, ChannelResult, AgreementLevel
    )
    cc = CorpusCallosum()
    left = ChannelResult(direction="LONG", confidence=0.72, source="left_brain")
    right = ChannelResult(direction="LONG", confidence=0.70, source="yijing")

    result = cc.integrate(left, right, a0_direction="SHORT")

    assert result.agreement_level == AgreementLevel.LR_CONSENSUS
    assert result.direction == "SHORT"  # 取A0方向
    assert result.confidence < 0.72  # 降置信
    assert result.confidence_adjustment < 0  # 负调整
    print(f"✅ test_corpus_callosum_lr_consensus_vs_a0 通过 (dir={result.direction}, conf={result.confidence:.2f})")
    return True


def test_corpus_callosum_lr_divergent():
    """场景3: 左右分歧 → 取A0方向 + 降置信 + 标记分歧"""
    from core.dual_channel.corpus_callosum import (
        CorpusCallosum, ChannelResult, AgreementLevel
    )
    cc = CorpusCallosum()
    left = ChannelResult(direction="LONG", confidence=0.70, source="left_brain")
    right = ChannelResult(direction="SHORT", confidence=0.65, source="oneirology")

    result = cc.integrate(left, right, a0_direction="LONG")

    assert result.agreement_level == AgreementLevel.LR_DIVERGENT
    assert result.direction == "LONG"  # 取A0方向
    assert result.divergence_flag is True
    assert result.confidence < 0.70  # 降置信
    print(f"✅ test_corpus_callosum_lr_divergent 通过 (dir={result.direction}, diverge={result.divergence_flag})")
    return True


def test_corpus_callosum_right_skip():
    """右脑未启用 → 单通道降级"""
    from core.dual_channel.corpus_callosum import (
        CorpusCallosum, ChannelResult, AgreementLevel
    )
    cc = CorpusCallosum(gate_threshold=0.65)
    left = ChannelResult(direction="LONG", confidence=0.70, source="left_brain")

    result = cc.integrate(left, None, a0_direction="LONG")

    assert result.agreement_level == AgreementLevel.RIGHT_SKIP
    assert result.direction == "LONG"
    assert result.confidence == 0.70  # 无调整
    assert result.right_brain is None
    print(f"✅ test_corpus_callosum_right_skip 通过")
    return True


def test_corpus_callosum_hold_rejected():
    """HOLD 方向 → 门禁不通过"""
    from core.dual_channel.corpus_callosum import CorpusCallosum, ChannelResult
    cc = CorpusCallosum(gate_threshold=0.65)
    left = ChannelResult(direction="HOLD", confidence=0.50, source="left_brain")
    right = ChannelResult(direction="HOLD", confidence=0.45, source="yijing")

    result = cc.integrate(left, right, a0_direction="HOLD")

    assert result.gate_passed is False
    assert result.direction == "HOLD"
    print(f"✅ test_corpus_callosum_hold_rejected 通过")
    return True


def test_dual_channel_runner_status():
    """DualChannelRunner 环境就绪度检查"""
    from core.dual_channel.dual_channel_runner import DualChannelRunner

    runner = DualChannelRunner(right_channel_enabled=True)
    status = runner.status()

    assert "right_channel_enabled" in status
    assert "yijing_available" in status
    assert "yijing_engine_active" in status
    assert "corpus_callosum" in status
    assert status["right_channel_enabled"] is True
    print(f"✅ test_dual_channel_runner_status 通过 (yijing={status['yijing_available']}, active={status['yijing_engine_active']})")
    return True


def test_dual_channel_runner_decision():
    """双通道运行器决策输出"""
    from core.dual_channel.dual_channel_runner import DualChannelRunner
    from core.dual_channel.corpus_callosum import ChannelResult

    runner = DualChannelRunner(right_channel_enabled=True)
    mkt = {
        "coin": "BTC", "price": 65000, "ema20": 64000, "ema50": 63000,
        "rsi14": 55, "change_24h": 2.5, "vol_ratio": 1.3,
        "funding_rate": 0.0001, "regime": "TREND",
    }
    memory = {"recent_decisions": [], "loss_streaks": 0}
    left = ChannelResult(direction="LONG", confidence=0.72, source="left_brain",
                         metadata={"a0_direction": "LONG"})

    decision = runner.run(mkt, memory, left, a0_direction="LONG")

    assert decision.direction in ("LONG", "SHORT", "HOLD")
    assert 0 <= decision.confidence <= 1
    assert decision.left_brain.direction == "LONG"
    # 右脑可能为None（yijing不可用时退化为做梦部）
    if decision.right_brain:
        assert decision.right_brain.source in ("yijing", "oneirology", "yijing_error", "oneirology_error")
    print(f"✅ test_dual_channel_runner_decision 通过 (dir={decision.direction}, conf={decision.confidence:.2f}, right={decision.right_brain.source if decision.right_brain else 'None'})")
    return True


def test_ab_comparison_report():
    """AB 对比回测报告生成"""
    from core.dual_channel.ab_comparison import ABComparison

    ab = ABComparison()
    # 使用少量K线快速测试
    report = ab.run(coin="BTC", bars=200)

    assert report.coin == "BTC"
    assert report.bars > 0
    assert -1.0 <= report.path_advantage <= 1.0
    assert report.decision in ("upgrade", "alert", "observe", "quarantine")
    assert isinstance(report.group_a.total_signals, int)
    assert isinstance(report.group_b.total_signals, int)

    summary = report.summary()
    assert "AB 对比报告" in summary
    assert "path_advantage" in summary
    print(f"✅ test_ab_comparison_report 通过 (A: {report.group_a.traded} trades, B: {report.group_b.traded} trades, adv={report.path_advantage:+.4f})")
    return True


def test_ab_comparison_cli_status():
    """CLI --status 环境检查"""
    from core.dual_channel.dual_channel_runner import DualChannelRunner
    import json

    runner = DualChannelRunner()
    status = runner.status()
    status_json = json.dumps(status, ensure_ascii=False)

    assert "yijing_available" in status_json
    assert "corpus_callosum" in status_json
    print(f"✅ test_ab_comparison_cli_status 通过")
    return True


if __name__ == "__main__":
    tests = [
        test_corpus_callosum_full_consensus,
        test_corpus_callosum_lr_consensus_vs_a0,
        test_corpus_callosum_lr_divergent,
        test_corpus_callosum_right_skip,
        test_corpus_callosum_hold_rejected,
        test_dual_channel_runner_status,
        test_dual_channel_runner_decision,
        test_ab_comparison_report,
        test_ab_comparison_cli_status,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"❌ {test.__name__} 失败: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"总计: {passed} passed, {failed} failed")
    if failed == 0:
        print("🎉 全部通过！")
    sys.exit(0 if failed == 0 else 1)
