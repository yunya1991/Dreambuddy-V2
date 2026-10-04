"""Skill Facets — 分面分类推断。

借鉴图书馆学 FAST 分面分类法：用多个正交维度替代扁平 category。
facets 维度：domain / task_type / potency / resource_cost / execution_mode

工程约束：HC-1a（独立模块）/ FAIL-OPEN / 零回归
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# 分面键定义
FACET_KEYS = ("domain", "task_type", "potency", "resource_cost", "execution_mode")

# 默认 facets
DEFAULT_FACETS = {
    "domain": "uncategorized",
    "task_type": "general",
    "potency": "unipotent",
    "resource_cost": "medium",
    "execution_mode": "auto",
}

# category → domain 映射
_CATEGORY_TO_DOMAIN = {
    "trading": "trading",
    "trading-core": "trading",
    "memory": "memory",
    "orchestration": "architecture",
    "governance": "governance",
    "tooling": "tooling",
    "yijing": "trading",
    "hermes": "architecture",
    "agent-collab": "architecture",
    "graph-compression": "tooling",
    "system-kernel": "architecture",
    "experiment": "trading",
}

# 路径关键词 → domain 映射
_PATH_TO_DOMAIN = {
    "6-TRADING": "trading",
    "4-MEMORY": "memory",
    "1-ARCHITECTURE": "architecture",
    "11-易经推理系统": "trading",
    "24-图结构上下文压缩": "tooling",
    "AGENT协作工具": "architecture",
    "deploy": "architecture",
    "experiments": "trading",
}

# trigger 关键词 → task_type 映射
_TRIGGER_TO_TASK_TYPE = [
    (("调研", "research", "市场调研", "技术调研"), "research"),
    (("bug", "修复", "排障", "根因", "5why"), "bugfix"),
    (("tdd", "测试驱动", "red-green", "红绿"), "dev"),
    (("开发", "写代码", "实现"), "dev"),
    (("回测", "backtest", "验证"), "verification"),
    (("优化", "调参", "bayesian"), "optimization"),
    (("治理", "索引", "registry"), "governance"),
    (("协作", "collab", "编排"), "orchestration"),
]


def infer_facets(
    category: str = "",
    triggers: list[str] | None = None,
    path: Path | None = None,
) -> dict[str, str]:
    """从 category / triggers / path 推断 facets。

    Args:
        category: SKILL 的 category 字段
        triggers: SKILL 的 triggers 列表
        path: SKILL.md 路径

    Returns:
        facets dict（domain/task_type/potency/resource_cost/execution_mode）
    """
    triggers = triggers or []
    facets = dict(DEFAULT_FACETS)

    # domain: path 优先（物理位置更准确），其次 category
    domain = None
    if path is not None:
        path_str = str(path)
        for key, d in _PATH_TO_DOMAIN.items():
            if key in path_str:
                domain = d
                break
    if domain is None:
        domain = _CATEGORY_TO_DOMAIN.get(category)
    if domain:
        facets["domain"] = domain

    # task_type: 从 triggers 推断
    for keywords, tt in _TRIGGER_TO_TASK_TYPE:
        if any(any(kw in t.lower() for kw in keywords) for t in triggers):
            facets["task_type"] = tt
            break

    return facets
