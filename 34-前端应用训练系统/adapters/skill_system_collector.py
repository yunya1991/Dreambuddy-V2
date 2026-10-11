"""SKILL 系统采集器。

读取 skills/_registry/registry.json，
实现 TrainingDataProvider 协议，为主动训练采集器提供 SKILL 执行模板数据。

设计:
  - 读取 registry.json（JSON 解析，无 IPC 开销）
  - 质量门控: 只采集 status=active 的 SKILL
  - 增量采集: since 参数为已知 content_hash 的 JSON list，只采集新/变化的 SKILL
  - FAIL-OPEN: registry 不存在或解析失败时返回空列表

字段映射 (SPEC §2.2: execution_template → DSH层训练数据):
  - name → intent
  - description → outcome_text
  - triggers → actions
  - depends_on → metadata
  - provides → metadata
  - facets → metadata
  - confidence → confidence
  - quality = "B" (结构化数据，质量较高)
  - source = "skill"
  - layer_tags = ["DSH"] (执行模板层)
"""
import json
import os
import sys
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

# 默认 registry 路径
_DEFAULT_REGISTRY_PATH = os.path.join(
    _PROJECT_ROOT, "1-ARCHITECTURE", "skills", "_registry", "registry.json"
)


class SkillSystemCollector(TrainingDataProvider):
    """SKILL 系统采集器。

    从 registry.json 读取 active SKILL，转换为 TrainingCase。
    SKILL 的 execution_template 作为 DSH 层训练数据。
    """

    def __init__(self, registry_path: str = "", quality_threshold: str = "B"):
        self._registry_path = registry_path or _DEFAULT_REGISTRY_PATH
        self._quality_threshold = quality_threshold

    def get_source_name(self) -> str:
        return "skill"

    def get_quality_threshold(self) -> str:
        return self._quality_threshold

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 registry.json 批量获取 active SKILL。

        Args:
            limit: 最大返回数量
            since: 增量采集参数，JSON list 格式的已知 content_hash 集合，
                   只返回 hash 不在集合中的 SKILL

        Returns:
            训练案例列表（FAIL-OPEN：registry 不可用时返回空列表）
        """
        if not os.path.exists(self._registry_path):
            return []

        try:
            with open(self._registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)

            # 解析 since 为已知 content_hash 集合
            known_hashes = set()
            if since:
                try:
                    known_hashes = set(json.loads(since))
                except (json.JSONDecodeError, TypeError):
                    pass

            skills = registry.get("skills", [])
            cases = []
            for skill in skills:
                # 质量门控: 只采集 active SKILL
                if skill.get("status") != "active":
                    continue

                # 增量: 跳过已采集的 content_hash
                content_hash = skill.get("content_hash", "")
                if content_hash and content_hash in known_hashes:
                    continue

                cases.append(self._convert_skill(skill))
                if len(cases) >= limit:
                    break

            return cases
        except Exception:
            return []

    @staticmethod
    def _convert_skill(skill: dict) -> TrainingCase:
        """将 SKILL registry 条目转换为 TrainingCase。"""
        name = skill.get("name", "unknown")
        description = skill.get("description", "")
        triggers = skill.get("triggers", [])
        facets = skill.get("facets", {})

        return TrainingCase(
            intent=name,
            actions=triggers if isinstance(triggers, list) else [],
            outcome_text=description,
            learned=[description] if description else [],
            layer_tags=["DSH"],  # execution_template → DSH层
            quality="B",  # 结构化数据，质量较高
            confidence=skill.get("confidence", 0.3),
            source="skill",
            metadata={
                "name": name,
                "version": skill.get("version", ""),
                "path": skill.get("path", ""),
                "category": skill.get("category", ""),
                "depends_on": skill.get("depends_on", []),
                "provides": skill.get("provides", []),
                "cognitive_links": skill.get("cognitive_links", []),
                "content_hash": skill.get("content_hash", ""),
                "facets": facets,
                "apply_count": skill.get("apply_count", 0),
                "last_verified": skill.get("last_verified"),
            },
        )
