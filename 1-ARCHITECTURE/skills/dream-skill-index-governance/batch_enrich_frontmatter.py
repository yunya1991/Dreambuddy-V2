"""批量补全 SKILL.md frontmatter 缺失字段。

为 ALL_SKILL_ROOTS 下所有 SKILL.md 补全：
  status (默认 active) / category (按目录推断) / triggers (按 name 推断) /
  depends_on ([]) / provides ([]) / cognitive_links ([])

不修改已有字段，只在 closing --- 前插入缺失字段。
安全模式：先 dry-run 预览，加 --apply 才真正写入。

用法：
  python3 batch_enrich_frontmatter.py --dry-run
  python3 batch_enrich_frontmatter.py --apply
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

# 复用 skill_indexer 的 ALL_SKILL_ROOTS
sys.path.insert(0, str(Path(__file__).parent))
from skill_indexer import ALL_SKILL_ROOTS  # noqa: E402

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 目录 → category 映射
_CATEGORY_MAP: dict[str, str] = {
    "6-TRADING": "trading",
    "11-易经推理系统": "yijing",
    "4-MEMORY": "memory",
    "deploy/hermes": "hermes",
    "1-ARCHITECTURE": "architecture",
    ".trae": "trae",
    "experiments": "experiment",
    "AGENT协作工具": "agent-collab",
    "24-图结构上下文压缩": "graph-compression",
}

_COMMON_PREFIXES = {"dream", "skill", "agent", "system", "auto"}


def _infer_category(path: Path) -> str:
    s = str(path)
    for key, cat in _CATEGORY_MAP.items():
        if key in s:
            return cat
    return "uncategorized"


def _infer_triggers(name: str) -> list[str]:
    """从 SKILL name 推断 triggers。"""
    parts = [p for p in re.split(r"[-_]", name.lower()) if p]
    # 去掉常见前缀
    triggers = [p for p in parts if p not in _COMMON_PREFIXES]
    if not triggers:
        triggers = parts[:2] if parts else [name]
    # 最多 4 个
    return triggers[:4]


def _ensure_list(value: Any) -> bool:
    return isinstance(value, list)


def enrich_frontmatter(skill_md: Path) -> tuple[bool, list[str]]:
    """补全单个 SKILL.md 的 frontmatter。返回 (是否修改, 添加的字段列表)。"""
    raw = skill_md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return False, ["no_frontmatter"]

    fm_text = m.group(1)
    try:
        fm = yaml.safe_load(fm_text)
    except Exception:
        return False, ["invalid_yaml"]

    if not isinstance(fm, dict):
        return False, ["not_a_dict"]

    added: list[str] = []
    fields_to_add: list[str] = []

    # status
    if "status" not in fm:
        fields_to_add.append("status: active")
        added.append("status")

    # category
    if "category" not in fm:
        cat = _infer_category(skill_md)
        fields_to_add.append(f"category: {cat}")
        added.append("category")

    # triggers
    if "triggers" not in fm:
        name = str(fm.get("name", skill_md.parent.name))
        trig = _infer_triggers(name)
        trig_str = "[" + ", ".join(trig) + "]"
        fields_to_add.append(f"triggers: {trig_str}")
        added.append("triggers")

    # depends_on / provides / cognitive_links
    for fld in ("depends_on", "provides", "cognitive_links"):
        if fld not in fm:
            fields_to_add.append(f"{fld}: []")
            added.append(fld)

    if not fields_to_add:
        return False, []

    # 在 closing --- 前插入
    closing_pos = m.end()  # 指向 closing --- 之后
    # 找到 closing --- 的位置
    # m.group(0) 是整个 frontmatter 块包括 --- 和 closing ---
    full_fm = m.group(0)
    # 从 full_fm 末尾往前找 closing ---
    # full_fm 以 "---\n" 结尾
    insert_text = "\n".join(fields_to_add) + "\n"
    # 把 closing --- 替换为 字段 + closing ---
    new_full_fm = full_fm[:-4] + insert_text + "---\n"  # -4 去掉末尾的 "---\n"

    new_raw = raw[:m.start()] + new_full_fm + raw[m.end():]
    skill_md.write_text(new_raw, encoding="utf-8")
    return True, added


def main() -> None:
    apply = "--apply" in sys.argv
    dry_run = not apply

    total = 0
    modified = 0
    skipped = 0
    no_fm = 0

    for root in ALL_SKILL_ROOTS:
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            total += 1
            changed, added = enrich_frontmatter(skill_md)
            if "no_frontmatter" in added or "invalid_yaml" in added or "not_a_dict" in added:
                no_fm += 1
                continue
            if changed:
                modified += 1
                if dry_run:
                    print(f"[dry-run] {skill_md.relative_to(root.parent.parent) if root.parent.parent.exists() else skill_md}: +{added}")
                else:
                    print(f"[applied] {skill_md.name}: +{added}")
            else:
                skipped += 1

    print(f"\n=== summary ===")
    print(f"total: {total}")
    print(f"modified: {modified}")
    print(f"already_complete: {skipped}")
    print(f"no_frontmatter/invalid: {no_fm}")
    if dry_run:
        print("\n(dry-run mode, no files changed. add --apply to write)")


if __name__ == "__main__":
    main()
