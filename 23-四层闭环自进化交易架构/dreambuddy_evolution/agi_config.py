"""
agi_config — AGI 升级模块统一开关配置（HC-AGI-07）

所有新认知模块默认关闭，Shadow 模式验证 ≥7 天 + Sharpe 正向才能小流量。
通过环境变量可单独开启某个模块进行验证。

开关清单：
  enable_agi_core              AGI 总开关
  enable_shadow_rl_phase3      Shadow RL Phase3 训练
  enable_signature_engine      签名方法引擎
  enable_path_integral         路径积分最小阻力路径
  enable_neural_sde            Neural SDE 动态建模
  enable_timesfm_forecast      TimesFM 时序预测
  enable_deep_reasoning        深度学习推理引擎
  enable_causal_engine         因果推断引擎
  enable_counterfactual        反事实评估器
  enable_strategy_synthesizer  深度学习策略生成器
  enable_transfer_learning     跨资产迁移
  enable_meta_cognition        元认知门禁
  enable_uncertainty_quant     Conformal Prediction 不确定性量化
  enable_pattern_detection     头肩顶等形态检测
  enable_btc_regime_classifier BTC-美股相关性 regime 分类
  enable_three_factor_short    三因子共振做空
"""
from __future__ import annotations

import os
from typing import Any, Dict


# 默认配置（HC-AGI-07 覆盖：用户决策 2026-09-11 全部开启进入实盘验证）
AGI_SWITCHES: Dict[str, bool] = {
    "enable_agi_core": True,              # AGI 总开关
    "enable_shadow_rl_phase3": True,      # Shadow RL Phase3 训练
    "enable_signature_engine": True,      # 签名方法引擎
    "enable_path_integral": True,         # 路径积分最小阻力路径
    "enable_neural_sde": True,            # Neural SDE 动态建模
    "enable_timesfm_forecast": True,      # TimesFM 时序预测
    "enable_deep_reasoning": True,        # 深度学习推理引擎
    "enable_causal_engine": True,         # 因果推断引擎
    "enable_counterfactual": True,        # 反事实评估器
    "enable_strategy_synthesizer": True,  # 深度学习策略生成器
    "enable_transfer_learning": True,     # 跨资产迁移
    "enable_meta_cognition": True,        # 元认知门禁
    "enable_uncertainty_quant": True,     # Conformal Prediction 不确定性量化
    "enable_pattern_detection": True,     # 头肩顶等形态检测
    "enable_btc_regime_classifier": True, # BTC-美股相关性 regime 分类
    "enable_three_factor_short": True,    # 三因子共振做空
    "enable_hjb_solver": True,           # HJB PDE 最优路径求解器
    "enable_variational_opt": True,      # 变分法路径优化器
    "enable_contradiction_identifier": True,  # 主要矛盾识别器 (Phase 3.1)
    "enable_trend_continuation": True,        # 趋势延续性评分 (Phase 3.2)
    "enable_contradiction_feedback": True,     # 验证回流闭环 (Phase 3.5)
    # --- 阻力场升级开关 (SPEC-矛盾论实现断裂修复) ---
    "enable_microstructure_resistance": False,  # 6 组件微观阻力向量
    "enable_rv_contradiction_modulation": False,  # RV 层矛盾调制
    "enable_hjb_dominant": False,               # HJB 权重 70% 增强模式
    # --- Phase 1 外生力量度量 ---
    "enable_exogenous_strength": False,           # 外生力量度量器
    # --- Phase 2 因果传导 + 质变检测 ---
    "enable_granger_causality": False,            # Granger 因果检验
    "enable_structural_break_detection": False,   # 质变检测
    "enable_contradiction_shift_detection": False,  # 矛盾转化检测
    # --- Phase 3 弹性约束 + 反身性 ---
    "enable_elastic_constraint": False,            # 弹性约束
    "enable_reflexivity_monitor": False,           # 反身性监测
}


def get_switch(name: str, default: bool = False) -> bool:
    """获取开关状态.

    优先级：环境变量 > AGI_SWITCHES 配置 > default.

    Args:
        name: 开关名称
        default: 默认值
    Returns:
        bool: 开关状态
    """
    # 环境变量覆盖（大写，如 ENABLE_CAUSAL_ENGINE=1）
    env_key = name.upper()
    env_val = os.environ.get(env_key)
    if env_val is not None:
        return env_val.lower() in ("1", "true", "yes", "on")

    return AGI_SWITCHES.get(name, default)


def is_enabled(name: str) -> bool:
    """检查某模块是否启用（总开关 + 模块开关）"""
    if name != "enable_agi_core" and not get_switch("enable_agi_core"):
        return False
    return get_switch(name)


def get_all_switches() -> Dict[str, bool]:
    """返回所有开关的当前状态（含环境变量覆盖）"""
    return {name: get_switch(name, default) for name, default in AGI_SWITCHES.items()}


def list_enabled() -> Dict[str, bool]:
    """返回所有已启用的开关"""
    return {k: v for k, v in get_all_switches().items() if v}


def set_switch(name: str, value: bool) -> None:
    """运行时设置开关（不写入环境变量，仅当前进程）"""
    if name in AGI_SWITCHES:
        AGI_SWITCHES[name] = value


def reset_switches() -> None:
    """重置所有开关为默认值（全部关闭）"""
    for k in AGI_SWITCHES:
        AGI_SWITCHES[k] = False
