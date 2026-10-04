"""SKILL 候选挖掘器 — 从认知记忆中自动挖掘可复用为 SKILL 的 task pattern

借鉴自然语言处理中的 n-gram / 关键词聚类思路：
1. 从 cognitive_memory.db 提取 hermes反思 或 SKILL 相关记忆
2. 提取关键词模式（中文/英文混合）
3. 按 pattern 聚类，出现次数 >= min_occurrences → 候选
4. 生成 SKILL.md frontmatter 草稿（status: proposed）

FAIL-OPEN：DB 不可读或为空 → 返回空列表，不抛异常。
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ───────────────────────────── 关键词提取 ─────────────────────────────

# 中文/英文关键词提取（排除停用词）
_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "have", "been",
    "will", "was", "are", "not", "but", "can", "has", "had", "was",
    "流程", "建议", "形成", "衍生", "可复用", "第", "次", "一个", "我们",
    "可以", "需要", "使用", "通过", "进行", "基于", "以及", "或者",
}

def _extract_keywords(text: str) -> list[str]:
    """从文本提取英文词和中文 2-4 字词（粗粒度）。"""
    if not text:
        return []
    words: list[str] = []
    # 英文词（>=3 字符）
    words.extend(re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text))
    # 中文 2-4 字片段
    for m in re.findall(r"[\u4e00-\u9fa5]{2,4}", text):
        words.append(m)
    return [w.lower() for w in words if w.lower() not in _STOPWORDS and len(w) >= 2]


def _pattern_signature(text: str) -> str:
    """生成 text 的 pattern 签名：取频次最高的 2-3 个关键词拼接。"""
    kws = _extract_keywords(text)
    if not kws:
        return ""
    # 取前 3 个关键词（按出现顺序去重）
    seen: list[str] = []
    for k in kws:
        if k not in seen:
            seen.append(k)
        if len(seen) >= 3:
            break
    return "_".join(seen)


# ───────────────────────────── 记忆查询 ─────────────────────────────

def _fetch_skill_memories(db_path: Path) -> list[dict]:
    """从认知记忆 DB 查询 hermes/SKILL 相关记忆。"""
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT id, content, tags FROM memories "
            "WHERE tags LIKE '%hermes%' OR tags LIKE '%SKILL%' OR content LIKE '%hermes%'"
        )
        rows = cur.fetchall()
        conn.close()
        results = []
        for mem_id, content, tags in rows:
            try:
                tag_list = tags.split(",") if isinstance(tags, str) else []
            except Exception:
                tag_list = []
            results.append({"id": mem_id, "content": content or "", "tags": tag_list})
        return results
    except Exception:
        return []  # FAIL-OPEN


# ───────────────────────────── 候选挖掘 ─────────────────────────────

@dataclass
class SkillCandidate:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    category: str = "uncategorized"
    evidence_count: int = 0
    source_memories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "category": self.category,
            "evidence_count": self.evidence_count,
            "source_memories": self.source_memories,
        }


def mine_candidates(db_path: Path | str | None = None, min_occurrences: int = 3) -> list[dict]:
    """挖掘 SKILL 候选。

    Args:
        db_path: 认知记忆 DB 路径（默认使用项目内 DB）
        min_occurrences: pattern 出现次数阈值

    Returns:
        候选字典列表（evidence_count >= min_occurrences）
    """
    if db_path is None:
        db_path = Path(__file__).resolve().parent.parent.parent.parent / "4-MEMORY" / "data" / "cognitive_memory.db"
    else:
        db_path = Path(db_path)

    memories = _fetch_skill_memories(db_path)
    if not memories:
        return []

    # 按 pattern 签名聚类
    clusters: dict[str, list[dict]] = {}
    for mem in memories:
        sig = _pattern_signature(mem["content"])
        if not sig:
            continue
        clusters.setdefault(sig, []).append(mem)

    candidates: list[SkillCandidate] = []
    for sig, mems in clusters.items():
        if len(mems) < min_occurrences:
            continue
        # 生成候选名
        name = _derive_skill_name(sig, mems)
        description = f"自动挖掘自 {len(mems)} 条 hermes 记忆，pattern: {sig.replace('_', ' ')}"
        triggers = _derive_triggers(sig, mems)
        category = _infer_category(mems)
        candidates.append(SkillCandidate(
            name=name,
            description=description,
            triggers=triggers,
            category=category,
            evidence_count=len(mems),
            source_memories=[m["id"] for m in mems],
        ))

    # 按 evidence_count 降序
    candidates.sort(key=lambda c: c.evidence_count, reverse=True)
    return [c.to_dict() for c in candidates]


def _derive_skill_name(sig: str, mems: list[dict]) -> str:
    """从 pattern 签名推导 SKILL 名（dream- 前缀）。"""
    parts = sig.split("_")[:3]
    slug = "-".join(parts)
    return f"dream-{slug}"


def _derive_triggers(sig: str, mems: list[dict]) -> list[str]:
    """从记忆内容推导 triggers。"""
    kws = _extract_keywords(" ".join(m["content"] for m in mems))
    counter = Counter(kws)
    return [w for w, _ in counter.most_common(5)]


def _infer_category(mems: list[dict]) -> str:
    """从记忆标签推断 category。"""
    all_tags: list[str] = []
    for m in mems:
        all_tags.extend(m.get("tags", []))
    tag_str = " ".join(all_tags).lower()
    if "tdd" in tag_str or "测试" in tag_str:
        return "development"
    if "research" in tag_str or "调研" in tag_str:
        return "research"
    if "bugfix" in tag_str or "bug" in tag_str:
        return "bugfix"
    if "skill" in tag_str or "治理" in tag_str:
        return "governance"
    return "uncategorized"


# ───────────────────────────── SKILL 草稿生成 ─────────────────────────────

def generate_skill_draft(candidate: dict) -> str:
    """从候选生成 SKILL.md frontmatter 草稿。"""
    name = candidate.get("name", "dream-unnamed")
    description = candidate.get("description", "")
    triggers = candidate.get("triggers", [])
    category = candidate.get("category", "uncategorized")
    evidence = candidate.get("evidence_count", 0)
    sources = candidate.get("source_memories", [])

    trigger_yaml = "\n".join(f"  - {t}" for t in triggers) if triggers else "  []"
    sources_yaml = "\n".join(f"  - {s}" for s in sources[:5]) if sources else "  []"

    return f"""---
name: {name}
description: {description}
version: 0.1.0
status: proposed
category: {category}
triggers:
{trigger_yaml}
depends_on: []
provides: []
cognitive_links: []
evidence_count: {evidence}
source_memories:
{sources_yaml}
created: 2026-09-29
---

# {name}

> 自动挖掘生成的 SKILL 草稿，请人工审核后定稿。

{description}

## 触发条件

{', '.join(triggers) if triggers else '(待定)'}

## 流程

(待补充)
"""


# ───────────────────────────── 自动创建 SKILL ─────────────────────────────

def _load_init_skill():
    """动态加载 skill-creator 的 init_skill 模块。

    搜索路径（按优先级）：
    1. 1-ARCHITECTURE/skills/skill-creator/scripts/init_skill.py
    2. .trae/skills/skill-creator/scripts/init_skill.py
    3. 11-易经推理系统/skills/4-GENERIC/skill-creator/scripts/init_skill.py

    FAIL-OPEN：找不到则返回 None，调用方降级为仅输出草稿。
    """
    import importlib.util

    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "skill-creator" / "scripts" / "init_skill.py",
        here.parent.parent.parent / ".trae" / "skills" / "skill-creator" / "scripts" / "init_skill.py",
        here.parent.parent.parent / "11-易经推理系统" / "skills" / "4-GENERIC" / "skill-creator" / "scripts" / "init_skill.py",
    ]
    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("skill_init", str(path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


def create_skill_from_candidate(
    candidate: dict,
    output_root: Path | str,
    enrich_body: bool = True,
) -> Path | None:
    """从候选自动创建 SKILL 目录并填充 frontmatter。

    流程：
    1. 调用 init_skill 创建目录结构（SKILL.md + scripts/ + references/ + assets/）
    2. 用 candidate 数据填充 frontmatter（name/description/triggers/category/cognitive_links）
    3. 可选：生成包含证据来源的 body 草稿

    Args:
        candidate: mine_candidates() 返回的候选字典
        output_root: skill 输出根目录（如 1-ARCHITECTURE/skills）
        enrich_body: 是否用 candidate 证据填充 body

    Returns:
        创建的 skill 目录路径，失败返回 None
    """
    init_module = _load_init_skill()
    if init_module is None:
        print("⚠️  init_skill.py 未找到，跳过自动创建（仅输出草稿）")
        return None

    name = candidate.get("name", "dream-unnamed")
    output_root = Path(output_root)

    # Step 1: 创建目录结构
    skill_dir = init_module.init_skill(name, str(output_root))
    if skill_dir is None:
        return None

    # Step 2: 填充 frontmatter
    skill_md = Path(skill_dir) / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")

    # 替换 description
    desc = candidate.get("description", f"Auto-mined skill: {name}")
    content = content.replace(
        "description: [TODO: Complete and informative explanation of what the skill does and when to use it. Include WHEN to use this skill - specific scenarios, file types, or tasks that trigger it.]",
        f'description: "{desc}"',
    )

    # 替换 triggers
    triggers = candidate.get("triggers", [])
    triggers_yaml = "[" + ", ".join(f'"{t}"' for t in triggers) + "]" if triggers else "[]"
    content = content.replace("triggers: []", f"triggers: {triggers_yaml}")

    # 替换 category
    category = candidate.get("category", "uncategorized")
    content = content.replace(
        "category: other          # trading|technical|orchestration|research|meta|bugfix|development|other",
        f"category: {category}          # trading|technical|orchestration|research|meta|bugfix|development|other",
    )

    # 填充 cognitive_links（来源记忆 ID）
    sources = candidate.get("source_memories", [])
    if sources:
        links_yaml = "[" + ", ".join(sources[:5]) + "]"
        content = content.replace("cognitive_links: []", f"cognitive_links: {links_yaml}")

    # Step 3: 可选 — 用证据填充 body 的 Overview
    if enrich_body:
        evidence = candidate.get("evidence_count", 0)
        overview_inject = (
            f"\n> **Auto-mined from {evidence} cognitive memories** "
            f"(pattern-based candidate). Review and refine before use.\n"
        )
        content = content.replace(
            "## Overview\n\n[TODO: 1-2 sentences explaining what this skill enables]",
            f"## Overview\n\n[TODO: 1-2 sentences explaining what this skill enables]\n{overview_inject}",
        )

    skill_md.write_text(content, encoding="utf-8")
    print(f"✅ 已填充 frontmatter: name={name}, category={category}, triggers={len(triggers)}")
    return Path(skill_dir)


def mine_and_create(
    output_root: Path | str,
    db_path: Path | str | None = None,
    min_occurrences: int = 3,
    max_create: int = 3,
) -> list[Path]:
    """端到端流水线：挖掘候选 → 自动创建 SKILL。

    Args:
        output_root: skill 输出根目录
        db_path: 认知记忆 DB 路径（默认项目内 DB）
        min_occurrences: pattern 出现次数阈值
        max_create: 最多自动创建的 SKILL 数量（防止一次性生成过多）

    Returns:
        成功创建的 skill 目录路径列表
    """
    candidates = mine_candidates(db_path=db_path, min_occurrences=min_occurrences)
    if not candidates:
        print("ℹ️  未挖掘到符合条件的 SKILL 候选")
        return []

    print(f"🔍 挖掘到 {len(candidates)} 个候选，最多创建 {max_create} 个：")
    created: list[Path] = []
    for cand in candidates[:max_create]:
        print(f"\n  → 创建 {cand['name']} (evidence={cand['evidence_count']})")
        skill_dir = create_skill_from_candidate(cand, output_root)
        if skill_dir is not None:
            created.append(skill_dir)

    print(f"\n✅ 自动创建完成：{len(created)}/{min(len(candidates), max_create)} 个 SKILL")
    return created


# ───────────────────────────── 测试辅助 ─────────────────────────────

def _write_test_db(db_path: Path, memories: list[dict]) -> None:
    """测试用：写入临时认知记忆 DB。"""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS memories ("
        "id TEXT PRIMARY KEY, content TEXT, vector BLOB, quality_level TEXT, "
        "confidence REAL, tags TEXT, memory_type TEXT, source TEXT, "
        "created_at TEXT, updated_at TEXT, verify_count INTEGER)"
    )
    for m in memories:
        tags = ",".join(m.get("tags", []))
        cur.execute(
            "INSERT INTO memories (id, content, tags, quality_level, confidence, verify_count) "
            "VALUES (?, ?, ?, 'C', 0.2, 0)",
            (m["id"], m["content"], tags),
        )
    conn.commit()
    conn.close()


# ───────────────────────────── CLI ─────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "create":
        # 端到端流水线：挖掘候选 → 自动创建 SKILL
        # 用法: skill_candidate_miner.py create <output_root> [min_occurrences] [max_create]
        output_root = sys.argv[2] if len(sys.argv) > 2 else "1-ARCHITECTURE/skills"
        min_occ = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        max_create = int(sys.argv[4]) if len(sys.argv) > 4 else 3
        mine_and_create(output_root, min_occurrences=min_occ, max_create=max_create)
    else:
        # 默认：仅挖掘候选并打印
        db = sys.argv[1] if len(sys.argv) > 1 else None
        cands = mine_candidates(db_path=db)
        print(f"挖掘到 {len(cands)} 个 SKILL 候选：")
        for c in cands:
            print(f"  {c['name']} (evidence={c['evidence_count']}, category={c['category']})")
