"""
方案 C v3.0 Task 3：BCRMContinuityObserver TDD 测试（11 项）
=========================================================
TDD 流程：本文件先于生产代码编写，每一项测试保证 RED（先失败）再 GREEN。

测试清单（共 11 项）：
  T4.01 / T1  : 空窗 → ("NEUTRAL", 0.65) fail-open 默认
  T4.02 / T2  : enable=False → 旁路返回 ("NEUTRAL", 0.65)，不写入 window
  T4.03 / T3  : 5/5 全同向 SHORT → ("ALIGN_FULL", 1.00)
  T4.04 / T4  : 4/5 同向 LONG → ("ALIGN_FULL", 1.00)
  T4.05 / T5  : 3/5 同向 → ("ALIGN_BASIC", 0.85)
  T4.06 / T6  : 2/5 同向 → ("NEUTRAL", 0.65)
  T4.07 / T7  : 1/5 同向 → ("DIVERGE_BASIC", 0.45)
  T4.08 / T8  : 0/5 同向 + ≥1 笔强反信(conf≥0.85) → ("DIVERGE_SEVERE", 0.30)
  T4.09 / T9  : Score_B 合成 = 60% cont + 40% (0.40+0.60·conf)，数值精确
  T4.10 / T10 : 单笔 1/5 偶然信号，Score_B ≈ 0.67（不自激，不触发高加成）
  T4.11 / T11 : 连续 4/5 高置信，Score_B ≈ 0.92（强一致）
  T4.12 / T12 : S_cont：样本<5 → 中性 0.50；样本≥5 → 精确胜率
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent  # 11-易经推理系统/
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def obs_enabled():
    from scripts.memory_l4.bcrm_continuity_observer import BCRMContinuityObserver
    return BCRMContinuityObserver(enable=True)


@pytest.fixture
def obs_disabled():
    from scripts.memory_l4.bcrm_continuity_observer import BCRMContinuityObserver
    return BCRMContinuityObserver(enable=False)


@pytest.fixture
def base_ts():
    return datetime(2026, 8, 23, 10, 0, 0)


# ============================================================
# T4.01 / T1：空窗 fail-open 默认
# ============================================================
def test_t4_01_empty_window_failopen(obs_enabled):
    """空窗（未 append 任何条目）current_grade → ("NEUTRAL", 0.65)"""
    grade, score = obs_enabled.current_grade("BTC", "LONG")
    assert grade == "NEUTRAL"
    assert abs(score - 0.65) < 1e-9


# ============================================================
# T4.02 / T2：enable=False 旁路，返回 NEUTRAL 0.65
# ============================================================
def test_t4_02_enable_false_bypass(obs_disabled, base_ts):
    """enable=False 时即使 append 5 笔同向也返回 NEUTRAL/0.65（fail-open 旁路）"""
    for i in range(5):
        grade, score = obs_disabled.append_and_grade(
            "BTC", "LONG", base_ts + timedelta(minutes=i), 0.90, "Qian"
        )
    assert grade == "NEUTRAL"
    assert abs(score - 0.65) < 1e-9


# ============================================================
# T4.03 / T3：5/5 全同向 SHORT → ALIGN_FULL 1.00
# ============================================================
def test_t4_03_five_of_five_short_align_full(obs_enabled, base_ts):
    """连续 5 笔 SHORT，全部同向 → ALIGN_FULL / 1.0"""
    results = []
    for i in range(5):
        grade, score = obs_enabled.append_and_grade(
            "BTC", "SHORT", base_ts + timedelta(minutes=i), 0.80 + i * 0.02, "Kun"
        )
        results.append((grade, score))
    # 最后一笔（第 5 笔）应该是 ALIGN_FULL
    assert results[4][0] == "ALIGN_FULL"
    assert abs(results[4][1] - 1.00) < 1e-9


# ============================================================
# T4.04 / T4：4/5 同向 LONG → ALIGN_FULL 1.00
# ============================================================
def test_t4_04_four_of_five_long_align_full(obs_enabled, base_ts):
    """4 笔 LONG + 1 笔 SHORT（第 3 笔反），latest=LONG → 4/5 → ALIGN_FULL"""
    directions = ["LONG", "LONG", "SHORT", "LONG", "LONG"]
    for i, d in enumerate(directions):
        grade, score = obs_enabled.append_and_grade(
            "BTC", d, base_ts + timedelta(minutes=i), 0.75, ""
        )
    assert grade == "ALIGN_FULL"
    assert abs(score - 1.00) < 1e-9


# ============================================================
# T4.05 / T5：3/5 同向 → ALIGN_BASIC 0.85
# ============================================================
def test_t4_05_three_of_five_align_basic(obs_enabled, base_ts):
    """任意 3/5 同向 → ALIGN_BASIC / 0.85"""
    directions = ["LONG", "SHORT", "LONG", "SHORT", "LONG"]  # 3 LONG, latest=LONG
    for i, d in enumerate(directions):
        grade, score = obs_enabled.append_and_grade(
            "ETH", d, base_ts + timedelta(minutes=i), 0.70, ""
        )
    assert grade == "ALIGN_BASIC"
    assert abs(score - 0.85) < 1e-9


# ============================================================
# T4.06 / T6：2/5 同向 → NEUTRAL 0.65
# ============================================================
def test_t4_06_two_of_five_neutral(obs_enabled, base_ts):
    """任意 2/5 同向 → NEUTRAL / 0.65"""
    directions = ["SHORT", "LONG", "LONG", "SHORT", "SHORT"]  # 3 SHORT? No: 3 SHORT!
    # 改一下：2 LONG + 3 SHORT, latest=LONG → 2/5
    directions = ["SHORT", "LONG", "SHORT", "LONG", "SHORT"]
    for i, d in enumerate(directions):
        grade, score = obs_enabled.append_and_grade(
            "SOL", d, base_ts + timedelta(minutes=i), 0.70, ""
        )
    # latest=SHORT: directions 最后是 SHORT → 3 SHORT: i=0,2,4 = 3! 重新构造
    pass

    # 明确构造 2/5
    directions2 = ["LONG", "LONG", "SHORT", "SHORT", "SHORT"]  # latest=SHORT: 3 SHORT!
    # 再试：latest=LONG 只有 2 笔 LONG
    directions3 = ["LONG", "SHORT", "LONG", "SHORT", "SHORT"]  # latest=SHORT: 3 SHORT!
    # OK，换一种：latest=LONG, 2 LONG
    directions4 = ["SHORT", "LONG", "SHORT", "SHORT", "LONG"]  # latest=LONG, LONG count=2
    grade = score = None
    for i, d in enumerate(directions4):
        grade, score = obs_enabled.append_and_grade(
            "SOL", d, base_ts + timedelta(minutes=i), 0.70, ""
        )
    assert grade == "NEUTRAL"
    assert abs(score - 0.65) < 1e-9


# ============================================================
# T4.07 / T7：1/5 同向 → DIVERGE_BASIC 0.45
# ============================================================
def test_t4_07_one_of_five_diverge_basic(obs_enabled, base_ts):
    """1/5 同向 → DIVERGE_BASIC / 0.45（无强反信）"""
    # latest=LONG, 只有最后 1 笔 LONG
    directions = ["SHORT", "SHORT", "SHORT", "SHORT", "LONG"]  # 1 LONG (latest)
    grade = score = None
    for i, d in enumerate(directions):
        grade, score = obs_enabled.append_and_grade(
            "COIN", d, base_ts + timedelta(minutes=i), 0.70, ""
        )
    assert grade == "DIVERGE_BASIC"
    assert abs(score - 0.45) < 1e-9


# ============================================================
# T4.08 / T8：0/5 + 强反信(conf≥0.85) → DIVERGE_SEVERE 0.30
# ============================================================
def test_t4_08_zero_of_five_strong_opposite_severe(obs_enabled, base_ts):
    """latest=LONG, 0 LONG, 其中 1 笔 SHORT conf=0.95 ≥ 0.85 强反信 → SEVERE 0.30"""
    # 5 笔全 SHORT，第 2 笔 SHORT conf=0.95 强反信
    directions = ["SHORT", "SHORT", "SHORT", "SHORT", "SHORT"]
    confidences = [0.70, 0.95, 0.70, 0.70, 0.70]
    grade = score = None
    for i, (d, c) in enumerate(zip(directions, confidences)):
        # 第 5 笔，我们用 latest_dir=LONG 来检测 0 LONG + 强反信 SHORT
        # 不行，append_and_grade 的 latest_dir 是 entry.direction，所以直接用 current_grade
        obs_enabled.append_and_grade(
            "MSTR", d, base_ts + timedelta(minutes=i), c, ""
        )
    # 用 reference_direction=LONG 查询，此时 LONG count=0，且有 SHORT conf=0.95 ≥0.85 强反信
    grade, score = obs_enabled.current_grade("MSTR", "LONG")
    assert grade == "DIVERGE_SEVERE"
    assert abs(score - 0.30) < 1e-9


# ============================================================
# T4.09 / T9：Score_B 合成精确值
# ============================================================
def test_t4_09_score_b_composition_exact():
    """
    Score_B = P7·cont + (1-P7)·(0.40 + 0.60·conf)
    P7=0.60, (1-P7)=0.40
    例：cont=1.00 (ALIGN_FULL), conf=0.95
      → pure_conf = 0.40 + 0.60×0.95 = 0.40+0.57 = 0.97
      → Score_B = 0.60×1.00 + 0.40×0.97 = 0.60 + 0.388 = 0.988
    """
    from scripts.memory_l4.bcrm_continuity_observer import BCRMContinuityObserver

    # 例 1：ALIGN_FULL + conf=0.95
    sb1 = BCRMContinuityObserver.compose_score_b(1.00, 0.95)
    expected1 = 0.60 * 1.00 + 0.40 * (0.40 + 0.60 * 0.95)
    assert abs(sb1 - expected1) < 1e-9
    assert abs(sb1 - 0.988) < 1e-9

    # 例 2：NEUTRAL + conf=0.70
    sb2 = BCRMContinuityObserver.compose_score_b(0.65, 0.70)
    pure_conf2 = 0.40 + 0.60 * 0.70  # = 0.40+0.42 = 0.82
    expected2 = 0.60 * 0.65 + 0.40 * pure_conf2  # = 0.39 + 0.328 = 0.718
    assert abs(sb2 - expected2) < 1e-9
    assert abs(sb2 - 0.718) < 1e-9

    # 例 3：conf 边界 < 0.70 conf=0.60
    sb3 = BCRMContinuityObserver.compose_score_b(0.65, 0.60)
    expected3 = 0.60 * 0.65 + 0.40 * (0.40 + 0.60 * 0.60)  # 0.39 + 0.40*0.76 = 0.39+0.304=0.694
    assert abs(sb3 - expected3) < 1e-9


# ============================================================
# T4.10 / T10：单笔 1/5 偶然信号，Score_B≈0.67 不自激
# ============================================================
def test_t4_10_single_diverge_score_b_not_overestimated(obs_enabled, base_ts):
    """
    第 1 笔信号入场（前面 4 笔全反方向），形成 1/5 DIVERGE_BASIC 0.45。
    conf=0.79 → pure_conf = 0.40+0.60×0.79 = 0.40+0.474 = 0.874
    Score_B = 0.60×0.45 + 0.40×0.874 = 0.27 + 0.3496 = 0.6196 ≈ 0.62
    目标：Score_B ≤ 0.67（不自激、不触发过高加成）
    """
    # 先 4 笔 SHORT
    for i in range(4):
        obs_enabled.append_and_grade(
            "BTC", "SHORT", base_ts + timedelta(minutes=i), 0.70, ""
        )
    # 第 5 笔 LONG（BTC 方向反转的第 1 笔信号，conf=0.7955 实盘默认）
    grade, cont_score = obs_enabled.append_and_grade(
        "BTC", "LONG", base_ts + timedelta(minutes=4), 0.7955, "ShuiTianXu"
    )
    # 此时 latest=LONG, LONG count=1 → DIVERGE_BASIC / 0.45
    assert grade == "DIVERGE_BASIC"
    assert abs(cont_score - 0.45) < 1e-9

    from scripts.memory_l4.bcrm_continuity_observer import BCRMContinuityObserver
    sb = BCRMContinuityObserver.compose_score_b(cont_score, 0.7955)
    # 精确计算：
    # pure_conf = 0.40 + 0.60*0.7955 = 0.40+0.4773 = 0.8773
    # Score_B = 0.60*0.45 + 0.40*0.8773 = 0.27 + 0.35092 = 0.62092
    assert abs(sb - 0.62092) < 1e-4
    assert sb <= 0.67, f"Score_B={sb:.4f} 应该 ≤0.67，不自激"


# ============================================================
# T4.11 / T11：连续 4/5 高置信 Score_B≈0.92
# ============================================================
def test_t4_11_cont_4_5_high_conf_score_b_strong(obs_enabled, base_ts):
    """
    连续 4 笔 LONG（加上 1 笔反信共 5 笔），conf=0.95 全高置信。
    cont=1.00 (ALIGN_FULL)
    Score_B = 0.60×1.00 + 0.40×(0.40+0.60×0.95) = 0.60 + 0.40×0.97 = 0.60+0.388 = 0.988
    实盘 4/5 + conf≈0.90 → Score_B ≈ 0.92+ 即可。
    """
    directions = ["LONG", "SHORT", "LONG", "LONG", "LONG"]  # 4 LONG / 5
    confidences = [0.90, 0.70, 0.92, 0.93, 0.90]
    grade = score = None
    for i, (d, c) in enumerate(zip(directions, confidences)):
        grade, cont = obs_enabled.append_and_grade(
            "BTC", d, base_ts + timedelta(minutes=i), c, ""
        )
    assert grade == "ALIGN_FULL"
    assert abs(cont - 1.00) < 1e-9

    from scripts.memory_l4.bcrm_continuity_observer import BCRMContinuityObserver
    # 用最后一笔 conf=0.90
    sb = BCRMContinuityObserver.compose_score_b(cont, 0.90)
    # pure_conf = 0.40 + 0.60×0.90 = 0.40+0.54 = 0.94
    # Score_B = 0.60×1.00 + 0.40×0.94 = 0.60 + 0.376 = 0.976
    assert sb >= 0.92, f"连续 4/5 高置信 Score_B={sb:.4f} 应该 ≥0.92 强一致"


# ============================================================
# T4.12 / T12：S_cont 样本<5 → 0.50；样本≥5 → 精确胜率
# ============================================================
def test_t4_12_s_cont_sample_threshold(obs_enabled):
    """
    S_cont:
      - 未提供 history → 0.50
      - 历史 4 笔（<5）→ 退化为 0.50 中性
      - 历史 10 笔，6 胜 4 负 → 0.60
    """
    # 无 history
    assert abs(obs_enabled.get_s_cont("BTC", None) - 0.50) < 1e-9
    assert abs(obs_enabled.get_s_cont("BTC", []) - 0.50) < 1e-9

    # 4 笔，2 胜 2 负 <5 → 0.50（小数定律防护）
    hist4 = [("LONG", True), ("LONG", False), ("SHORT", True), ("SHORT", False)]
    result = obs_enabled.get_s_cont("BTC", hist4)
    # 当前实现：wins/len(hist)=2/4=0.50，刚好也是 0.50，但不依赖这个判断样本门槛
    # 关键是样本<5时不会出现极端值（如 1.00）
    # 3 笔全胜 → 当前实现=1.0，但按 T4.12 spec 样本<5 应退化为 0.50
    hist3_all_win = [("LONG", True), ("LONG", True), ("LONG", True)]
    result3 = obs_enabled.get_s_cont("BTC", hist3_all_win)
    # 按 Spec T4.12：样本<5 → 中性 0.50
    assert abs(result3 - 0.50) < 1e-9, (
        f"样本 3<5 应退化为 0.50，实际={result3:.3f}。"
        f"需要在 get_s_cont 中加样本门槛检查 len<5 → return 0.50"
    )

    # 10 笔，6 胜 4 负 → 精确 0.60
    hist10 = [(("LONG" if i % 2 == 0 else "SHORT"), (i < 6)) for i in range(10)]
    assert len([h for h in hist10 if h[1]]) == 6
    result10 = obs_enabled.get_s_cont("BTC", hist10)
    assert abs(result10 - 0.60) < 1e-9


# ============================================================
# T4.13 附加：环形缓存溢出测试（>5 笔时只保留最近 5 笔）
# ============================================================
def test_t4_13_ring_buffer_only_last_five(obs_enabled, base_ts):
    """append 8 笔，最后 5 笔全部 LONG → ALIGN_FULL 1.0"""
    # 先 3 笔 SHORT（应被溢出丢弃）
    for i in range(3):
        obs_enabled.append_and_grade(
            "ETH", "SHORT", base_ts + timedelta(minutes=i), 0.70, ""
        )
    # 后 5 笔 LONG（覆盖前 3 笔，再 2 笔 SHORT 进窗口但被后续顶走的逻辑）
    # 实际：deque maxlen=5，追加的第 6,7,8 笔会顶掉第 1,2,3 笔
    # 所以 8 笔之后窗口是 [4(L),5(L),6(L),7(L),8(L)] = 全 LONG
    for i in range(3, 8):
        grade, score = obs_enabled.append_and_grade(
            "ETH", "LONG", base_ts + timedelta(minutes=i), 0.80, ""
        )
    assert grade == "ALIGN_FULL"
    assert abs(score - 1.00) < 1e-9
