"""
25-用户策略生成系统 - 基线策略库

内置基线策略集合（classic_10_strategies + 注册表 tier≥B），
作为策略知识库供 AI 参考和用户对比。基线策略只读。
"""
from typing import Any, Dict, List, Optional
from pathlib import Path

# 基线策略库数据路径
_BASELINE_DIR = Path(__file__).parent.parent / "data" / "baseline"
_BASELINE_DIR.mkdir(parents=True, exist_ok=True)

# 基线策略来源
_BASELINE_SOURCES = [
    "classic_10_strategies",  # 内置经典10策略
    "registry_tier_ab",        # 注册表中 tier>=B 的策略
]


def baseline_list() -> List[Dict[str, Any]]:
    """列出所有基线策略，含 metrics_summary"""
    # TODO: Phase 4 实现 - 从注册表加载 tier>=B 的策略
    return []


def baseline_get(strategy_id: str, source_zip: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """获取单个基线策略"""
    for b in baseline_list():
        if b.get("strategy_id") == strategy_id:
            if source_zip is None or b.get("source_zip") == source_zip:
                return b
    return None


def baseline_metrics(strategy_id: str, source_zip: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """获取基线策略的回测指标"""
    entry = baseline_get(strategy_id, source_zip)
    if entry:
        return entry.get("metrics_summary")
    return None
