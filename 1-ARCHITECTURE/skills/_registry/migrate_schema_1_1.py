#!/usr/bin/env python3
"""registry.json schema 1.0 -> 1.1 迁移（SPEC P0-1）。

只新增两个字段，不改现有结构：
  role: researcher | trader | risk | operator | coordinator
  tier: ["local" | "github" | "cloud"]  非空子集

推断规则（先 category 规则，name/description 关键词补正）：
  role  — 风险域关键词优先命中 risk，其余按 category 映射
  tier  — category 决定基础面，关键词增补；无任何命中则默认三端全开（并列入人工复核清单）

用法：
    python3 1-ARCHITECTURE/skills/_registry/migrate_schema_1_1.py [--dry-run]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REGISTRY = Path(__file__).with_name("registry.json")

# 风险域关键词：name 命中即判定；description 只用高特异度词（避免 "compression risk"/
# "risk plan"/"risk agent" 这类泛化表述把编排类 SKILL 误标为 risk）。
RISK_NAME_KEYWORDS = (
    "risk",
    "风控",
    "stop-loss",
    "stop_loss",
    "止损",
    "drawdown",
    "position-sizing",
    "position_sizing",
    "pretrade",
    "pre-trade",
    "compliance",
    "合规",
    "gatekeeper",
    "t3-risk",
)

RISK_DESC_KEYWORDS = (
    "stop-loss",
    "stop_loss",
    "止损",
    "停止损失",
    "移动止损",
    "drawdown",
    "position-sizing",
    "position_sizing",
    "pretrade",
    "pre-trade",
    "gatekeeper",
    "compliance",
)

CATEGORY_ROLE = {
    "trading": "trader",
    "research": "researcher",
    "tooling": "operator",
    "orchestration": "coordinator",
    "cognition": "researcher",
    "knowledge": "researcher",
    "memory": "researcher",
    "meta": "coordinator",
    "core": "coordinator",
    "governance": "coordinator",
    "support": "operator",
    "trigger": "operator",
    "collaboration": "coordinator",
}

CATEGORY_TIER_BASE = {
    "trading": ["cloud"],
    "research": ["local"],
    "tooling": ["local"],
    "orchestration": ["local", "github", "cloud"],
    "cognition": ["local", "cloud"],
    "knowledge": ["local", "cloud"],
    "memory": ["local", "cloud"],
    "meta": ["local", "github", "cloud"],
    "core": ["local", "github", "cloud"],
    "governance": ["local", "github", "cloud"],
    "support": ["local", "cloud"],
    "trigger": ["local", "cloud"],
    "collaboration": ["local", "github", "cloud"],
}

TIER_SIGNALS: dict[str, tuple[str, ...]] = {
    "cloud": (
        "cloud",
        "云端",
        "deploy",
        "部署",
        "server",
        "服务器",
        "systemd",
        "timer",
        "scheduler",
        "监控",
        "monitor",
        "alert",
        "报警",
        "live",
        "实盘",
        "remote",
        "远端",
        "生产",
        "backup",
        "备份",
        "restart",
        "重启",
        "服务",
        "snapshot",
    ),
    "github": ("github", " pr", "pr ", " ci", "commit", "提交", "merge", "release", "workflow"),
    "local": (
        "local",
        "本地",
        "dev",
        "开发",
        "spec",
        "design",
        "设计",
        "research",
        "调研",
        "tdd",
        "test",
        "测试",
        "refactor",
        "重构",
        "文档",
        "review",
        "评审",
        "backtest",
        "回测",
        "训练",
        "train",
    ),
}

TIER_ORDER = ["local", "github", "cloud"]


# 执行器类 SKILL 名字即定性：即使描述里提到"止损/风控"，其职责仍是执行 → trader
EXECUTOR_NAME_KEYWORDS = ("executor", "execution", "trader", "trading-executor")


def infer_role(skill: dict) -> str:
    name = skill.get("name", "").lower()
    desc = skill.get("description", "").lower()
    if any(k in name for k in RISK_NAME_KEYWORDS):
        return "risk"
    if not any(k in name for k in EXECUTOR_NAME_KEYWORDS):
        if any(k in desc for k in RISK_DESC_KEYWORDS):
            return "risk"
    return CATEGORY_ROLE.get(skill.get("category", ""), "coordinator")


def infer_tier(skill: dict) -> tuple[list[str], bool]:
    """返回 (tier, 是否走了默认兜底)。"""
    haystack = f"{skill.get('name', '')} {skill.get('description', '')} {skill.get('category', '')}".lower()
    tier = set(CATEGORY_TIER_BASE.get(skill.get("category", ""), []))
    for end, keywords in TIER_SIGNALS.items():
        if any(k in haystack for k in keywords):
            tier.add(end)
    if not tier:
        return TIER_ORDER, True
    return [t for t in TIER_ORDER if t in tier], False


def main() -> int:
    dry_run = "--dry-run" in sys.argv[1:]
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))

    fallback: list[str] = []
    role_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}

    for skill in data["skills"]:
        role = infer_role(skill)
        tier, used_fallback = infer_tier(skill)
        skill["role"] = role
        skill["tier"] = tier
        role_counts[role] = role_counts.get(role, 0) + 1
        tier_counts["+".join(tier)] = tier_counts.get("+".join(tier), 0) + 1
        if used_fallback:
            fallback.append(skill["name"])

    data["schema_version"] = "1.1"
    data["total_count"] = len(data["skills"])

    print(f"skills: {len(data['skills'])}  -> schema_version 1.1")
    print("role 分布:", json.dumps(role_counts, ensure_ascii=False))
    print("tier 分布:", json.dumps(tier_counts, ensure_ascii=False))
    print(f"默认兜底（需人工复核）: {len(fallback)} -> {fallback}")

    if dry_run:
        print("[dry-run] 未写盘")
        return 0

    REGISTRY.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {REGISTRY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
