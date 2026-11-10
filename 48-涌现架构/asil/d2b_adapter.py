"""ASIL D2-B Adapter — 接入 D2-B generator 真实调用。

Phase 2：从 Phase 1 mock BuildPlan 升级为真实 D2-B generate(gap) 调用。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 路径：48-涌现架构
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

D2B_GAPS_PATH = _PKG_ROOT / "registry" / "capability_gaps.jsonl"
D2B_TYPES = {"architecture_gap", "doc_debt", "interface_mismatch"}


class D2BAdapter:
    """D2-B 架构方案生成器适配器。"""

    def __init__(self, gaps_path: Optional[Path] = None):
        self.gaps_path = gaps_path or D2B_GAPS_PATH
        self._generator_available = False
        self._generate = None
        self._load_generator()

    def _load_generator(self) -> None:
        """惰性导入 D2-B generator，失败降级。"""
        try:
            from experiments.d2b_engineering.generator import generate as gen

            self._generate = gen
            self._generator_available = True
        except Exception:
            self._generator_available = False

    def is_available(self) -> bool:
        return self._generator_available

    def load_open_gaps(self, gap_type_filter: Optional[set] = None) -> List[Dict[str, Any]]:
        """读取 capability_gaps.jsonl 中 status=open 的 gap。"""
        gaps: List[Dict[str, Any]] = []
        if not self.gaps_path.exists():
            return gaps
        with open(self.gaps_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    gap = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if gap.get("status") != "open":
                    continue
                if gap_type_filter and gap.get("gap_type") not in gap_type_filter:
                    continue
                gaps.append(gap)
        return gaps

    def generate(self, gap: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """对单个 gap 调用 D2-B generate，返回 BuildPlan dict 或 None（不可用）。"""
        if not self._generator_available or self._generate is None:
            return None
        try:
            plan = self._generate(gap)
            # 转换为 ASIL 统一 schema（generator.BuildPlan → dict + modules 字段）
            d = plan.to_dict()
            # 补充 modules 列表（从 dependencies + module_name 提取）
            d["modules"] = [d["module_name"]] + d.get("dependencies", [])
            d["architecture_graph"] = d.get("architecture_graph_patch", {})
            d["bootstrap"] = False
            return d
        except Exception:
            return None

    def generate_bootstrap_templates(self) -> List[Dict[str, Any]]:
        """SPEC §1.3 bootstrap fallback：E6 空时生成预注册模板 BuildPlan。"""
        templates: List[Dict[str, Any]] = []
        if self._generator_available:
            # 用三种预注册类型构造伪 gap
            for gap_type in D2B_TYPES:
                fake_gap = {
                    "gap_id": f"BOOTSTRAP-{gap_type}",
                    "gap_type": gap_type,
                    "evidence": {"source": "asil_bootstrap_fallback"},
                    "expected_value": "bootstrap 自动生成",
                }
                plan = self.generate(fake_gap)
                if plan:
                    plan["bootstrap"] = True
                    templates.append(plan)
        return templates
