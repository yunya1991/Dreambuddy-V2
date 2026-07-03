"""
Dreambuddy OS — SKILL 适配器

将 6-TRADING/skills/ 或其他位置的 SKILL.md 包装为 Node。

设计:
    - 读取 SKILL.md 元信息（node_id / chain / tokens）
    - 调用 SKILL 执行入口（脚本 / API / MCP）
    - 将执行结果转为 NodeResult

P0 阶段: 接口 + 占位实现
P1 阶段: 真正接入 SKILL 执行机制
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseAdapter
from ..registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ============================================================
# SKILL 元信息解析
# ============================================================

def parse_skill_metadata(skill_md_path: str) -> Dict[str, Any]:
    """解析 SKILL.md 的元信息

    从 frontmatter / 标题 / 内容中提取:
        - node_id
        - name
        - chain (A/C/F/G/T)
        - description
        - estimated_tokens
        - entry_point (脚本路径 / API endpoint)
    """
    path = Path(skill_md_path)
    if not path.exists():
        return {}

    content = path.read_text(encoding="utf-8")
    meta: Dict[str, Any] = {
        "skill_path": str(path),
        "node_id": path.stem,  # 文件名作为默认 ID
        "name": "",
        "chain": "",
        "description": "",
        "estimated_tokens": 0,
        "entry_point": "",
    }

    # 从 frontmatter 解析
    fm = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if fm:
        for line in fm.group(1).split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                k = k.strip().lower()
                v = v.strip()
                if k in ("node_id", "id"):
                    meta["node_id"] = v
                elif k in ("name", "title"):
                    meta["name"] = v
                elif k in ("chain", "domain"):
                    meta["chain"] = v
                elif k in ("tokens", "estimated_tokens"):
                    meta["estimated_tokens"] = int(v) if v.isdigit() else 0
                elif k == "entry":
                    meta["entry_point"] = v

    # 从一级标题提取 name
    if not meta["name"]:
        m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if m:
            meta["name"] = m.group(1).strip()

    # 从文件路径推断 chain
    if not meta["chain"]:
        parent = path.parent.name.lower()
        if parent.startswith("a"):
            meta["chain"] = "A"
        elif parent.startswith("c"):
            meta["chain"] = "C"
        elif parent.startswith("f"):
            meta["chain"] = "F"

    return meta


# ============================================================
# SKILL 节点
# ============================================================

class SkillNode(BaseNode):
    """SKILL 节点 — 包装 SKILL.md 定义的能力

    P0: 占位实现，仅记录 SKILL 元信息
    P1: 真正调用 SKILL 执行入口
    """

    def __init__(self, skill_path: str, node_id: str = "",
                 name: str = "", chain: str = "",
                 estimated_tokens: int = 0, **kwargs):
        super().__init__(config=kwargs)
        self.skill_path = skill_path
        self.node_id = node_id
        self.name = name
        self.chain = chain
        self.estimated_tokens = estimated_tokens

    def execute_core(self, state: State) -> NodeResult:
        # P0: 占位实现
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.DEGRADED,
            confidence=0.0,
            error=f"SKILL 执行机制尚未实现 (skill={self.skill_path})",
            outputs={"skill_path": self.skill_path},
        )


# ============================================================
# SKILL 适配器
# ============================================================

class SkillAdapter(BaseAdapter):
    """SKILL 适配器 — 将 SKILL.md 包装为 Node

    用法:
        adapter = SkillAdapter()
        node = adapter.to_node({
            "type": "skill",
            "path": "6-TRADING/skills/A0_contradiction/SKILL.md",
        })
    """

    adapter_type = "skill"

    def can_handle(self, config: Dict[str, Any]) -> bool:
        return config.get("type") == "skill" and "path" in config

    def to_node(self, config: Dict[str, Any]) -> SkillNode:
        skill_path = config["path"]

        # 尝试解析 SKILL.md 元信息
        meta = parse_skill_metadata(skill_path) if os.path.exists(skill_path) else {}

        return SkillNode(
            skill_path=skill_path,
            node_id=config.get("node_id") or meta.get("node_id", ""),
            name=config.get("name") or meta.get("name", ""),
            chain=config.get("chain") or meta.get("chain", ""),
            estimated_tokens=meta.get("estimated_tokens", 0),
        )
