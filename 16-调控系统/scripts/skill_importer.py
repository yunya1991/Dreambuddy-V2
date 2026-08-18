#!/usr/bin/env python3
"""
SKILL.md 兼容导入器 — 借鉴 Grok Build 的「读 Claude/Cursor MCP 配置」思路

功能：
1. 解析 SKILL.md（本项目风格 + Superpowers/Claude Code 风格）
2. 标准化为 SkillMeta 对象
3. 双注册：同时注册到 SkillEngine 和 NodeRegistry

用法:
  python -m scripts.skill_importer scan
  python -m scripts.skill_importer import dream-strategy-research
  python -m scripts.skill_importer list
  python -m scripts.skill_importer validate <skill_path>
"""
import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@dataclass
class SkillPhase:
    phase_id: str
    name: str
    description: str = ""
    inputs: List[Dict] = field(default_factory=list)
    outputs: List[Dict] = field(default_factory=list)


@dataclass
class SkillMeta:
    skill_name: str
    version: str
    description: str
    tags: List[str] = field(default_factory=list)
    trigger_words: List[str] = field(default_factory=list)
    supported_intents: List[str] = field(default_factory=list)
    phases: List[SkillPhase] = field(default_factory=list)
    skill_path: str = ""
    handler: Optional[Callable] = None
    source_format: str = "native"


class SKILLMdParser:
    FIELD_ALIASES = {
        "triggers": "trigger_words",
        "intents": "supported_intents",
        "keywords": "trigger_words",
        "category": "tags",
        "categories": "tags",
    }

    def parse(self, skill_md_path: Path) -> SkillMeta:
        content = skill_md_path.read_text(encoding="utf-8")

        frontmatter = self._parse_frontmatter(content)
        phases = self._parse_phases(content)

        skill_name = frontmatter.get("name", skill_md_path.parent.name)
        version = frontmatter.get("version", "1.0.0")
        description = frontmatter.get("description", "")
        tags = self._parse_list_field(frontmatter, "tags")
        trigger_words = self._parse_list_field(frontmatter, "trigger_words")
        supported_intents = self._parse_list_field(frontmatter, "supported_intents")

        source_format = self._detect_format(frontmatter)

        return SkillMeta(
            skill_name=skill_name,
            version=version,
            description=description,
            tags=tags,
            trigger_words=trigger_words,
            supported_intents=supported_intents,
            phases=phases,
            skill_path=str(skill_md_path),
            source_format=source_format,
        )

    def _parse_frontmatter(self, content: str) -> Dict[str, Any]:
        if not content.startswith("---"):
            return {}

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}

        fm_text = parts[1].strip()
        result = {}

        lines = fm_text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith("#"):
                i += 1
                continue

            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")

                if key in self.FIELD_ALIASES:
                    key = self.FIELD_ALIASES[key]

                if val.startswith("["):
                    end_bracket = self._find_matching_bracket(lines, i, "[")
                    list_content = "\n".join(lines[i:end_bracket + 1])
                    result[key] = list_content
                    i = end_bracket + 1
                    continue

                result[key] = val

            i += 1

        return result

    def _find_matching_bracket(self, lines: List[str], start_idx: int, bracket: str) -> int:
        depth = 0
        end_bracket = "]" if bracket == "[" else "}"
        for i in range(start_idx, len(lines)):
            line = lines[i]
            depth += line.count(bracket) - line.count(end_bracket)
            if depth == 0:
                return i
        return start_idx

    def _parse_list_field(self, frontmatter: Dict, field_name: str) -> List[str]:
        value = frontmatter.get(field_name, "")
        if not value:
            return []

        if isinstance(value, list):
            return value

        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                items = []
                for item in value[1:-1].split(","):
                    item = item.strip().strip('"').strip("'").strip()
                    if item:
                        items.append(item)
                return items
            return [value]

        return []

    def _parse_phases(self, content: str) -> List[SkillPhase]:
        phases = []
        phase_pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)

        matches = list(phase_pattern.finditer(content))
        for i, match in enumerate(matches):
            phase_name = match.group(1).strip()
            phase_id = f"P{i+1}"

            if i + 1 < len(matches):
                next_match = matches[i + 1]
                phase_content = content[match.end():next_match.start()]
            else:
                phase_content = content[match.end():]

            description = self._extract_description(phase_content)
            inputs, outputs = self._extract_parameters(phase_content)

            phases.append(
                SkillPhase(
                    phase_id=phase_id,
                    name=phase_name,
                    description=description,
                    inputs=inputs,
                    outputs=outputs,
                )
            )

        return phases

    def _extract_description(self, content: str) -> str:
        lines = content.strip().split("\n")
        description_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("###") and not stripped.startswith("|") and not stripped.startswith("```"):
                description_lines.append(stripped)
            else:
                break
        return " ".join(description_lines)[:200]

    def _extract_parameters(self, content: str) -> tuple:
        inputs = []
        outputs = []

        table_pattern = re.compile(r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|")

        lines = content.split("\n")
        in_input_section = False
        in_output_section = False

        for line in lines:
            if "输入参数" in line or "Inputs" in line or "input" in line.lower():
                in_input_section = True
                in_output_section = False
                continue
            if "输出参数" in line or "Outputs" in line or "output" in line.lower():
                in_output_section = True
                in_input_section = False
                continue

            match = table_pattern.match(line)
            if match:
                cols = [c.strip() for c in match.groups()]
                if len(cols) >= 2 and cols[0] != "参数":
                    param = {"name": cols[0], "type": cols[1] if len(cols) > 1 else "", "description": cols[2] if len(cols) > 2 else ""}
                    if in_input_section:
                        inputs.append(param)
                    elif in_output_section:
                        outputs.append(param)

        return inputs, outputs

    def _detect_format(self, frontmatter: Dict) -> str:
        if frontmatter.get("superpowers_version") or frontmatter.get("format") == "superpowers":
            return "superpowers"
        if frontmatter.get("claude_version") or "anthropic" in str(frontmatter.get("provider", "")).lower():
            return "claude"
        return "native"

    def validate(self, skill_meta: SkillMeta) -> List[str]:
        errors = []
        if not skill_meta.skill_name:
            errors.append("skill_name 不能为空")
        if not skill_meta.version:
            errors.append("version 不能为空")
        if not skill_meta.description and len(skill_meta.phases) == 0:
            errors.append("缺少描述或阶段定义")
        return errors


class SkillImporter:
    def __init__(
        self,
        skill_engine=None,
        node_registry=None,
    ):
        self.parser = SKILLMdParser()
        self.skill_engine = skill_engine
        self.node_registry = node_registry

    def import_one(self, skill_md_path: Path) -> SkillMeta:
        meta = self.parser.parse(skill_md_path)
        errors = self.parser.validate(meta)
        if errors:
            raise ValueError(f"SKILL.md 校验失败: {errors}")

        self._register_to_skill_engine(meta)
        self._register_to_node_registry(meta)
        return meta

    def scan_and_import(self, skills_dir: Path) -> Dict[str, Any]:
        results = {"success": [], "failed": []}

        for skill_md in skills_dir.rglob("SKILL.md"):
            try:
                meta = self.import_one(skill_md)
                results["success"].append({
                    "name": meta.skill_name,
                    "version": meta.version,
                    "path": str(skill_md),
                })
            except Exception as e:
                results["failed"].append({
                    "path": str(skill_md),
                    "error": str(e),
                })

        return results

    def _register_to_skill_engine(self, meta: SkillMeta):
        if not self.skill_engine:
            try:
                from core.skill_engine import SkillEngine

                self.skill_engine = SkillEngine
            except Exception:
                return

        try:
            self.skill_engine.register(
                skill_name=meta.skill_name,
                handler=None,
                skill_path=meta.skill_path,
                version=meta.version,
            )
        except Exception:
            pass

    def _register_to_node_registry(self, meta: SkillMeta):
        if not self.node_registry:
            try:
                from dreamos.registry.node_registry import NodeRegistry
                from dreamos.shared.interfaces import Node

                class SkillNode(Node):
                    def __init__(self, meta):
                        self.node_id = f"SKILL_{meta.skill_name}"
                        self.chain = self._infer_chain(meta.tags)
                        self.name = meta.skill_name
                        self.description = meta.description
                        self.tags = meta.tags
                        self.handler = meta.handler

                    def _infer_chain(self, tags):
                        tags_str = " ".join(tags).upper()
                        if "TRADE" in tags_str:
                            return "A"
                        if "INTELLIGENCE" in tags_str:
                            return "I"
                        if "SUPPORT" in tags_str:
                            return "S"
                        if "CORE" in tags_str:
                            return "C"
                        return "G"

                self.node_registry = NodeRegistry()
            except Exception:
                return

        try:
            node = self._create_skill_node(meta)
            if node:
                self.node_registry.register(node)
        except Exception:
            pass

    def _create_skill_node(self, meta: SkillMeta):
        try:
            from dreamos.shared.interfaces import Node

            class SkillNode(Node):
                def __init__(self, meta):
                    self.node_id = f"SKILL_{meta.skill_name}"
                    self.chain = self._infer_chain(meta.tags)
                    self.name = meta.skill_name
                    self.description = meta.description
                    self.tags = meta.tags
                    self.handler = meta.handler

                def _infer_chain(self, tags):
                    tags_str = " ".join(tags).upper()
                    if "TRADE" in tags_str:
                        return "A"
                    if "INTELLIGENCE" in tags_str:
                        return "I"
                    if "SUPPORT" in tags_str:
                        return "S"
                    if "CORE" in tags_str:
                        return "C"
                    return "G"

            return SkillNode(meta)
        except Exception:
            return None


def main():
    parser = argparse.ArgumentParser(description="SKILL.md 兼容导入器")
    parser.add_argument("action", choices=["scan", "import", "list", "validate"], help="操作")
    parser.add_argument("target", nargs="?", help="目标（import/validate 时指定）")

    args = parser.parse_args()

    skills_dir = _ROOT / "11-易经推理系统" / "skills"
    importer = SkillImporter()

    if args.action == "scan":
        print(f"扫描目录: {skills_dir}")
        results = importer.scan_and_import(skills_dir)
        print(f"\n成功: {len(results['success'])} 个")
        for s in results["success"]:
            print(f"  ✓ {s['name']} v{s['version']}")
        if results["failed"]:
            print(f"\n失败: {len(results['failed'])} 个")
            for f in results["failed"]:
                print(f"  ✗ {f['path']}: {f['error']}")

    elif args.action == "import":
        if not args.target:
            print("请指定要导入的 skill 名称")
            sys.exit(1)
        skill_md = skills_dir / args.target / "SKILL.md"
        if not skill_md.exists():
            print(f"SKILL.md 不存在: {skill_md}")
            sys.exit(1)
        meta = importer.import_one(skill_md)
        print(f"导入成功: {meta.skill_name} v{meta.version}")
        print(f"描述: {meta.description}")
        print(f"标签: {meta.tags}")
        print(f"阶段数: {len(meta.phases)}")

    elif args.action == "list":
        try:
            from core.skill_engine import SkillEngine

            registry = SkillEngine.SKILL_REGISTRY
            print(f"已注册技能: {len(registry)} 个")
            for name, info in registry.items():
                print(f"  {name} v{info.get('version', '1.0.0')}")
        except Exception as e:
            print(f"读取注册失败: {e}")

    elif args.action == "validate":
        if not args.target:
            print("请指定要校验的 SKILL.md 路径")
            sys.exit(1)
        skill_md_path = Path(args.target)
        if not skill_md_path.exists():
            print(f"文件不存在: {skill_md_path}")
            sys.exit(1)
        meta = importer.parser.parse(skill_md_path)
        errors = importer.parser.validate(meta)
        if errors:
            print("校验失败:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)
        else:
            print(f"校验通过: {meta.skill_name} v{meta.version}")
            print(f"描述: {meta.description[:100]}")
            print(f"标签: {meta.tags}")
            print(f"触发词: {meta.trigger_words[:5]}")
            print(f"阶段数: {len(meta.phases)}")


if __name__ == "__main__":
    main()
