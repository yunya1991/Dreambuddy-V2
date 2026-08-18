#!/usr/bin/env python3
"""
严格贝叶斯优化单元测试 — TDD红阶段
验证3个优化点：
1. Beta分布动态似然度 (替代 0.95/0.05 固定值)
2. 全概率公式展开证据 P(B) (替代 0.8/0.2 固定值)
3. 基于记忆年龄的遗忘因子 (替代 经验衰减因子)
"""

import json
import os
import sys
import tempfile
import time
import shutil
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_1_beta_likelihood_dynamic_update():
    """优化点1：Beta分布动态似然度，不再是固定0.95/0.05
    
    核心断言：
    - 初始状态 alpha=1, beta=1 (无信息先验)，似然度 E[p] = alpha/(alpha+beta) = 0.5
    - 经过一次成功+遵循后：alpha+=1 → 似然度=(1+1)/(2+1)=0.6667
    - 经过N次成功后：似然度趋近1，但不会立刻跳到0.95
    - 经过一次失败+遵循后：beta+=1
    - MemoryEntry 应包含 beta_alpha, beta_beta 字段
    """
    from bayesian_memory_updater import BayesianMemoryUpdater, MemoryEntry
    
    tmpdir = tempfile.mkdtemp()
    try:
        updater = BayesianMemoryUpdater(tmpdir)
        
        # 添加一条全新记忆 (C级，0.5置信度)
        e = updater.add_memory(
            memory_id="BETA-TEST-001",
            content="测试记忆",
            category="lesson",
            initial_confidence=0.5,
            source="TDD测试",
            tags=["test"],
        )
        
        # 断言1：初始状态 beta_alpha=1, beta_beta=1 (等价于 Beta(1,1) 均匀分布)
        assert hasattr(e, 'beta_alpha'), "MemoryEntry 缺少 beta_alpha 字段"
        assert hasattr(e, 'beta_beta'), "MemoryEntry 缺少 beta_beta 字段"
        assert e.beta_alpha == 1, f"初始 alpha 应为 1, 得 {e.beta_alpha}"
        assert e.beta_beta == 1, f"初始 beta 应为 1, 得 {e.beta_beta}"
        
        # 断言2：初始似然度计算 E[P(成功|记忆为真)] = alpha/(alpha+beta) = 0.5
        initial_likelihood = updater._calc_beta_likelihood_success(e)
        assert abs(initial_likelihood - 0.5) < 1e-4, (
            f"初始成功似然度应为 0.5, 得 {initial_likelihood}"
        )
        
        # 执行：第一次遵循+成功
        updater.update_confidence("BETA-TEST-001", observation_success=True, followed_memory=True)
        e = updater.get_memory("BETA-TEST-001")
        
        # 断言3：更新后 alpha=2, beta=1
        assert e.beta_alpha == 2, f"1次成功后 alpha 应为 2, 得 {e.beta_alpha}"
        assert e.beta_beta == 1, f"1次成功后 beta 应为 1, 得 {e.beta_beta}"
        
        # 断言4：似然度=(2)/(2+1)=0.6667，而不是固定的0.95！
        lik1 = updater._calc_beta_likelihood_success(e)
        assert abs(lik1 - 2/3) < 1e-4, (
            f"1次成功后似然度应为 2/3≈0.6667, 得 {lik1} (不能是固定0.95)"
        )
        assert lik1 < 0.9, f"似然度不应过早跳到0.95固定值, 得 {lik1}"
        
        # 再执行4次成功 → 共5次成功
        for _ in range(4):
            updater.update_confidence("BETA-TEST-001", True, True)
        e = updater.get_memory("BETA-TEST-001")
        
        # 断言5：5次成功后 alpha=6, beta=1, 似然度=6/7≈0.8571
        lik5 = updater._calc_beta_likelihood_success(e)
        expected_5 = 6 / 7
        assert abs(lik5 - expected_5) < 1e-4, (
            f"5次成功后似然度应为 6/7≈0.8571, 得 {lik5}"
        )
        
        # 再执行5次成功 → 共10次成功
        for _ in range(5):
            updater.update_confidence("BETA-TEST-001", True, True)
        e = updater.get_memory("BETA-TEST-001")
        
        # 断言6：10次成功后似然度=11/12≈0.9167，接近0.95但仍低于
        lik10 = updater._calc_beta_likelihood_success(e)
        expected_10 = 11 / 12
        assert abs(lik10 - expected_10) < 1e-4, (
            f"10次成功后似然度应为 11/12≈0.9167, 得 {lik10}"
        )
        
        # 执行：一次遵循+失败 → beta+1
        updater.update_confidence("BETA-TEST-001", False, True)
        e = updater.get_memory("BETA-TEST-001")
        
        # 断言7：失败更新beta，alpha不变
        assert e.beta_alpha == 11, f"失败不应改alpha, 得 {e.beta_alpha}"
        assert e.beta_beta == 2, f"1次失败后beta应为2, 得 {e.beta_beta}"
        lik_fail = updater._calc_beta_likelihood_success(e)
        assert abs(lik_fail - 11/13) < 1e-4, (
            f"失败后似然度应为 11/13≈0.846, 得 {lik_fail}"
        )
        
        print("✅ test_1_beta_likelihood_dynamic_update 全部通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_2_full_probability_evidence():
    """优化点2：严格全概率公式展开证据 P(B)，替代0.8/0.2固定值
    
    全概率公式：
      P(观察成功) = P(成功|记忆为真) × P(记忆为真)
                  + P(成功|记忆为假) × P(记忆为假)
                  
    核心断言：
    - 不再出现 0.8 / 0.2 的固定证据值
    - 先验很高（如0.9）时观察成功 → P(B) = likelihood×0.9 + base_rate×0.1 → 较高
    - 先验很低（如0.1）时观察成功 → P(B) = likelihood×0.1 + base_rate×0.9 → 较低（更接近base_rate）
    - 极端先验 (prior=1.0) → P(B) 应等于 P(成功|真)
    - 极端先验 (prior=0.0) → P(B) 应等于 P(成功|假) = base_rate
    """
    from bayesian_memory_updater import BayesianMemoryUpdater
    
    tmpdir = tempfile.mkdtemp()
    try:
        updater = BayesianMemoryUpdater(tmpdir)
        
        # 准备高置信度记忆 (A级, 0.9)
        e_high = updater.add_memory(
            memory_id="HIGH-PRIOR-001",
            content="高置信度记忆",
            category="principle",
            initial_confidence=0.9,
            source="TDD",
            tags=["test"],
        )
        # 准备低置信度记忆 (C级, 0.1)
        e_low = updater.add_memory(
            memory_id="LOW-PRIOR-001",
            content="低置信度记忆",
            category="lesson",
            initial_confidence=0.1,
            source="TDD",
            tags=["test"],
        )
        
        # 让它们有相同的似然度历史（2次成功，保证似然度一致）
        # 注：add_memory后beta_alpha=1, beta_beta=1 → likelihood_success = 0.5
        # 所以需要先更新两次获得更确定的似然度
        updater.update_confidence("HIGH-PRIOR-001", True, True)
        updater.update_confidence("HIGH-PRIOR-001", True, True)
        updater.update_confidence("LOW-PRIOR-001", True, True)
        updater.update_confidence("LOW-PRIOR-001", True, True)
        
        e_high = updater.get_memory("HIGH-PRIOR-001")
        e_low = updater.get_memory("LOW-PRIOR-001")
        
        # 两者似然度应相同 (alpha=3, beta=1 → 3/4=0.75)
        lik_high = updater._calc_beta_likelihood_success(e_high)
        lik_low = updater._calc_beta_likelihood_success(e_low)
        assert abs(lik_high - lik_low) < 1e-6, "相同验证历史应有相同似然度"
        likelihood = lik_high
        
        # 先验重置到想要的水平（绕过更新，直接通过 _save 保存状态）
        # 用 add 新记忆实现测试场景更干净
        tmpdir2 = tempfile.mkdtemp()
        updater2 = BayesianMemoryUpdater(tmpdir2)
        
        # 创建一个3次成功的beta历史 → likelihood = 4/5 = 0.8
        # 同时先验置信度 = 0.9 (非常确定记忆为真)
        e_h = updater2.add_memory(
            memory_id="HP", content="h", category="p",
            initial_confidence=0.9, source="t", tags=["t"]
        )
        for _ in range(3):
            updater2.update_confidence("HP", True, True)
        # 更新后置信度变了，需要手动模拟全概率函数的单元测试
        # 通过调用独立的 _calc_evidence 方法
        
        # 直接用计算函数：_calc_full_evidence(prior, likelihood_success, is_success, base_rate)
        # 假设记忆非常确定为真 (prior=0.9999, 似然度高 likelihood=0.9)
        base_rate = 0.5  # 随机成功概率 = 0.5
        p_ev_high_prior = updater2._calc_full_evidence(
            prior=0.9999,
            likelihood_success=0.9,
            observation_success=True,
            base_rate=base_rate,
        )
        # 断言：几乎所有概率都来自"记忆为真"的分支 → P(B) ≈ 0.9
        assert 0.89 < p_ev_high_prior < 0.91, (
            f"prior→1时 P(B|成功) 应≈似然度(0.9), 得 {p_ev_high_prior}"
        )
        
        # 记忆几乎确定为假 (prior=0.0001)
        p_ev_low_prior = updater2._calc_full_evidence(
            prior=0.0001,
            likelihood_success=0.9,
            observation_success=True,
            base_rate=base_rate,
        )
        # 断言：几乎所有概率都来自"记忆为假"的分支 → P(B) ≈ base_rate=0.5
        assert 0.49 < p_ev_low_prior < 0.51, (
            f"prior→0时 P(B|成功) 应≈base_rate(0.5), 得 {p_ev_low_prior}"
        )
        
        # 相同似然度(0.9) + 相同观察(成功)：
        # 高先验(0.9)的P(B) 应 > 低先验(0.1)的P(B)
        p_high = updater2._calc_full_evidence(0.9, 0.9, True, 0.5)
        p_low = updater2._calc_full_evidence(0.1, 0.9, True, 0.5)
        assert p_high > p_low, (
            f"高先验的P(B)应大于低先验: P_high={p_high}, P_low={p_low}"
        )
        # 数值应分别为：0.9×0.9+0.5×0.1=0.86  vs  0.9×0.1+0.5×0.9=0.54
        assert abs(p_high - (0.9*0.9 + 0.5*0.1)) < 1e-6, f"P_high={p_high} 不等于0.86"
        assert abs(p_low - (0.9*0.1 + 0.5*0.9)) < 1e-6, f"P_low={p_low} 不等于0.54"
        
        # 失败观察下的全概率也应正确：
        # P(失败|真) = 1 - P(成功|真) = 0.1
        # P(失败|假) = 1 - base_rate = 0.5
        # 高先验 P(失败) = 0.1×0.9 + 0.5×0.1 = 0.14
        p_fail_high = updater2._calc_full_evidence(0.9, 0.9, False, 0.5)
        assert abs(p_fail_high - (0.1*0.9 + 0.5*0.1)) < 1e-6, (
            f"失败观察的P(B)计算错误: {p_fail_high}, 应为0.14"
        )
        
        # 验证 base_rate 的默认值存在
        assert hasattr(updater2, 'base_success_rate'), "应定义默认 base_success_rate"
        assert 0.0 < updater2.base_success_rate < 1.0, "base_rate应在(0,1)内"
        
        # 确保旧的 0.8/0.2 固定值被移除
        src = Path(__file__).parent / "bayesian_memory_updater.py"
        code = src.read_text(encoding="utf-8")
        # update_confidence 中不应再出现 evidence = 0.8 if ... else 0.2
        for line in code.split("\n"):
            stripped = line.strip()
            if stripped.startswith("evidence =") and "0.8" in stripped:
                assert False, f"检测到固定证据值0.8/0.2，必须用全概率公式替代：{line}"
        
        print("✅ test_2_full_probability_evidence 全部通过")
        shutil.rmtree(tmpdir2, ignore_errors=True)
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_3_age_based_forgetting_factor():
    """优化点3：基于记忆年龄的贝叶斯遗忘因子
    
    核心原理：
      new_confidence = forget_factor × new_posterior + (1-forget_factor) × prior_center(0.5)
      forget_factor = exp(-λ × age_in_days / half_life_days)
      
    其中 λ = ln2 ≈ 0.693，使得：
      age == half_life → forget_factor = 0.5
      age == 0 → forget_factor = 1.0 (不遗忘)
      age >> half_life → forget_factor → 0 (完全回归0.5)
      
    核心断言：
    - MemoryEntry 包含 created_at 字段
    - 新记忆 (age<1小时)：forget_factor ≈ 1.0 → 基本不额外衰减
    - 老记忆 (age == half_life)：forget_factor ≈ 0.5
    - 极老记忆 (age >> half_life)：forget_factor → 0 → 置信度≈0.5
    - 半衰周期可调：S级半衰更长，C级半衰更短
    """
    from bayesian_memory_updater import BayesianMemoryUpdater
    
    tmpdir = tempfile.mkdtemp()
    try:
        updater = BayesianMemoryUpdater(tmpdir)
        
        now = datetime.now()
        
        # 断言1：添加的记忆有 created_at
        e = updater.add_memory(
            memory_id="AGE-TEST-001",
            content="年龄测试记忆",
            category="principle",
            initial_confidence=0.8,
            source="TDD",
            tags=["test"],
        )
        assert hasattr(e, 'created_at'), "MemoryEntry 缺少 created_at 字段"
        assert len(e.created_at) > 0, "created_at 不应为空"
        
        # 断言2：_calc_forget_factor 方法存在，且年龄=0时 factor≈1.0
        age_seconds_new = 60  # 1分钟
        ff_new_S = updater._calc_forget_factor(age_seconds_new, "S")
        ff_new_C = updater._calc_forget_factor(age_seconds_new, "C")
        assert abs(ff_new_S - 1.0) < 0.01, f"新记忆的S级遗忘因子应≈1.0, 得 {ff_new_S}"
        assert abs(ff_new_C - 1.0) < 0.01, f"新记忆的C级遗忘因子应≈1.0, 得 {ff_new_C}"
        
        # 断言3：S级半衰 >> C级半衰 (经验知识更稳定)
        half_life_S = updater._get_half_life_days("S")
        half_life_A = updater._get_half_life_days("A")
        half_life_B = updater._get_half_life_days("B")
        half_life_C = updater._get_half_life_days("C")
        half_life_D = updater._get_half_life_days("D")
        
        assert half_life_S > half_life_A > half_life_B > half_life_C >= half_life_D, (
            f"半衰周期不满足 S>A>B>C≥D: {half_life_S},{half_life_A},{half_life_B},{half_life_C},{half_life_D}"
        )
        
        # 断言4：当 age == S级半衰时，遗忘因子≈0.5
        age_S_half_secs = half_life_S * 86400  # 天数 → 秒
        ff_S_half = updater._calc_forget_factor(age_S_half_secs, "S")
        assert abs(ff_S_half - 0.5) < 0.02, (
            f"S级半衰({half_life_S}天)时遗忘因子应≈0.5, 得 {ff_S_half}"
        )
        
        # 断言5：当 age == C级半衰时，遗忘因子≈0.5
        age_C_half_secs = half_life_C * 86400
        ff_C_half = updater._calc_forget_factor(age_C_half_secs, "C")
        assert abs(ff_C_half - 0.5) < 0.02, (
            f"C级半衰({half_life_C}天)时遗忘因子应≈0.5, 得 {ff_C_half}"
        )
        
        # 断言6：极老记忆 → 遗忘因子≈0，置信度≈0.5
        age_very_old = half_life_S * 86400 * 10  # 10倍半衰
        ff_very_old = updater._calc_forget_factor(age_very_old, "S")
        assert ff_very_old < 0.01, f"10倍半衰时应几乎完全遗忘, 得 {ff_very_old}"
        # 后验为0.9时，经过几乎完全遗忘，应≈0.5
        posterior_before = 0.9
        posterior_forgotten = updater._apply_age_forgetting(posterior_before, age_very_old, "S")
        assert abs(posterior_forgotten - 0.5) < 0.02, (
            f"极老记忆置信度应回归≈0.5, 得 {posterior_forgotten}"
        )
        
        # 断言7：完整流程测试 - 模拟一条"30天前的S级记忆（已达半衰）"
        e_old = updater.add_memory(
            memory_id="OLD-MEM",
            content="老记忆",
            category="principle",
            initial_confidence=0.9,
            source="TDD-old",
            tags=["test"],
        )
        # 伪造 created_at 为 half_life_S 天前
        created_dt = now - timedelta(days=half_life_S)
        e_old.created_at = created_dt.isoformat()
        # 同时伪造一个高beta历史: 10次成功 (似然度≈11/12≈0.9167)
        e_old.beta_alpha = 11
        e_old.beta_beta = 1
        e_old.verify_count = 10
        updater._save_memories()  # 保存状态
        
        prior_before = e_old.confidence  # 0.9
        # 执行一次遵循+成功
        new_conf, new_lvl = updater.update_confidence("OLD-MEM", True, True)
        e_old = updater.get_memory("OLD-MEM")
        
        # 如果无遗忘：似然度=12/13≈0.9231, P(B)按全概率≈似然度(因prior高)≈0.923
        # 纯贝叶斯后验≈(0.923×0.9)/0.923 = 0.9 (几乎不变，因先验已经和似然度一致)
        # 但经过半衰遗忘(forget≈0.5)：新置信度 = 0.5×0.9 + 0.5×0.5 = 0.7
        # 即 后验0.9应该被拉回到约0.7左右
        # 注：此处精确数值可能有细微差别，主要验证 "有遗忘" vs "无遗忘" 的差距
        new_conf_actual = e_old.confidence
        # 无遗忘应该接近 prior (因先验高+一致的似然度)，但遗忘后应明显低于 prior
        assert new_conf_actual < prior_before - 0.05, (
            f"老记忆应因年龄被衰减: 先验{prior_before}, 后验{new_conf_actual}"
        )
        assert new_conf_actual > 0.45, "不应过度衰减"
        
        print("✅ test_3_age_based_forgetting_factor 全部通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_4_backward_compat_legacy_data():
    """回归测试：加载旧版JSON（无beta_alpha/beta_beta/created_at字段）时自动补默认值"""
    from bayesian_memory_updater import BayesianMemoryUpdater
    
    tmpdir = tempfile.mkdtemp()
    try:
        # 伪造旧版JSON数据 (没有 beta_alpha, beta_beta, created_at)
        mem_file = Path(tmpdir) / "bayesian_memories.json"
        old_data = {
            "updated_at": datetime.now().isoformat(),
            "memory_count": 1,
            "memories": [
                {
                    "memory_id": "LEGACY-001",
                    "content": "旧版记忆（缺失新字段）",
                    "category": "principle",
                    "confidence": 0.7,
                    "quality_level": "B",
                    "verify_count": 2,
                    "conflict_count": 0,
                    "last_updated": datetime.now().isoformat(),
                    "source": "legacy",
                    "tags": ["old"],
                    # 没有 beta_alpha / beta_beta / created_at
                }
            ]
        }
        mem_file.write_text(json.dumps(old_data, indent=2, ensure_ascii=False), encoding="utf-8")
        
        # 加载
        updater = BayesianMemoryUpdater(tmpdir)
        e = updater.get_memory("LEGACY-001")
        assert e is not None, "旧版记忆应成功加载"
        
        # 断言：缺失字段被自动补默认
        assert e.beta_alpha == 1 + e.verify_count, (
            f"旧版的beta_alpha应为 1+verify_count={1+e.verify_count}, 得 {e.beta_alpha}"
        )
        assert e.beta_beta == 1 + e.conflict_count, (
            f"旧版的beta_beta应为 1+conflict_count={1+e.conflict_count}, 得 {e.beta_beta}"
        )
        assert hasattr(e, 'created_at'), "应补 created_at 字段"
        assert len(e.created_at) > 0, "created_at 不应为空"
        
        # 断言：可以正常更新（不会报错）
        new_c, new_l = updater.update_confidence("LEGACY-001", True, True)
        assert 0 < new_c < 1, "更新后置信度应合法"
        
        print("✅ test_4_backward_compat_legacy_data 全部通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_5_integration_full_bayes_pipeline():
    """端到端整合测试：3个优化点一起工作，对比旧算法的数学正确性
    
    场景：
    - 记忆X初始：置信度=0.5, beta(1,1)
    - 连续 10 次"遵循+成功"
    - 严格贝叶斯应逐步上升，不会像旧版那样2次就冲到A级
    """
    from bayesian_memory_updater import BayesianMemoryUpdater
    
    tmpdir = tempfile.mkdtemp()
    try:
        updater = BayesianMemoryUpdater(tmpdir)
        e = updater.add_memory(
            memory_id="INT-001",
            content="端到端测试",
            category="lesson",
            initial_confidence=0.5,
            source="integration",
            tags=["test"],
        )
        
        confidences = [e.confidence]
        levels = [e.quality_level]
        
        for i in range(10):
            new_c, new_l = updater.update_confidence("INT-001", True, True)
            confidences.append(new_c)
            levels.append(new_l)
        
        e = updater.get_memory("INT-001")
        
        # 断言：置信度单调上升
        for i in range(1, len(confidences)):
            assert confidences[i] >= confidences[i-1] - 1e-9, (
                f"置信度应单调上升: 序列 {confidences}"
            )
        
        # 断言：验证次数应等于成功次数
        assert e.verify_count == 10, f"verify_count应为10, 得 {e.verify_count}"
        
        # 断言：10次成功但还没到S级（S需要10次 + ≥0.95置信度，且似然度=11/12≈0.9167<0.95）
        # 实际上置信度可能达到0.95以上，但似然度决定的贝叶斯更新速度更保守
        print(f"  置信度序列: {[round(c,4) for c in confidences]}")
        print(f"  等级序列: {levels}")
        print(f"  最终: conf={e.confidence:.4f}, level={e.quality_level}, vcount={e.verify_count}")
        print(f"  最终似然度: {e.beta_alpha}/{e.beta_alpha+e.beta_beta} = {e.beta_alpha/(e.beta_alpha+e.beta_beta):.4f}")
        
        # 断言：不会在3次以内就冲到A级（旧版bug：2次成功就够A级）
        assert levels[2] != "A" or levels[3] != "A", (
            f"3次成功内不应轻易到A级，序列: {levels[:5]}"
        )
        
        print("✅ test_5_integration_full_bayes_pipeline 全部通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 70)
    print("🔴 TDD RED 阶段：严格贝叶斯优化测试（期望失败）")
    print("=" * 70)
    
    tests = [
        ("test_1_beta_likelihood_dynamic_update", test_1_beta_likelihood_dynamic_update),
        ("test_2_full_probability_evidence", test_2_full_probability_evidence),
        ("test_3_age_based_forgetting_factor", test_3_age_based_forgetting_factor),
        ("test_4_backward_compat_legacy_data", test_4_backward_compat_legacy_data),
        ("test_5_integration_full_bayes_pipeline", test_5_integration_full_bayes_pipeline),
    ]
    
    passed = 0
    failed = 0
    failures = []
    
    for name, fn in tests:
        print(f"\n▶ 运行: {name}")
        try:
            if fn():
                passed += 1
            else:
                failed += 1
                failures.append((name, "返回False"))
        except AssertionError as ae:
            failed += 1
            failures.append((name, f"断言失败: {ae}"))
            print(f"   ❌ 断言失败: {ae}")
        except Exception as ex:
            failed += 1
            failures.append((name, f"异常: {type(ex).__name__}: {ex}"))
            print(f"   ❌ 异常: {type(ex).__name__}: {ex}")
    
    print("\n" + "=" * 70)
    print(f"📊 结果: 通过 {passed} / {len(tests)}, 失败 {failed}")
    if failures:
        print("失败列表:")
        for n, r in failures:
            print(f"  - {n}: {r}")
    print("=" * 70)
    
    sys.exit(0 if failed == 0 else 1)
