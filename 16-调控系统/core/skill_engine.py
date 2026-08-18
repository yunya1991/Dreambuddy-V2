"""
SKILL 执行引擎 — 16-调控系统 Phase 2

提供 SKILL 方法论的程序化执行框架：
- 读取 SKILL.md 获取方法论定义
- 解析阶段结构
- 统一的输入/输出契约
- 支持降级回退
- 支持未来接入 LLM bridge

架构原则：
- 每个 SKILL 有一个 adapter 实现
- adapter 输出格式与 SKILL.md 中的 JSON 规范一致
- 外部调用只依赖引擎接口，不依赖具体 adapter 实现
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


MODULE_DIR = Path(__file__).parent.parent
BASE_DIR = MODULE_DIR.parent


@dataclass
class SkillPhase:
    phase_id: str
    name: str
    description: str = ""


@dataclass
class SkillResult:
    skill_name: str
    skill_version: str
    status: str = "completed"
    execution_mode: str = "code_adapter"
    phases_executed: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "skill_name": self.skill_name,
            "skill_version": self.skill_version,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "phases_executed": self.phases_executed,
            "data": self.data,
            "error": self.error,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
        }


class SkillEngine:
    """
    SKILL 执行引擎

    用法：
        engine = SkillEngine()
        result = engine.execute("dream-strategy-research", inputs)
        print(result.data)
    """

    SKILL_REGISTRY: Dict[str, Dict] = {}

    @classmethod
    def register(cls, skill_name: str, handler: Callable, skill_path: str = "", version: str = "1.0.0"):
        """注册 SKILL 处理器"""
        cls.SKILL_REGISTRY[skill_name] = {
            "handler": handler,
            "skill_path": skill_path,
            "version": version,
        }

    def __init__(self, project_root: str = None):
        self.project_root = Path(project_root) if project_root else BASE_DIR

    def load_skill_md(self, skill_name: str) -> Optional[str]:
        """加载 SKILL.md 内容"""
        reg = self.SKILL_REGISTRY.get(skill_name)
        if not reg or not reg["skill_path"]:
            return None

        skill_path = self.project_root / reg["skill_path"]
        if not skill_path.exists():
            return None

        try:
            return skill_path.read_text(encoding="utf-8")
        except Exception:
            return None

    def parse_skill_info(self, skill_md: str) -> Dict:
        """从 SKILL.md 中解析 frontmatter 元信息"""
        info = {"name": "", "version": "", "description": ""}
        if not skill_md.startswith("---"):
            return info

        parts = skill_md.split("---", 2)
        if len(parts) < 3:
            return info

        fm = parts[1]
        for line in fm.split("\n"):
            line = line.strip()
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == "name":
                    info["name"] = val
                elif key == "version":
                    info["version"] = val
                elif key == "description":
                    info["description"] = val

        return info

    def parse_phases(self, skill_md: str) -> List[SkillPhase]:
        """从 SKILL.md 中解析执行阶段"""
        phases = []
        phase_pattern = re.compile(
            r'###?\s*(Phase\s*[\d.]+|阶段\s*[\d.]+)[：:]\s*(.+?)\n',
            re.IGNORECASE,
        )

        matches = list(phase_pattern.finditer(skill_md))
        for i, match in enumerate(matches):
            phase_id = match.group(1).strip()
            phase_name = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(skill_md)
            section = skill_md[start:end]
            lines = [l.strip() for l in section.split("\n") if l.strip() and not l.startswith("#")]
            description = lines[0] if lines else phase_name

            phases.append(SkillPhase(
                phase_id=phase_id,
                name=phase_name,
                description=description,
            ))

        return phases

    def execute(self, skill_name: str, inputs: Dict[str, Any]) -> SkillResult:
        """
        执行指定 SKILL

        Args:
            skill_name: SKILL 名称（如 "dream-strategy-research"）
            inputs: 输入数据字典

        Returns:
            SkillResult 对象
        """
        reg = self.SKILL_REGISTRY.get(skill_name)
        if not reg:
            return SkillResult(
                skill_name=skill_name,
                skill_version="unknown",
                status="error",
                error=f"SKILL not registered: {skill_name}",
                fallback_used=True,
                fallback_reason="not_registered",
            )

        handler = reg["handler"]
        version = reg["version"]

        try:
            result_data = handler(inputs, self)
            return SkillResult(
                skill_name=skill_name,
                skill_version=version,
                status="completed",
                data=result_data,
            )
        except Exception as e:
            return SkillResult(
                skill_name=skill_name,
                skill_version=version,
                status="error",
                error=str(e),
                fallback_used=True,
                fallback_reason=f"handler_error: {type(e).__name__}",
            )


def register_skill(skill_name: str, skill_path: str = "", version: str = "1.0.0"):
    """
    装饰器：注册 SKILL 处理器

    用法：
        @register_skill("my-skill", "path/to/SKILL.md", "1.0.0")
        def my_skill_handler(inputs, engine):
            return {"result": ...}
    """
    def decorator(func):
        SkillEngine.register(skill_name, func, skill_path, version)
        return func
    return decorator
