"""Skill Recall Bridge — 集成 skill_indexer.recall_hook 到认知系统 recall 流程

提供 recall_with_skills() 函数，同时返回认知记忆 + SKILL 候选。
不修改认知系统核心代码（HC-1a 合规），通过桥接模式实现集成。

用法：
  from skill_recall_bridge import recall_with_skills
  result = recall_with_skills("TDD 开发 bug 修复")
  # result = {"memories": [...], "memory_count": N, "skill_candidates": [...], "skill_count": M}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# 添加认知系统路径（FAIL-OPEN：不可用时跳过）
_COGNITIVE_DIR = Path(__file__).resolve().parents[3] / "4-MEMORY" / "9-工具与接口"
if _COGNITIVE_DIR.exists() and str(_COGNITIVE_DIR) not in sys.path:
    sys.path.insert(0, str(_COGNITIVE_DIR))

try:
    from cognitive_loop_entry import get_cle
    _HAS_COGNITIVE = True
except Exception:
    _HAS_COGNITIVE = False

from skill_indexer import scan_skills, recall_hook, ALL_SKILL_ROOTS

# 复用 skill_indexer 的 ALL_SKILL_ROOTS（项目自有 SKILL 全量目录）
DEFAULT_SKILL_ROOTS = ALL_SKILL_ROOTS


def recall_with_skills(
    context: str,
    skill_roots: list[Path] | None = None,
    top_k: int = 5,
    min_quality: str = "C",
) -> dict[str, Any]:
    """同时检索认知记忆 + SKILL 候选。

    Args:
        context: 检索上下文关键词
        skill_roots: SKILL 扫描路径，默认 .trae/skills + 1-ARCHITECTURE/skills
        top_k: 认知记忆返回数
        min_quality: 认知记忆最低质量等级

    Returns:
        {
            "memories": [...],          # 认知系统 recall 结果
            "memory_count": int,
            "skill_candidates": [...],  # skill_indexer.recall_hook 结果
            "skill_count": int,
        }
    """
    roots = skill_roots or DEFAULT_SKILL_ROOTS

    # 认知记忆检索（FAIL-OPEN：不可用时返回空）
    memories: list[dict[str, Any]] = []
    if _HAS_COGNITIVE:
        try:
            cle = get_cle()
            memories = cle.recall(context, top_k=top_k, min_quality=min_quality) or []
        except Exception:
            memories = []

    # SKILL 候选检索
    entries = scan_skills(roots)
    skill_candidates = recall_hook(context, entries)

    return {
        "memories": memories,
        "memory_count": len(memories),
        "skill_candidates": skill_candidates,
        "skill_count": len(skill_candidates),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Recall with SKILL candidates")
    parser.add_argument("--context", required=True, help="检索上下文关键词")
    parser.add_argument("--top-k", type=int, default=5, help="认知记忆返回数")
    parser.add_argument("--min-quality", default="C", help="最低质量等级")
    parser.add_argument("--roots", nargs="*", default=None, help="SKILL 扫描路径")
    args = parser.parse_args()

    roots = [Path(r) for r in args.roots] if args.roots else None
    result = recall_with_skills(args.context, roots, args.top_k, args.min_quality)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
