"""
ftc_schema — 金融思维链（Financial Thinking Chain）数据结构定义

FTC 三步基因类型:
  - condition: 可观测条件（执行）— 有 data_required + threshold
  - inference: 因果推理步骤（不执行，仅用于知识对齐+可解释）— 有 logic + knowledge_ref
  - action: 交易动作（执行）— 有 gene_ref (AC-*)

关键约束:
  - inference 步骤不参与回测执行，仅用于知识相似度对齐和人类可读的因果解释
  - condition + action 必须形成完整执行链
  - 每条 FTC 有 knowledge_alignment 字段，记录与金融知识锚点的相似度
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Literal
import uuid


StepType = Literal["condition", "inference", "action"]
Track = Literal["exploit", "mixed", "explore", "discard"]
Source = Literal["experience_seed", "exploration", "ripple", "reflection", "mutation"]


@dataclass
class FTCStep:
    """FTC 的单一步骤"""
    step_id: str
    type: StepType
    description: str

    # condition 专用
    gene_ref: Optional[str] = None          # 如 "CD-VOL-SURGE"
    data_required: list[str] = field(default_factory=list)
    threshold: Optional[float] = None

    # inference 专用
    logic: Optional[str] = None             # 因果推理文本
    knowledge_ref: Optional[str] = None     # 关联的金融理论名

    # action 专用
    # action 也用 gene_ref (如 "AC-LONG")

    depends_on: list[str] = field(default_factory=list)  # 依赖的 step_id 列表

    def to_dict(self) -> dict:
        d = asdict(self)
        # 移除 None 值的可选字段，保持简洁
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class KnowledgeAlignment:
    """FTC 与某个金融知识锚点的相似度"""
    theory: str
    similarity: float  # 0.0 - 1.0


@dataclass
class FTC:
    """金融思维链"""
    ftc_id: str
    name: str
    steps: list[FTCStep] = field(default_factory=list)
    knowledge_alignment: list[KnowledgeAlignment] = field(default_factory=list)
    source: Source = "experience_seed"

    # 运行时状态
    ess: Optional[float] = None
    n_samples: int = 0
    track: Track = "exploit"  # 默认利用轨道，由编排器根据相似度重算
    is_active: bool = True

    def to_dict(self) -> dict:
        return {
            "ftc_id": self.ftc_id,
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
            "knowledge_alignment": [asdict(ka) for ka in self.knowledge_alignment],
            "source": self.source,
            "ess": self.ess,
            "n_samples": self.n_samples,
            "track": self.track,
            "is_active": self.is_active,
        }

    @property
    def max_similarity(self) -> float:
        """返回与所有知识锚点的最高相似度"""
        if not self.knowledge_alignment:
            return 0.0
        return max(ka.similarity for ka in self.knowledge_alignment)

    @property
    def condition_steps(self) -> list[FTCStep]:
        return [s for s in self.steps if s.type == "condition"]

    @property
    def inference_steps(self) -> list[FTCStep]:
        return [s for s in self.steps if s.type == "inference"]

    @property
    def action_steps(self) -> list[FTCStep]:
        return [s for s in self.steps if s.type == "action"]

    def has_executable_chain(self) -> bool:
        """检查 condition + action 是否形成完整执行链"""
        return len(self.condition_steps) > 0 and len(self.action_steps) > 0


def gen_ftc_id(prefix: str = "FTC") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def gen_step_id() -> str:
    return f"S{uuid.uuid4().hex[:4].upper()}"
