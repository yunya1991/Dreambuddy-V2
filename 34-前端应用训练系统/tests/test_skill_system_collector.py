"""SkillSystemCollector 单元测试。

测试:
  1. registry.json 中 active SKILL 被采集
  2. TrainingCase 字段正确映射（name→intent, description→outcome_text, triggers→actions）
  3. layer_tags 包含 DSH（执行模板层）
  4. 增量采集：since 时间戳过滤（基于 content_hash 变化）
  5. FAIL-OPEN：registry 不存在时返回空列表
  6. 非 active SKILL 被跳过
"""
import os
import sys
import json
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class SkillSystemCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时 registry.json 用于测试。"""
        cls._tmpdir = tempfile.mkdtemp(prefix="skill_test_")
        cls._registry_path = os.path.join(cls._tmpdir, "registry.json")

        test_registry = {
            "schema_version": "1.0",
            "total_count": 3,
            "skills": [
                {
                    "name": "dream-tdd-dev",
                    "description": "TDD development workflow: RED→GREEN→REFACTOR",
                    "version": "1.0.0",
                    "path": "/fake/skills/dream-tdd-dev/SKILL.md",
                    "status": "active",
                    "category": "workflow",
                    "triggers": ["tdd", "red-green", "测试驱动"],
                    "depends_on": ["pytest"],
                    "provides": ["test_coverage"],
                    "cognitive_links": [],
                    "content_hash": "abc123",
                    "facets": {
                        "domain": "development",
                        "task_type": "coding",
                        "potency": "unipotent",
                        "resource_cost": "medium",
                        "execution_mode": "auto",
                    },
                    "confidence": 0.5,
                    "apply_count": 10,
                    "last_verified": "2026-10-01",
                    "execution_history": [],
                    "evolution_log": [],
                },
                {
                    "name": "inactive-skill",
                    "description": "This skill is inactive",
                    "version": "0.1.0",
                    "path": "/fake/skills/inactive/SKILL.md",
                    "status": "deprecated",
                    "category": "tooling",
                    "triggers": [],
                    "depends_on": [],
                    "provides": [],
                    "cognitive_links": [],
                    "content_hash": "def456",
                    "facets": {},
                    "confidence": 0.2,
                    "apply_count": 0,
                    "last_verified": None,
                    "execution_history": [],
                    "evolution_log": [],
                },
                {
                    "name": "dream-bugfix",
                    "description": "Bug fix workflow: symptom→root cause→fix→verify",
                    "version": "2.0.0",
                    "path": "/fake/skills/dream-bugfix/SKILL.md",
                    "status": "active",
                    "category": "workflow",
                    "triggers": ["bug", "fix", "root cause"],
                    "depends_on": ["5why"],
                    "provides": ["bugfix_report"],
                    "cognitive_links": [],
                    "content_hash": "ghi789",
                    "facets": {
                        "domain": "development",
                        "task_type": "debugging",
                        "potency": "unipotent",
                        "resource_cost": "low",
                        "execution_mode": "auto",
                    },
                    "confidence": 0.6,
                    "apply_count": 5,
                    "last_verified": "2026-10-05",
                    "execution_history": [],
                    "evolution_log": [],
                },
            ],
        }

        with open(cls._registry_path, "w") as f:
            json.dump(test_registry, f)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_collect_active_skills(self):
        """只采集 status=active 的 SKILL，跳过 deprecated。"""
        from skill_system_collector import SkillSystemCollector

        collector = SkillSystemCollector(registry_path=self._registry_path)
        cases = collector.fetch_cases(limit=100)

        # 2 active SKILLs
        self.assertEqual(len(cases), 2)

        names = [c.intent for c in cases]
        self.assertIn("dream-tdd-dev", names)
        self.assertIn("dream-bugfix", names)
        self.assertNotIn("inactive-skill", names)

    def test_training_case_fields_mapped(self):
        """TrainingCase 字段正确映射。"""
        from skill_system_collector import SkillSystemCollector

        collector = SkillSystemCollector(registry_path=self._registry_path)
        cases = collector.fetch_cases(limit=100)

        tdd_case = [c for c in cases if c.intent == "dream-tdd-dev"][0]

        self.assertEqual(tdd_case.source, "skill")
        self.assertIn("TDD development workflow", tdd_case.outcome_text)
        # triggers → actions
        self.assertIn("tdd", tdd_case.actions)
        # layer_tags contains DSH
        self.assertIn("DSH", tdd_case.layer_tags)
        self.assertEqual(tdd_case.confidence, 0.5)
        self.assertEqual(tdd_case.quality, "B")

    def test_source_name(self):
        from skill_system_collector import SkillSystemCollector
        collector = SkillSystemCollector(registry_path=self._registry_path)
        self.assertEqual(collector.get_source_name(), "skill")

    def test_quality_threshold(self):
        from skill_system_collector import SkillSystemCollector
        collector = SkillSystemCollector(registry_path=self._registry_path)
        self.assertEqual(collector.get_quality_threshold(), "B")

    def test_fail_open_registry_missing(self):
        """registry.json 不存在时返回空列表。"""
        from skill_system_collector import SkillSystemCollector
        collector = SkillSystemCollector(registry_path="/nonexistent/registry.json")
        cases = collector.fetch_cases(limit=10)
        self.assertEqual(cases, [])

    def test_incremental_collect_by_content_hash(self):
        """增量采集：只采集 content_hash 不在已知集合中的 SKILL。"""
        from skill_system_collector import SkillSystemCollector

        collector = SkillSystemCollector(registry_path=self._registry_path)

        # 第一次全量采集
        all_cases = collector.fetch_cases(limit=100)
        self.assertEqual(len(all_cases), 2)

        # 传入已知 hashes（abc123 已采集），只应返回 ghi789
        known_hashes = {"abc123"}
        new_cases = collector.fetch_cases(limit=100, since=json.dumps(list(known_hashes)))
        self.assertEqual(len(new_cases), 1)
        self.assertEqual(new_cases[0].intent, "dream-bugfix")


if __name__ == "__main__":
    unittest.main()
