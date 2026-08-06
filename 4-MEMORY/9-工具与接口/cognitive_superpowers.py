#!/usr/bin/env python3
"""
Superpowers流程模板系统 — 元认知与应用认知双层架构

核心分层（对齐总记忆/应用记忆架构）:
  Layer 1: 元认知流程（Meta-Cognition）= 总记忆层
    = Superpowers标准规范
    = "应该怎么做"的标准化流程
    = 通用软件工程最佳实践
    = 存储: 全局 process_templates.json
    = 例如: test-driven-development, systematic-debugging（原版 Superpowers Skill name）

  Layer 2: 应用认知流程（Applied Cognition）= 应用记忆层
    = Solution Paths（解决路径）
    = "实际怎么做的"具体行动链
    = 特定领域/子系统的实例化
    = 存储: 各应用记忆单元的 solution_paths
    = 例如: "交易系统TDD实践", "风控模块调试路径"

  映射关系（TemplateMappingRegistry）:
    元认知流程 ──(实例化)──▶ 应用认知流程
    ProcessTemplate ──(execute)──▶ SolutionPath
    "应该怎么做" ──(实践)──▶ "实际怎么做的"

核心设计原则:
  - 元认知流程是"建议"而非"约束"，AI可自由选择
  - 应用认知流程是实例化的结果，贝叶斯验证有效性
  - 元→应用映射: 一个流程模板可产生多个应用实例
  - 应用→元反馈: 应用验证结果反哺流程模板置信度
  - Superpowers属于标准规范，建议注入；实际中思维链/行动链
    可继续沉淀为应用认知流程，形成完整的元-应用闭环

认知三要素:
  Knowledge（知识）+ Memory（记忆）+ Process（流程）= 完整认知
  其中 Process = 元认知流程 + 应用认知流程
"""

import json
import os
import sys
import re
import time
import yaml
import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ============================================================
# 元认知流程（Meta-Cognition）= 总记忆层
# ============================================================

class ProcessTemplate:
    """
    流程模板 — 元认知层或应用认知层的统一数据模型。

    layer = "meta"    → 元认知流程（总记忆层，Superpowers标准规范）
    layer = "applied" → 应用认知流程（应用记忆层，Solution Paths）

    质量等级与记忆系统一致:
      S: conf≥0.95, verify≥10
      A: conf≥0.70, verify≥3
      B: conf≥0.40, verify≥1
      C: conf<0.40, verify=0
    """

    def __init__(
        self,
        template_id: str,
        name: str,
        steps: List[str],
        description: str = "",
        confidence: float = 0.5,
        verify_count: int = 0,
        source: str = "superpowers",
        tags: Optional[List[str]] = None,
        layer: str = "meta",
        parent_template_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        quality_level: Optional[str] = None,
    ):
        self.template_id = template_id
        self.name = name
        self.steps = steps
        self.description = description or name
        self.confidence = confidence
        self.verify_count = verify_count
        self.source = source
        self.tags = tags or []
        self.layer = layer
        self.parent_template_id = parent_template_id
        self.metadata = metadata or {}
        # 附录 A.6：质量等级显式覆盖（如 "quarantined"），为 None 时按置信度+验证数计算
        self._quality_level_override: Optional[str] = quality_level
        # 附录 A.6：path_advantage 累积跟踪 + 连续正/负向计数（自动升降级依据）
        self.path_advantage_history: List[float] = []
        self.evaluation_count: int = 0
        self.last_evaluated_at: int = 0
        self.consecutive_positive: int = 0
        self.consecutive_negative: int = 0

    @property
    def quality_level(self) -> str:
        if self._quality_level_override is not None:
            return self._quality_level_override
        if self.confidence >= 0.95 and self.verify_count >= 10:
            return "S"
        elif self.confidence >= 0.70 and self.verify_count >= 3:
            return "A"
        elif self.confidence >= 0.40 and self.verify_count >= 1:
            return "B"
        else:
            return "C"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "steps": self.steps,
            "description": self.description,
            "confidence": self.confidence,
            "verify_count": self.verify_count,
            "quality_level": self.quality_level,
            "source": self.source,
            "tags": self.tags,
            "layer": self.layer,
            "parent_template_id": self.parent_template_id,
            "metadata": self.metadata,
            "quality_level_override": self._quality_level_override,
            "path_advantage_history": self.path_advantage_history,
            "evaluation_count": self.evaluation_count,
            "last_evaluated_at": self.last_evaluated_at,
            "consecutive_positive": self.consecutive_positive,
            "consecutive_negative": self.consecutive_negative,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProcessTemplate":
        obj = cls(
            template_id=data["template_id"],
            name=data["name"],
            steps=data["steps"],
            description=data.get("description", ""),
            confidence=data.get("confidence", 0.5),
            verify_count=data.get("verify_count", 0),
            source=data.get("source", "superpowers"),
            tags=data.get("tags", []),
            layer=data.get("layer", "meta"),
            parent_template_id=data.get("parent_template_id"),
            metadata=data.get("metadata", {}),
            quality_level=data.get("quality_level_override"),
        )
        obj.path_advantage_history = list(data.get("path_advantage_history", []))
        obj.evaluation_count = int(data.get("evaluation_count", 0))
        obj.last_evaluated_at = int(data.get("last_evaluated_at", 0))
        obj.consecutive_positive = int(data.get("consecutive_positive", 0))
        obj.consecutive_negative = int(data.get("consecutive_negative", 0))
        return obj


# ============================================================
# 元→应用映射（Meta→Applied Mapping）
# ============================================================

class TemplateMapping:
    """元认知流程 → 应用认知流程的映射关系（单条）。"""

    def __init__(
        self,
        parent_id: str,
        applied_id: str,
        success_count: int = 0,
        fail_count: int = 0,
        last_verified: float = 0.0,
    ):
        self.parent_id = parent_id
        self.applied_id = applied_id
        self.success_count = success_count
        self.fail_count = fail_count
        self.last_verified = last_verified or time.time()

    @property
    def total_count(self) -> int:
        return self.success_count + self.fail_count

    @property
    def success_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.success_count / self.total_count

    def record_verification(self, success: bool):
        if success:
            self.success_count += 1
        else:
            self.fail_count += 1
        self.last_verified = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parent_id": self.parent_id,
            "applied_id": self.applied_id,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "last_verified": self.last_verified,
            "total_count": self.total_count,
            "success_rate": self.success_rate,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateMapping":
        return cls(
            parent_id=data["parent_id"],
            applied_id=data["applied_id"],
            success_count=data.get("success_count", 0),
            fail_count=data.get("fail_count", 0),
            last_verified=data.get("last_verified", 0.0),
        )


class TemplateMappingRegistry:
    """
    元→应用映射注册表（持久化）。

    存储位置（与总记忆对齐）:
      4-MEMORY/0-元记忆/template_mappings.json
    """

    def __init__(self, storage_path: Optional[str] = None):
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = (
                _SCRIPT_DIR / ".." / "0-元记忆" / "template_mappings.json"
            )
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        # parent_id → {applied_id: TemplateMapping}
        self._mapping: Dict[str, Dict[str, TemplateMapping]] = {}
        # applied_id → parent_id 反向索引
        self._reverse: Dict[str, str] = {}
        self.load()

    def register(self, parent_id: str, applied_id: str) -> TemplateMapping:
        if parent_id not in self._mapping:
            self._mapping[parent_id] = {}
        if applied_id not in self._mapping[parent_id]:
            self._mapping[parent_id][applied_id] = TemplateMapping(
                parent_id=parent_id, applied_id=applied_id
            )
        self._reverse[applied_id] = parent_id
        return self._mapping[parent_id][applied_id]

    def get_mapping(self, parent_id: str, applied_id: str) -> Optional[TemplateMapping]:
        return self._mapping.get(parent_id, {}).get(applied_id)

    def get_parent(self, applied_id: str) -> Optional[str]:
        return self._reverse.get(applied_id)

    def get_applied_instances(self, parent_id: str) -> List[TemplateMapping]:
        return list(self._mapping.get(parent_id, {}).values())

    def record_verification(self, applied_id: str, success: bool) -> Optional[TemplateMapping]:
        parent_id = self._reverse.get(applied_id)
        if not parent_id:
            return None
        mapping = self._mapping[parent_id][applied_id]
        mapping.record_verification(success)
        return mapping

    def get_parent_stats(self, parent_id: str) -> Dict[str, Any]:
        instances = self.get_applied_instances(parent_id)
        total_success = sum(m.success_count for m in instances)
        total_fail = sum(m.fail_count for m in instances)
        total = total_success + total_fail
        return {
            "parent_id": parent_id,
            "applied_count": len(instances),
            "total_verifications": total,
            "total_success": total_success,
            "total_fail": total_fail,
            "success_rate": (total_success / total) if total > 0 else 0.0,
        }

    def list_all(self) -> List[TemplateMapping]:
        result: List[TemplateMapping] = []
        for group in self._mapping.values():
            result.extend(group.values())
        return result

    def save(self):
        data = {
            "version": 1,
            "updated_at": time.time(),
            "mappings": [m.to_dict() for m in self.list_all()],
        }
        self.storage_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )

    def load(self):
        if not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        self._mapping = {}
        self._reverse = {}
        for entry in data.get("mappings", []):
            mapping = TemplateMapping.from_dict(entry)
            pid = mapping.parent_id
            aid = mapping.applied_id
            if pid not in self._mapping:
                self._mapping[pid] = {}
            self._mapping[pid][aid] = mapping
            self._reverse[aid] = pid


# ============================================================
# 应用记忆单元发现
# ============================================================

# 顶层目录 → 应用记忆单元ID / 名称 的映射
APP_MEMORY_UNIT_MAP: Dict[str, Dict[str, str]] = {
    "1-开发记忆单元": {"unit_id": "MU-DEV", "name": "开发记忆单元"},
    "2-交易记忆单元": {"unit_id": "MU-TRD", "name": "交易记忆单元"},
    "3-架构记忆": {"unit_id": "MU-ARC", "name": "架构记忆单元"},
    "4-信息记忆单元": {"unit_id": "MU-INF", "name": "信息记忆单元"},
    "5-通用经验": {"unit_id": "MU-GEN", "name": "通用经验单元"},
}


def discover_app_memory_units(base_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    发现所有应用记忆单元（带有 solution_paths 目录或已注册的单元）。

    返回: [{"unit_id", "name", "path", "has_solution_paths"}, ...]
    """
    base = base_dir or (_SCRIPT_DIR / "..")
    base = base.resolve()

    units: List[Dict[str, Any]] = []
    for dir_name, meta in APP_MEMORY_UNIT_MAP.items():
        unit_path = base / dir_name
        if not unit_path.is_dir():
            continue
        sp_path = unit_path / "solution_paths"
        units.append(
            {
                "unit_id": meta["unit_id"],
                "name": meta["name"],
                "path": str(unit_path),
                "solution_paths_path": str(sp_path),
                "has_solution_paths": sp_path.is_dir(),
            }
        )
    return units


def resolve_unit_for_task(task_type: str) -> Optional[Dict[str, Any]]:
    """
    根据任务类型推断目标应用记忆单元。

    映射规则（保守）:
      - python-development / memory-system / documentation / knowledge-management
          → MU-DEV
      - trading-system → MU-TRD
      - 其余 → MU-DEV（默认单元）
    """
    mapping: Dict[str, str] = {
        "python-development": "MU-DEV",
        "memory-system": "MU-DEV",
        "documentation": "MU-DEV",
        "knowledge-management": "MU-DEV",
        "configuration": "MU-DEV",
        # P2: 交易类全部路由到 MU-TRD
        "trading-system": "MU-TRD",
        "trading-data": "MU-TRD",
        "strategy-state": "MU-TRD",
        "risk-control": "MU-TRD",
        "strategy-research": "MU-TRD",
        "strategy-backtest": "MU-TRD",
        "strategy-execution": "MU-TRD",
        "strategy-governance": "MU-TRD",
        "general": "MU-DEV",
    }
    unit_id = mapping.get(task_type, "MU-DEV")
    units = discover_app_memory_units()
    for u in units:
        if u["unit_id"] == unit_id:
            return u
    # 默认回退到开发单元
    for u in units:
        if u["unit_id"] == "MU-DEV":
            return u
    return None


# ============================================================
# 流程模板注册表（元 + 应用 双层）
# ============================================================

class ProcessTemplateRegistry:
    """
    流程模板注册表：存储、检索、持久化。

    双层存储架构:
      - 元认知层（meta）: 全局 4-MEMORY/0-元记忆/process_templates.json
      - 应用认知层（applied）: 各应用记忆单元的 solution_paths/*.json

    这样设计的原因:
      - 元认知流程（Superpowers规范）属于"总记忆"，全局共享
      - 应用认知流程（Solution Paths）属于"应用记忆"，就近存放
      - 支持多应用记忆单元独立演进 + 总索引统一检索
    """

    def __init__(
        self,
        meta_data_dir: Optional[str] = None,
        app_memory_dirs: Optional[List[str]] = None,
        auto_discover: bool = True,
    ):
        # 元认知层存储路径
        if meta_data_dir:
            self.meta_dir = Path(meta_data_dir)
        else:
            self.meta_dir = _SCRIPT_DIR / ".." / "0-元记忆"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.meta_storage = self.meta_dir / "process_templates.json"

        # 应用认知层存储路径（可多个应用记忆单元）
        self.app_memory_dirs: List[Path] = []
        if app_memory_dirs:
            for d in app_memory_dirs:
                p = Path(d)
                p.mkdir(parents=True, exist_ok=True)
                self.app_memory_dirs.append(p)
        elif auto_discover:
            for unit in discover_app_memory_units():
                sp = Path(unit["solution_paths_path"])
                if not sp.exists():
                    sp.mkdir(parents=True, exist_ok=True)
                self.app_memory_dirs.append(sp)

        # 双层模板缓存
        self._meta_templates: Dict[str, ProcessTemplate] = {}
        self._applied_templates: Dict[str, ProcessTemplate] = {}

        # 初始化映射注册表（持久化）
        self.mapping_registry = TemplateMappingRegistry()

        # 加载持久化模板（元认知流程层已迁移至 SkillLoader 加载原版 14 个 SKILL.md）
        self._load_meta_templates()
        self._load_applied_templates()

    # ---------- 初始化 ----------
    def _load_meta_templates(self):
        if not self.meta_storage.exists():
            return
        try:
            data = json.loads(self.meta_storage.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for tid, tdata in data.items():
            if tid in self._meta_templates:
                continue
            self._meta_templates[tid] = ProcessTemplate.from_dict(tdata)

    def _load_applied_templates(self):
        for sp_dir in self.app_memory_dirs:
            for f in sorted(sp_dir.glob("*.json")):
                if f.name.startswith("."):
                    continue
                try:
                    data = json.loads(f.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                templates = data if isinstance(data, list) else [data]
                for tdata in templates:
                    try:
                        tmpl = ProcessTemplate.from_dict(tdata)
                        if tmpl.layer == "applied":
                            self._applied_templates[tmpl.template_id] = tmpl
                    except (KeyError, TypeError):
                        continue

    # ---------- 注册 ----------
    def register(
        self,
        template_id: str,
        name: str,
        steps: List[str],
        confidence: float = 0.5,
        verify_count: int = 0,
        layer: str = "meta",
        parent_template_id: Optional[str] = None,
        unit_id: Optional[str] = None,
        **kwargs,
    ) -> ProcessTemplate:
        """
        注册流程模板。

        Args:
            template_id: 模板唯一ID
            name: 模板名称
            steps: 步骤列表
            confidence: 置信度
            verify_count: 验证次数
            layer: meta 或 applied
            parent_template_id: 应用模板关联的元模板ID
            unit_id: 应用模板归属的应用记忆单元ID（仅applied层）
        """
        template = ProcessTemplate(
            template_id=template_id,
            name=name,
            steps=steps,
            confidence=confidence,
            verify_count=verify_count,
            layer=layer,
            parent_template_id=parent_template_id,
            **kwargs,
        )

        if layer == "meta":
            self._meta_templates[template_id] = template
        else:
            template.metadata.setdefault("unit_id", unit_id or "MU-DEV")
            self._applied_templates[template_id] = template
            if parent_template_id:
                self.mapping_registry.register(parent_template_id, template_id)

        return template

    def register_applied_from_session(
        self,
        template_id: str,
        name: str,
        steps: List[str],
        parent_template_id: Optional[str],
        solution_path: Dict[str, Any],
        unit_id: Optional[str] = None,
        parent_skill_ids: Optional[List[str]] = None,
        process_verify_report: Optional[Dict[str, Any]] = None,
        task_type: Optional[str] = None,
        reproducible_steps: Optional[List[str]] = None,
        key_artifacts: Optional[Dict[str, Any]] = None,
        quality_level: Optional[str] = None,
    ) -> ProcessTemplate:
        """
        从认知会话的 Solution Path 沉淀应用认知流程。

        这是"行动链→应用记忆流程"的核心入口。
        设计节 4.5：新增 5 个 metadata 字段（parent_skill_ids / process_verify_report /
        task_type / reproducible_steps / key_artifacts）。
        """
        outcome = solution_path.get("outcome", {})
        approach = solution_path.get("approach", {})

        metadata = {
            "unit_id": unit_id or "MU-DEV",
            "problem": solution_path.get("problem", ""),
            "action_count": approach.get("action_count", 0),
            "files_touched": approach.get("files_touched", []),
            "duration_minutes": approach.get("duration_minutes", 0),
            "success": outcome.get("success", False),
            "commit_hash": outcome.get("commit_hash", ""),
            "created_at": time.time(),
        }
        # 设计节 4.5：5 个新字段（仅当传入时写入）
        if parent_skill_ids is not None:
            metadata["parent_skill_ids"] = parent_skill_ids
        if process_verify_report is not None:
            metadata["process_verify_report"] = process_verify_report
        if task_type is not None:
            metadata["task_type"] = task_type
        if reproducible_steps is not None:
            metadata["reproducible_steps"] = reproducible_steps
        if key_artifacts is not None:
            metadata["key_artifacts"] = key_artifacts

        template = ProcessTemplate(
            template_id=template_id,
            name=name,
            steps=steps,
            confidence=0.3,  # 初始置信度，待贝叶斯验证
            verify_count=0,
            layer="applied",
            parent_template_id=parent_template_id,
            source="cognitive-session",
            tags=["solution_path", "applied-cognition"],
            metadata=metadata,
            quality_level=quality_level,
        )

        self._applied_templates[template_id] = template

        if parent_template_id:
            self.mapping_registry.register(parent_template_id, template_id)
            if outcome.get("success"):
                self.mapping_registry.record_verification(template_id, success=True)

        # 持久化到应用记忆单元
        self._persist_applied_template(template)
        return template

    # ---------- 查询 ----------
    def get(self, template_id: str) -> Optional[ProcessTemplate]:
        return self._meta_templates.get(template_id) or self._applied_templates.get(
            template_id
        )

    def get_meta(self, template_id: str) -> Optional[ProcessTemplate]:
        return self._meta_templates.get(template_id)

    def get_applied(self, template_id: str) -> Optional[ProcessTemplate]:
        return self._applied_templates.get(template_id)

    def get_applied_template(self, applied_id: str) -> Optional[ProcessTemplate]:
        """评测闭环调用入口：作为 get_applied 的别名。"""
        return self.get_applied(applied_id)

    def update_path_advantage(
        self,
        applied_id: str,
        path_advantage: float,
        decision: str,
    ) -> None:
        """
        附录 A.6 + 设计节 7.5/7.7：更新应用流程的 path_advantage 跟踪并自动升降级。

        - 连续 3 次 path_advantage ≤ -0.2 → 标记 quarantined（recall 时不再召回）。
        - 连续 2 次正向且当前为 C → 升至 B；连续 4 次正向且当前为 B → 升至 A。
        """
        applied = self.get_applied_template(applied_id)
        if applied is None:
            return

        applied.path_advantage_history.append(path_advantage)
        applied.evaluation_count += 1
        applied.last_evaluated_at = int(time.time())

        # 连续正/负向计数
        if path_advantage >= 0.2:
            applied.consecutive_positive += 1
            applied.consecutive_negative = 0
        elif path_advantage <= -0.2:
            applied.consecutive_negative += 1
            applied.consecutive_positive = 0
        # 其余区间（-0.2, 0.2）不动连续计数

        # 自动升降级（quarantined 触发会强制 override；升级判定基于当前
        # 有效 level，即 quality_level property 的返回值，以支撑 C→B→A 链式升级）
        if applied.consecutive_negative >= 3:
            applied._quality_level_override = "quarantined"
            return

        current_level = applied.quality_level
        if applied.consecutive_positive >= 2 and current_level == "C":
            applied._quality_level_override = "B"
        elif applied.consecutive_positive >= 4 and current_level == "B":
            applied._quality_level_override = "A"

    # P2: 交易专用 path_advantage — 用 P&L/夏普/回撤/胜率计算客观分
    def update_path_advantage_from_trading(
        self,
        applied_id: str,
        pnl_pct: float,
        sharpe_ratio: float,
        max_drawdown_pct: float,
        win_rate: float,
    ) -> None:
        """
        P2: 用交易客观指标计算 path_advantage 并触发贝叶斯升降级。

        评分公式（归一化到 [-1, 1] 区间）：
          pnl_score    = clip(pnl_pct / 10.0, -1, 1)        # ±10% P&L 即满分
          sharpe_score = clip(sharpe_ratio / 2.0, -1, 1)     # ±2.0 夏普即满分
          dd_score     = clip((15.0 - max_drawdown_pct) / 15.0, -1, 1)  # ≤15%回撤为正，>30%为负
          win_score    = clip((win_rate - 0.5) / 0.3, -1, 1) # 50%胜率为中性，80%+为满分

          path_advantage = pnl_score*0.4 + sharpe_score*0.3 + dd_score*0.2 + win_score*0.1

        升降级规则复用 update_path_advantage（≥0.2 正向，≤-0.2 负向）。
        """
        applied = self.get_applied_template(applied_id)
        if applied is None:
            return

        # 归一化各指标到 [-1, 1]
        def _clip(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
            return max(lo, min(hi, v))

        pnl_score = _clip(pnl_pct / 10.0)
        sharpe_score = _clip(sharpe_ratio / 2.0)
        dd_score = _clip((15.0 - max_drawdown_pct) / 15.0)
        win_score = _clip((win_rate - 0.5) / 0.3)

        path_advantage = (
            pnl_score * 0.4
            + sharpe_score * 0.3
            + dd_score * 0.2
            + win_score * 0.1
        )

        # 存入 outcome_metrics
        applied.metadata["outcome_metrics"] = {
            "pnl_pct": pnl_pct,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": max_drawdown_pct,
            "win_rate": win_rate,
            "computed_path_advantage": round(path_advantage, 4),
            "component_scores": {
                "pnl_score": round(pnl_score, 4),
                "sharpe_score": round(sharpe_score, 4),
                "dd_score": round(dd_score, 4),
                "win_score": round(win_score, 4),
            },
            "timestamp": int(time.time()),
        }

        # 复用主升降级逻辑
        self.update_path_advantage(applied_id, path_advantage, decision="trading_outcome")

    def retrieve_applied(self, context: str, top_k: int = 2) -> List[Dict[str, Any]]:
        """
        设计节 7.7：召回应用流程模板，跳过 quarantined。
        P5: 排序时 A/B/S 优先，C 级仅填充（quality_level 为主键，verify_count 为次键）。
        """
        results: List[Dict[str, Any]] = []
        for t in self._applied_templates.values():
            if t.quality_level == "quarantined":
                continue
            parent_skill_ids = t.metadata.get("parent_skill_ids") or []
            parent_skill = parent_skill_ids[0] if parent_skill_ids else ""
            path_adv = t.path_advantage_history[-1] if t.path_advantage_history else 0.0
            injector = getattr(self, "_build_applied_injection", None)
            if callable(injector):
                try:
                    injection = injector(t)
                except Exception:
                    injection = f"## {t.name}\n{t.description}"
            else:
                injection = f"## {t.name}\n{t.description}"
            results.append({
                "applied_id": t.template_id,
                "title": t.name,
                "quality_level": t.quality_level,
                "confidence": t.confidence,
                "verify_count": t.verify_count,
                "parent_skill": parent_skill,
                "path_advantage": path_adv,
                "evaluation_count": t.evaluation_count,
                "injection": injection,
            })
        # P5: C级惩罚 — quality_level 为主排序键(S>A>B>C)，verify_count 为次排序键
        # 高等级优先召回，C 级仅在高等级不足时填充，避免低质噪声抢占名额
        _ql_order = {"S": 4, "A": 3, "B": 2, "C": 1}
        results.sort(
            key=lambda x: (
                _ql_order.get(x.get("quality_level", "C"), 1),
                x.get("verify_count", 0),
            ),
            reverse=True,
        )
        return results[:top_k]

    def list_meta(self) -> List[ProcessTemplate]:
        return list(self._meta_templates.values())

    def list_applied(self, unit_id: Optional[str] = None) -> List[ProcessTemplate]:
        if not unit_id:
            return list(self._applied_templates.values())
        return [
            t
            for t in self._applied_templates.values()
            if t.metadata.get("unit_id") == unit_id
        ]

    def list_all(self) -> List[ProcessTemplate]:
        return list(self._meta_templates.values()) + list(
            self._applied_templates.values()
        )

    def list_by_layer(self, layer: str) -> List[ProcessTemplate]:
        if layer == "meta":
            return self.list_meta()
        if layer == "applied":
            return self.list_applied()
        return []

    def get_children(self, parent_id: str) -> List[ProcessTemplate]:
        """获取某个元认知流程的所有应用实例。"""
        return [
            t
            for t in self._applied_templates.values()
            if t.parent_template_id == parent_id
        ]

    # ---------- 持久化 ----------
    def save(self):
        """保存所有模板（元 + 应用 + 映射）。"""
        self._save_meta_templates()
        # 应用模板已在 register 时写入，这里仅保存映射
        self.mapping_registry.save()

    def _save_meta_templates(self):
        data = {tid: t.to_dict() for tid, t in self._meta_templates.items()}
        self.meta_storage.write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )

    def _persist_applied_template(self, template: ProcessTemplate):
        """将单个应用模板持久化到对应应用记忆单元的 solution_paths。"""
        unit_id = template.metadata.get("unit_id", "MU-DEV")
        # 找到对应单元目录
        target_dir: Optional[Path] = None
        for sp_dir in self.app_memory_dirs:
            # 通过上两级目录名识别单元
            parts = sp_dir.parts
            joined = "/".join(parts[-2:]) if len(parts) >= 2 else ""
            if unit_id == "MU-DEV" and "1-开发记忆单元" in joined:
                target_dir = sp_dir
                break
            if unit_id == "MU-TRD" and "2-交易记忆单元" in joined:
                target_dir = sp_dir
                break
            if unit_id == "MU-ARC" and "3-架构记忆" in joined:
                target_dir = sp_dir
                break
            if unit_id == "MU-INF" and "4-信息记忆单元" in joined:
                target_dir = sp_dir
                break
            if unit_id == "MU-GEN" and "5-通用经验" in joined:
                target_dir = sp_dir
                break

        if target_dir is None:
            # 默认回退：写入第一个可用的 app memory dir
            if self.app_memory_dirs:
                target_dir = self.app_memory_dirs[0]
            else:
                # 创建默认目录
                target_dir = self.meta_dir.parent / "1-开发记忆单元" / "solution_paths"
                target_dir.mkdir(parents=True, exist_ok=True)

        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{template.template_id}.json"
        file_path.write_text(
            json.dumps(template.to_dict(), indent=2, ensure_ascii=False)
        )

    def load(self):
        """从文件重新加载所有模板（元 + 应用）。"""
        self._meta_templates = {}
        self._applied_templates = {}
        self._load_meta_templates()
        self._load_applied_templates()
        self.mapping_registry.load()


# ============================================================
# 关键词 → 流程模板 映射
# ============================================================


def _build_keyword_index(registry: ProcessTemplateRegistry) -> Dict[str, List[str]]:
    """基于注册表动态构建关键词索引（含应用层模板的 tags）。"""
    index: Dict[str, List[str]] = {}
    for tmpl in registry.list_all():
        # 模板自身的 tags 和 name 作为关键词来源
        kws = list(tmpl.tags)
        kws.append(tmpl.name)
        # 去重
        seen = set()
        deduped = []
        for k in kws:
            kl = k.lower()
            if kl not in seen:
                seen.add(kl)
                deduped.append(k)
        index[tmpl.template_id] = deduped
    return index


# ============================================================
# 检索相关流程
# ============================================================

def retrieve_relevant_processes(
    query: str,
    registry: ProcessTemplateRegistry,
    top_k: int = 3,
    layer: str = "meta",
    loader=None,
) -> List[ProcessTemplate]:
    """
    根据查询检索相关流程模板。

    Args:
        query: 查询文本（任务类型/关键词）
        registry: 流程模板注册表
        top_k: 返回数量
        layer: meta（仅元认知） / applied（仅应用） / all（全部）
        loader: SkillLoader 实例（Task 14 改造：优先用原版 14 Skill，全 0 时退化到旧 registry）

    策略：关键词匹配 + 置信度排序 + 质量等级加权
    """
    # ---- Task 14 改造：优先用 SkillLoader（原版 14 Skill）----
    if loader is not None and layer in ("meta", "all"):
        result = loader.retrieve(query, top_meta=top_k, top_applied=0)
        meta_results = result.get("meta", [])
        # 如果 SkillLoader 有 score > 0 的结果，直接返回（包装为 ProcessTemplate 兼容格式）
        positive = [(sk, sc, rs) for sk, sc, rs in meta_results if sc > 0]
        if positive:
            wrappers = []
            for sk, sc, rs in positive[:top_k]:
                w = ProcessTemplate(
                    template_id=sk.skill_id,
                    name=sk.display_name,
                    steps=[],
                    description=sk.description,
                    confidence=min(sc / 10.0, 0.95),
                    verify_count=0,
                    source="superpowers-v6.2.0",
                    tags=sk.trigger_keywords[:5],
                    layer="meta",
                )
                w.metadata = {"match_score": sc, "match_reason": rs, "hard_gates": sk.hard_gates, "checklists": sk.checklists}
                wrappers.append(w)
            return wrappers
        # 全 0 → 退化到旧 registry 逻辑（fallback）

    # ---- 旧逻辑（保留作为 fallback）----
    query_lower = query.lower()
    keyword_index = _build_keyword_index(registry)

    candidates: List[ProcessTemplate]
    if layer == "meta":
        candidates = registry.list_meta()
    elif layer == "applied":
        candidates = registry.list_applied()
    else:
        candidates = registry.list_all()

    scores: Dict[str, float] = {}
    for template in candidates:
        tid = template.template_id
        keywords = keyword_index.get(tid, [template.name.lower()])
        score = 0.0
        for kw in keywords:
            if kw.lower() in query_lower:
                score += 1.0
        if score > 0:
            # 置信度加权
            score += template.confidence * 0.2
            # 质量等级加权（P5: C级负向惩罚，非零奖励）
            ql_bonus = {"S": 0.3, "A": 0.2, "B": 0.1, "C": -0.3}
            score += ql_bonus.get(template.quality_level, -0.3)
        scores[tid] = score

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    results = [registry.get(tid) for tid in sorted_ids if registry.get(tid)]

    if not results:
        all_templates = list(candidates)
        all_templates.sort(key=lambda t: t.confidence, reverse=True)
        results = all_templates[:top_k]

    return results[:top_k]


# ============================================================
# 格式化流程建议
# ============================================================

def format_process_suggestions(templates: List[ProcessTemplate]) -> str:
    """生成AI可读的流程建议文本（非约束）。"""
    lines = [
        "# 🎯 流程建议（非约束，可自由选择是否遵循）",
        "",
        "以下标准化流程可能有助于提高任务质量和效率：",
        "",
    ]

    for i, t in enumerate(templates, 1):
        ql = t.quality_level
        layer_label = "元认知" if t.layer == "meta" else "应用认知"
        steps_str = " → ".join(t.steps)
        lines.append(f"## {i}. [{ql}][{layer_label}] {t.name}")
        lines.append(f"   ID: {t.template_id}")
        lines.append(
            f"   置信度: {t.confidence:.2f} | 验证次数: {t.verify_count}"
        )
        lines.append(f"   步骤: {steps_str}")
        if t.description:
            lines.append(f"   说明: {t.description}")
        if t.parent_template_id:
            lines.append(f"   源自: {t.parent_template_id}")
        lines.append("")

    lines.extend(
        [
            "---",
            "💡 提示: 流程模板来自软件工程最佳实践。遵循可能提高成功率，但不强制。",
            "   如果您有更好的方法，请自由探索——系统会记录并验证不同方案的有效性。",
        ]
    )

    return "\n".join(lines)


# ============================================================
# 校验是否遵循流程
# ============================================================

def verify_process_followed(
    template: ProcessTemplate,
    action_chain: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    校验行动链是否遵循了流程模板。

    策略：检查行动链中是否出现流程步骤的关键词或同义词。
    """
    action_text = " ".join(
        str(a.get("detail", "")) for a in action_chain
    ).lower()

    matched_steps = 0
    step_matches: List[str] = []

    for step in template.steps:
        step_lower = step.lower()
        if step_lower in action_text:
            matched_steps += 1
            step_matches.append(step)
            continue
        synonyms = _get_step_synonyms(step)
        if any(syn in action_text for syn in synonyms):
            matched_steps += 1
            step_matches.append(step)

    followed = matched_steps >= len(template.steps) / 2

    return {
        "followed": followed,
        "matched_steps": matched_steps,
        "total_steps": len(template.steps),
        "step_matches": step_matches,
    }


def _get_step_synonyms(step: str) -> List[str]:
    synonyms_map: Dict[str, List[str]] = {
        "写测试": ["test", "测试", "添加测试", "写失败测试"],
        "写代码": ["code", "实现", "添加代码", "写最小实现"],
        "重构": ["refactor", "优化", "改进", "整理"],
        "调试": ["debug", "排错", "修复", "定位"],
        "复现": ["reproduce", "重现", "复现问题"],
        "定位": ["locate", "定位", "找根因", "root cause"],
        "修复": ["fix", "修复", "修复bug"],
        "验证": ["verify", "validate", "验证", "确认"],
        "测试通过": ["pass", "通过", "测试通过", "green"],
        "添加防御": ["defense", "防御", "添加防御", "test for"],
    }
    step_lower = step.lower()
    for key, syns in synonyms_map.items():
        if key in step_lower:
            return syns
    return []


# ============================================================
# 贝叶斯更新
# ============================================================

def update_process_confidence(
    template: ProcessTemplate,
    success: bool,
    decay_factor: float = 0.7,
) -> ProcessTemplate:
    """
    流程模板置信度的贝叶斯更新（与记忆系统逻辑一致）。
    """
    if success:
        old = template.confidence
        template.confidence = old + (1 - old) * (1 - decay_factor) * 0.5
    else:
        old = template.confidence
        template.confidence = old - old * (1 - decay_factor) * 0.5

    template.verify_count += 1
    template.confidence = max(0.0, min(1.0, template.confidence))
    return template


# ============================================================
# 元→应用反馈（应用→元 置信度反哺）
# ============================================================

def feedback_to_meta_template(
    registry: ProcessTemplateRegistry,
    applied_template_id: str,
    success: bool,
) -> Optional[ProcessTemplate]:
    """
    应用认知流程验证结果反哺元认知流程。

    路径:
      applied_template → parent_template_id → meta template
      1. 更新映射表的 success/fail 计数
      2. 按比例（映射数越多，单个实例权重越低）反哺元模板置信度
    """
    mapping = registry.mapping_registry.record_verification(
        applied_template_id, success
    )
    if not mapping:
        return None

    parent_id = mapping.parent_id
    meta_template = registry.get_meta(parent_id)
    if meta_template is None:
        return None

    # 子实例总数越多，单次反馈权重越低（避免一个实例主导）
    siblings = registry.get_children(parent_id)
    total = len(siblings)
    # 权重: 1/√total （平滑衰减）
    weight = 1.0 / (total ** 0.5) if total > 0 else 1.0

    # 加权贝叶斯更新
    if success:
        old = meta_template.confidence
        meta_template.confidence = old + (1 - old) * weight * 0.3
    else:
        old = meta_template.confidence
        meta_template.confidence = old - old * weight * 0.3

    meta_template.verify_count += 1
    meta_template.confidence = max(0.0, min(1.0, meta_template.confidence))
    return meta_template


# ============================================================
# 主入口
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Superpowers流程模板系统")
    parser.add_argument("--list", action="store_true", help="列出所有流程模板")
    parser.add_argument("--list-meta", action="store_true", help="列出元认知流程")
    parser.add_argument("--list-applied", action="store_true", help="列出应用认知流程")
    parser.add_argument("--search", type=str, help="搜索相关流程")
    parser.add_argument("--suggest", type=str, help="生成流程建议文本")
    parser.add_argument("--mapping", action="store_true", help="显示元→应用映射")
    parser.add_argument("--save", action="store_true", help="保存所有模板和映射")
    args = parser.parse_args()

    registry = ProcessTemplateRegistry()

    if args.list:
        print("📋 已注册流程模板（元+应用）:")
        for t in registry.list_all():
            layer = "元" if t.layer == "meta" else "用"
            print(f"  [{t.quality_level}][{layer}] {t.template_id}: {t.name} (conf={t.confidence:.2f})")
        print(f"  合计: 元 {len(registry.list_meta())} / 应用 {len(registry.list_applied())}")

    elif args.list_meta:
        print("🎯 元认知流程（总记忆层）:")
        for t in registry.list_meta():
            print(f"  [{t.quality_level}] {t.template_id}: {t.name} (conf={t.confidence:.2f})")

    elif args.list_applied:
        print("🧩 应用认知流程（应用记忆层）:")
        for t in registry.list_applied():
            parent = t.parent_template_id or "-"
            unit = t.metadata.get("unit_id", "?")
            print(
                f"  [{t.quality_level}] {t.template_id}: {t.name} "
                f"(unit={unit}, parent={parent}, conf={t.confidence:.2f})"
            )

    elif args.search:
        results = retrieve_relevant_processes(args.search, registry)
        print(f"🔍 查询'{args.search}'相关流程:")
        for t in results:
            layer = "元" if t.layer == "meta" else "用"
            print(f"  [{t.quality_level}][{layer}] {t.template_id}: {t.name}")
            print(f"    步骤: {' → '.join(t.steps)}")

    elif args.suggest:
        results = retrieve_relevant_processes(args.suggest, registry)
        text = format_process_suggestions(results)
        print(text)

    elif args.mapping:
        print("🔗 元→应用映射:")
        for m in registry.mapping_registry.list_all():
            print(
                f"  {m.parent_id} → {m.applied_id} "
                f"(success={m.success_count}, fail={m.fail_count}, rate={m.success_rate:.2f})"
            )

    elif args.save:
        registry.save()
        print("✅ 已保存元模板 + 应用模板 + 映射")


if __name__ == "__main__":
    main()


# ============================================================
# Part A: SuperpowersSkill 数据类（设计节 2.2）
# ============================================================

@dataclass
class SuperpowersSkill:
    """SKILL.md 解析结果（设计节 2.2 SuperpowersSkill 数据模型）"""
    skill_id: str
    display_name: str
    description: str
    version: str
    raw_skill_md: str
    hard_gates: List[str] = field(default_factory=list)
    checklists: List[str] = field(default_factory=list)
    trigger_keywords: List[str] = field(default_factory=list)
    supplement: Optional[str] = None
    md5_of_base: str = ""
    localized: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "SuperpowersSkill":
        return SuperpowersSkill(**d)


# ============================================================
# Part B: SkillLoader 类（设计节 2.2-2.3）
# ============================================================

class SkillLoader:
    """
    SKILL.md 加载器。
    SKILLS_ROOT = /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/0-元记忆/superpowers/skills
    INDEX_PATH = SKILLS_ROOT 父目录下 /skills-index.json
    """
    SKILLS_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/0-元记忆/superpowers/skills")
    INDEX_PATH = SKILLS_ROOT.parent / "skills-index.json"

    # P1: 交易认知 Skill 双源加载
    TRADING_SKILLS_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/0-元记忆/trading-cognition/skills")
    TRADING_INDEX_PATH = TRADING_SKILLS_ROOT.parent / "trading-skills-index.json"

    # P1: 交易类 task_type 集合（用于 retrieve 路由）
    _TRADING_TASK_TYPES = frozenset([
        "trading-system", "trading-data", "strategy-state", "risk-control",
        "strategy-research", "strategy-backtest", "strategy-execution", "strategy-governance",
    ])

    def __init__(self):
        self.skills: Dict[str, SuperpowersSkill] = {}
        self.trading_skills: Dict[str, SuperpowersSkill] = {}
        self.load_all()
        self._load_trading_skills()

    # --- 格式红线（经验 95953）----
    def _validate_frontmatter_format(self, content: str, path: str) -> None:
        """FAIL FAST。校验 frontmatter 分隔符必须是 ---，不得用 *** / ===== / ____"""
        lines = content.splitlines()
        if not lines:
            raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: 0 Error: 文件为空 Suggested fix: 添加合法的 YAML frontmatter（--- 分隔符包裹）")

        line0 = lines[0].strip()
        if line0 != "---":
            line_no = 1
            if lines[0].startswith("***"):
                raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: {line_no} Error: frontmatter 起始分隔符使用了 '***' 而非 '---' Suggested fix: 将第 1 行和闭合分隔符都改为 '---'")
            elif lines[0].startswith("==="):
                raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: {line_no} Error: frontmatter 起始分隔符使用了 '===' 而非 '---' Suggested fix: 将第 1 行和闭合分隔符都改为 '---'")
            elif lines[0].startswith("___"):
                raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: {line_no} Error: frontmatter 起始分隔符使用了 '___' 而非 '---' Suggested fix: 将第 1 行和闭合分隔符都改为 '---'")
            else:
                raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: {line_no} Error: frontmatter 起始分隔符必须是 '---'（当前第 1 行为 {line0!r}）Suggested fix: 第 1 行必须严格为 '---'")

        close_idx = None
        for i in range(1, min(len(lines), 100)):
            if lines[i].strip() == "---":
                close_idx = i
                break

        if close_idx is None:
            raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: 1 Error: 未找到 frontmatter 闭合分隔符 '---' Suggested fix: 在 frontmatter 结束后添加独立的一行 '---'")

        for j in range(0, min(len(lines), 10)):
            raw_line = lines[j]
            if j == 0 or j == close_idx:
                continue
            stripped = raw_line.strip()
            if stripped.startswith("***") and len(stripped) >= 3 and all(c == '*' for c in stripped):
                raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: {j+1} Error: 在前 10 行发现疑似分隔符 '***' Suggested fix: frontmatter 只允许用 '---'，不要用 ***")
            if stripped.startswith("===") and len(stripped) >= 3 and all(c == '=' for c in stripped):
                raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: {j+1} Error: 在前 10 行发现疑似分隔符 '===' Suggested fix: frontmatter 只允许用 '---'，不要用 ===")
            if stripped.startswith("___") and len(stripped) >= 3 and all(c == '_' for c in stripped):
                raise ValueError(f"[SKILL_LOADER_ERROR] File: {path} Line: {j+1} Error: 在前 10 行发现疑似分隔符 '___' Suggested fix: frontmatter 只允许用 '---'，不要用 ___")

    def _parse_skill_md(self, content: str) -> Tuple[dict, List[str], List[str]]:
        """解析 SKILL.md → (frontmatter_dict, hard_gates, checklists)"""
        lines = content.splitlines()
        close_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                close_idx = i
                break

        fm_lines = lines[1:close_idx]
        fm_yaml = "\n".join(fm_lines)
        fm = yaml.safe_load(fm_yaml) or {}

        hg_pattern = re.compile(r"<HARD-GATE>([\s\S]*?)</HARD-GATE>", re.MULTILINE)
        hard_gates = [m.group(1).strip() for m in hg_pattern.finditer(content)]

        iron_law_pattern = re.compile(
            r"^##\s+The Iron Law.*?$([\s\S]*?)(?=^##|\Z)",
            re.MULTILINE,
        )
        for m in iron_law_pattern.finditer(content):
            section = m.group(1)
            code_block_match = re.search(r"```.*?\n([\s\S]*?)\n```", section)
            if code_block_match:
                gate_text = code_block_match.group(1).strip()
                if gate_text:
                    hard_gates.append(gate_text)
            else:
                stripped = section.strip()
                if stripped:
                    hard_gates.append(stripped[:500])

        cl_pattern = re.compile(r"^[-*]\s+\[.?\]\s+(.+)$", re.MULTILINE)
        checklists = [m.group(1).strip() for m in cl_pattern.finditer(content)]

        return fm, hard_gates, checklists

    def _load_supplement(self, skill_dir: Path) -> Optional[str]:
        """读同级 supplement 文件；不存在返回 None。
        P1: 优先 dreambuddy-supplement.md（开发 Skill），回退 cognitive-supplement.md（交易 Skill）
        """
        for name in ("dreambuddy-supplement.md", "cognitive-supplement.md"):
            sup_path = skill_dir / name
            if sup_path.exists():
                try:
                    return sup_path.read_text(encoding="utf-8")
                except OSError:
                    pass
        return None

    _EN_STOPWORDS_2 = {
        "on","in","to","it","an","of","or","at","by","do","is","be","as","so","we","if","go","no","up","my","he","me","hi","ok","ex","vs","al","eg","id","pm","am"
    }

    def _extract_trigger_keywords(self, fm: dict, hg: List[str], cl: List[str], sup: Optional[str]) -> List[str]:
        """汇总 name + description + hg 词元 + cl 词元 + supplement 词元，去重后返回。

        防 C1 子串匹配噪音：
        1. 纯英文 2-letter token（[a-z]{2}）若在停用词表中 → 剔除
        2. 纯英文 token 长度必须 ≥ 3（除非含数字/连字符，如 "TDD", "CI/CD", "P0" 保留）
        """
        parts: List[str] = []
        parts.append(str(fm.get("name", "")))
        parts.append(str(fm.get("description", "")))
        parts.extend(hg)
        parts.extend(cl)
        # 仅 supplement 的「本土触发条件」章节（## 4. ~ ## 5. 之间）参与 KW 提取。
        # 其他章节的 OKX/Python/交易系统等上下文通用词不做 KW，避免跨语义场景误命中。
        # 本土触发词段的命中在 retrieve() 中另有 +2.0 高权重机制专门处理。
        if sup:
            lines = sup.splitlines()
            inside_trigger = False
            trigger_section_lines: List[str] = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("## 4.") and "触发条件" in stripped:
                    inside_trigger = True
                    continue
                if stripped.startswith("## 5.") and inside_trigger:
                    break
                if inside_trigger:
                    trigger_section_lines.append(line)
            if trigger_section_lines:
                parts.append("\n".join(trigger_section_lines))
        combined = " ".join(parts)
        tokens = re.split(r"[^a-zA-Z0-9\u4e00-\u9fa5._\-/]+", combined)
        seen = set()
        result = []
        for tok in tokens:
            if not tok:
                continue
            if len(tok) < 2:
                continue
            tl = tok.lower()
            only_ascii = re.fullmatch(r"[a-z]+", tl) is not None
            # C1-1: 纯英文字母 len=2 且在停用词表 → 剔除
            if only_ascii and len(tl) == 2 and tl in self._EN_STOPWORDS_2:
                continue
            # C1-2: 纯英文字母 len<3 且不在停用词表但过于常见（如 'xx','zz'）仍剔除
            # 注：TDD/CI 等 len=3 的专业缩写不会命中此条
            if tl not in seen:
                seen.add(tl)
                result.append(tok)
        return result

    @staticmethod
    def _kw_matches(kw: str, query_lower: str) -> bool:
        """关键词匹配。C1 修复：纯 ASCII kw 用词边界 \b；含中文/数字/标点用子串匹配。"""
        if not kw:
            return False
        kw_l = kw.lower()
        only_ascii = re.fullmatch(r"[a-z._\-/]+", kw_l) is not None
        if only_ascii:
            # 词边界匹配，避免 Python 匹配到 "on" 子串
            pattern = r"\b" + re.escape(kw_l) + r"\b"
            return re.search(pattern, query_lower) is not None
        # 中文/数字/混合：子串匹配合理
        return kw_l in query_lower

    # --- 加载 ----
    def load_all(self) -> None:
        """遍历 SKILLS_ROOT/*/SKILL.md 加载。异常隔离：单文件失败不影响其余"""
        cache_ok = False
        if self.INDEX_PATH.exists():
            try:
                cache_data = json.loads(self.INDEX_PATH.read_text(encoding="utf-8"))
                if isinstance(cache_data, dict) and len(cache_data) == 14:
                    all_valid = True
                    temp_skills: Dict[str, SuperpowersSkill] = {}
                    for sid, sd in cache_data.items():
                        try:
                            sk = SuperpowersSkill.from_dict(sd)
                            skill_dir = self.SKILLS_ROOT / sid
                            skill_md = skill_dir / "SKILL.md"
                            if skill_md.exists():
                                actual_md5 = hashlib.md5(skill_md.read_text(encoding="utf-8").encode()).hexdigest()
                                if actual_md5 != sk.md5_of_base:
                                    all_valid = False
                                    break
                            temp_skills[sid] = sk
                        except (KeyError, TypeError, ValueError):
                            all_valid = False
                            break
                    if all_valid:
                        self.skills = temp_skills
                        cache_ok = True
            except (json.JSONDecodeError, OSError, ValueError):
                cache_ok = False

        if cache_ok:
            return

        if not self.SKILLS_ROOT.exists():
            print(f"[SkillLoader] WARNING: SKILLS_ROOT 不存在: {self.SKILLS_ROOT}")
            return

        for skill_dir in sorted(self.SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md_path = skill_dir / "SKILL.md"
            if not skill_md_path.exists():
                continue
            skill_id = skill_dir.name
            try:
                content = skill_md_path.read_text(encoding="utf-8")

                self._validate_frontmatter_format(content, str(skill_md_path))

                fm, hard_gates, checklists = self._parse_skill_md(content)

                supplement = self._load_supplement(skill_dir)

                md5_of_base = hashlib.md5(content.encode()).hexdigest()

                trigger_keywords = self._extract_trigger_keywords(fm, hard_gates, checklists, supplement)

                localized = supplement is not None

                sup_version = "v0.0"
                if supplement:
                    m = re.match(r"v(\d+\.\d+(?:\.\d+)?)", supplement.strip())
                    if m:
                        sup_version = f"v{m.group(1)}"

                version = f"upstream v6.2.0 + dreambuddy supplement {sup_version}"

                display_name = str(fm.get("name") or skill_id)
                description = str(fm.get("description") or "")

                sk = SuperpowersSkill(
                    skill_id=skill_id,
                    display_name=display_name,
                    description=description,
                    version=version,
                    raw_skill_md=content,
                    hard_gates=hard_gates,
                    checklists=checklists,
                    trigger_keywords=trigger_keywords,
                    supplement=supplement,
                    md5_of_base=md5_of_base,
                    localized=localized,
                )
                self.skills[skill_id] = sk
            except Exception as e:
                print(f"[SkillLoader] ERROR 加载 {skill_id} 失败: {e}")

        try:
            self._rebuild_index_cache()
        except Exception as e:
            print(f"[SkillLoader] WARNING: 写入 skills-index.json 失败: {e}")

    # P1: 交易 Skill 加载（复用 _parse_skill_md / _load_supplement / _extract_trigger_keywords）
    def _load_trading_skills(self) -> None:
        """从 TRADING_SKILLS_ROOT 加载交易认知 Skill。异常隔离，失败不影响开发 Skill。"""
        if not self.TRADING_SKILLS_ROOT.exists():
            return

        for skill_dir in sorted(self.TRADING_SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md_path = skill_dir / "SKILL.md"
            if not skill_md_path.exists():
                continue
            skill_id = skill_dir.name
            try:
                content = skill_md_path.read_text(encoding="utf-8")
                self._validate_frontmatter_format(content, str(skill_md_path))
                fm, hard_gates, checklists = self._parse_skill_md(content)
                supplement = self._load_supplement(skill_dir)
                trigger_keywords = self._extract_trigger_keywords(fm, hard_gates, checklists, supplement)

                display_name = str(fm.get("name") or skill_id)
                description = str(fm.get("description") or "")
                md5_of_base = hashlib.md5(content.encode()).hexdigest()

                sk = SuperpowersSkill(
                    skill_id=skill_id,
                    display_name=display_name,
                    description=description,
                    version=f"trading-cognition v0.1",
                    raw_skill_md=content,
                    hard_gates=hard_gates,
                    checklists=checklists,
                    trigger_keywords=trigger_keywords,
                    supplement=supplement,
                    md5_of_base=md5_of_base,
                    localized=supplement is not None,
                )
                self.trading_skills[skill_id] = sk
            except Exception as e:
                print(f"[SkillLoader] WARNING: 交易 Skill 加载 {skill_id} 失败: {e}")

    def _rebuild_index_cache(self) -> None:
        """写 skills-index.json：{skill_id: skill.to_dict() for skill_id in self.skills}"""
        data = {sid: sk.to_dict() for sid, sk in self.skills.items()}
        self.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.INDEX_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # --- 检索（设计节 2.3）----
    def retrieve(self, query: str, top_meta: int = 2, top_applied: int = 2, applied_loader=None, task_type: str = None) -> dict:
        """
        按查询文本的关键词匹配度返回 meta（SuperpowersSkill）与 applied（历史应用流程）。
        P1: 新增 task_type 参数，trading 类 task_type 召回交易 Skill，其他召回开发 Skill。
        返回结构：{"meta": List[Tuple[SuperpowersSkill, float, str]], "applied": List[Dict]}
        评分：对每个 skill，trigger_keywords 命中数 + hg 命中数*0.3 + cl 命中数*0.2
        applied_loader 为 None 时 applied 维持空列表（向后兼容）。
        """
        query_lower = query.lower()
        query_tokens = [t for t in re.split(r"[^a-z0-9\u4e00-\u9fa5]+", query_lower) if t]

        # P1: 按 task_type 选择 Skill 源
        is_trading = task_type is not None and task_type in self._TRADING_TASK_TYPES
        source_skills = self.trading_skills if is_trading else self.skills

        scored: List[Tuple[SuperpowersSkill, float, List[str]]] = []

        for skill_id, sk in source_skills.items():
            score = 0.0
            reasons: List[str] = []

            # C1 修复：纯 ASCII 触发词用 \b 词边界匹配，避免子串噪音
            for kw in sk.trigger_keywords:
                if self._kw_matches(kw, query_lower):
                    score += 1.0
                    reasons.append(f"kw:{kw}")

            # 本土触发词优先匹配（高权重）—— 用于修复 C2 跨语言匹配失效
            if sk.supplement:
                for line in (sk.supplement or "").splitlines():
                    line = line.strip()
                    # 本土触发条件：形如 "- [x] 中文触发词一 / 别名1 / 别名2" 这样的 bullet 行
                    if line.startswith("-") and ("触发" in line or len(line) < 80):
                        # 提取 "/" 分隔的别名
                        segments = [s.strip() for s in re.split(r"[-/|、,，]", line.lstrip("- []x")) if len(s.strip()) >= 2]
                        for alias in segments:
                            if alias and alias in query:
                                score += 2.0  # 本土触发词 2 倍权重
                                reasons.append(f"local-trigger:{alias}")

            hg_hit = 0
            for g in sk.hard_gates:
                g_lower = g.lower()
                for tok in query_tokens:
                    # C1 修复：HG 是长句，查询 token 若为纯 ASCII 2-letter 噪音直接跳过
                    if len(tok) == 2 and tok in self._EN_STOPWORDS_2:
                        continue
                    if re.search(r"\b" + re.escape(tok) + r"\b", g_lower) if re.fullmatch(r"[a-z._\-/]+", tok) else tok in g_lower:
                        hg_hit += 1
                        break
            score += hg_hit * 0.3
            if hg_hit > 0:
                reasons.append(f"hg:{hg_hit}")

            cl_hit = 0
            for c in sk.checklists:
                c_lower = c.lower()
                for tok in query_tokens:
                    if len(tok) == 2 and tok in self._EN_STOPWORDS_2:
                        continue
                    if re.search(r"\b" + re.escape(tok) + r"\b", c_lower) if re.fullmatch(r"[a-z._\-/]+", tok) else tok in c_lower:
                        cl_hit += 1
                        break
            score += cl_hit * 0.2
            if cl_hit > 0:
                reasons.append(f"cl:{cl_hit}")

            if score > 0 or len(scored) < top_meta:
                scored.append((sk, score, reasons))

        scored.sort(key=lambda x: x[1], reverse=True)

        meta_results: List[Tuple[SuperpowersSkill, float, str]] = []
        for (sk, sc, rsns) in scored[:top_meta]:
            reason_str = " ; ".join(rsns[:4])
            meta_results.append((sk, sc, reason_str))

        # applied 部分（设计节 7.7）：applied_loader 提供，注入时附带历史评测行
        applied_results: List[Dict[str, Any]] = []
        if applied_loader is not None:
            try:
                raw_applied = applied_loader.retrieve_applied(query, top_k=top_applied)
            except Exception:
                raw_applied = []
            for item in raw_applied:
                try:
                    enhanced = dict(item)
                    enhanced["injection"] = self._build_applied_injection_with_eval(enhanced)
                except Exception:
                    enhanced = item
                applied_results.append(enhanced)

        return {"meta": meta_results, "applied": applied_results}

    def _build_applied_injection_with_eval(self, applied: Dict[str, Any]) -> str:
        """设计节 7.7：在 applied injection 末尾追加历史评测行。"""
        base = applied.get("injection", "")
        eval_count = applied.get("evaluation_count", 0)
        path_adv = applied.get("path_advantage", 0.0)
        if eval_count > 0:
            eval_line = f"\n> 📊 历史评测: path_advantage {path_adv:+.2f} · 验证 {eval_count} 次"
            if not base.endswith("\n"):
                base += "\n"
            base += eval_line
        return base


# ============================================================
# Task 14: 退化兼容映射表（设计节 4.6）
# ============================================================

LEGACY_TO_NEW: Dict[str, str] = {
    "TDD-001":       "test-driven-development",
    "DEBUG-001":     "systematic-debugging",
    "REFACTOR-001":  "test-driven-development",
    "REVIEW-001":    "requesting-code-review",
    "DESIGN-001":    "brainstorming",
    "TDD-DEBUG-001": "subagent-driven-development",
}
