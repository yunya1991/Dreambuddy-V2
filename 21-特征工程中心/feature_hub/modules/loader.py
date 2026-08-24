"""loader — 从 config/feature_sets.yaml 加载模块和启用集合到 FeaturePipeline

提供 load_default_sets(pipe) 一键注册：
  1. 注册所有已知 Native 模块（crypto_morphology / elder_ray / triple_screen_trend /
     classic_indicators / five_domain_fc）
  2. 从 config/feature_sets.yaml 读取集合并 register_set
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "feature_sets.yaml"

# 模块名 → compute 函数的导入路径
_MODULE_IMPORTS = {
    "crypto_morphology": "feature_hub.modules.crypto_morphology",
    "elder_ray": "feature_hub.modules.elder_ray",
    "triple_screen_trend": "feature_hub.modules.triple_screen_trend",
    "classic_indicators": "feature_hub.modules.classic_indicators",
    "talib_aligned": "feature_hub.modules.talib_aligned",
    "five_domain_fc": "feature_hub.modules.five_domain_fc",
    "martin_features": "feature_hub.modules.martin_features",
    "fundamental_ratios": "feature_hub.modules.fundamental_ratios",
}


def load_default_sets(pipe) -> None:
    """注册所有 Native 模块 + 从 YAML 加载启用集合

    Args:
        pipe: FeaturePipeline 实例
    """
    import importlib

    # 1) 注册模块
    for name, module_path in _MODULE_IMPORTS.items():
        try:
            mod = importlib.import_module(module_path)
            if hasattr(mod, "compute"):
                pipe.register_module(name, mod.compute)
        except Exception as exc:
            logger.warning("[FeatureHub] module '%s' import failed: %s", name, exc)

    # 2) 从 YAML 加载集合
    sets = _load_yaml_sets()
    for set_name, modules in sets.items():
        pipe.register_set(set_name, modules)


def _load_yaml_sets() -> Dict[str, List[str]]:
    """解析 config/feature_sets.yaml，返回 {set_name: [module, ...]}"""
    try:
        import yaml
    except ImportError:
        logger.warning("[FeatureHub] PyYAML 未安装，使用内置默认集合")
        return _default_sets()

    if not _CONFIG_PATH.exists():
        logger.warning("[FeatureHub] 配置文件不存在: %s", _CONFIG_PATH)
        return _default_sets()

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    result: Dict[str, List[str]] = {}
    for set_name, cfg in (data.get("feature_sets") or {}).items():
        modules = (cfg or {}).get("modules") or []
        result[set_name] = modules
    return result


def _default_sets() -> Dict[str, List[str]]:
    """YAML 不可用时的内置默认集合"""
    return {
        "btc_morph_v6": ["crypto_morphology"],
        "alt_trend_ensemble": ["crypto_morphology", "elder_ray", "triple_screen_trend"],
        "triple_screen_only": ["triple_screen_trend"],
        "classic_talib_only": ["talib_aligned"],
        "equity_classic_trend": ["triple_screen_trend", "classic_indicators", "five_domain_fc"],
        "commodity_safe_haven": ["classic_indicators", "five_domain_fc", "elder_ray"],
    }
