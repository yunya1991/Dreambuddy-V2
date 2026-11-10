"""D3-A 基线预测器（SPEC v0.4 §4.3）。

预测目标：session 的 task_type（intent_proxy）。
基线：
  - B0 majority     : 训练集出现最多的 task_type
  - B1 intent_engine: 结构化规则（file_domains 映射 → task_type）
  - B3 knn          : 基于 session 嵌入的 k 近邻
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

TaskType = str


@dataclass
class SessionEvent:
    session_id: str
    ts: float
    task_type: TaskType
    file_domains: list[str]
    recalled_skills: list[str]
    recalled_memory_count: int
    transition_count: int


def parse_event(raw: dict) -> SessionEvent:
    sig = raw.get("intent_signals", {}) or {}
    return SessionEvent(
        session_id=raw["session_id"],
        ts=raw["ts"],
        task_type=raw.get("intent_proxy") or "general",
        file_domains=list(sig.get("file_domains", []) or []),
        recalled_skills=list(raw.get("recalled_skills", []) or []),
        recalled_memory_count=len(raw.get("recalled_memory_ids", []) or []),
        transition_count=int(sig.get("transition_count", 0) or 0),
    )


# ---- B0: 多数类 ----


@dataclass
class B0Majority:
    majority: TaskType = ""

    def fit(self, events: list[SessionEvent]) -> None:
        counts = Counter(e.task_type for e in events)
        self.majority = counts.most_common(1)[0][0]

    def predict(self, _event: SessionEvent) -> tuple[TaskType, dict[TaskType, float]]:
        return self.majority, {self.majority: 1.0}


# ---- B1: IntentEngine 规则（file_domains → task_type 映射）----

# 顶层目录前缀 → task_type 的硬编码映射（与 intent engine 启发式一致）
DOMAIN_RULES: dict[str, TaskType] = {
    "0-系统文档管理": "documentation",
    "1-ARCHITECTURE": "architecture-design",
    "2-": "architecture-design",
    "3-": "trading-system",
    "4-MEMORY": "memory-system",
    "5-": "python-development",
    "6-": "trading-data",
    "7-": "frontend-development",
    "8-": "trading-strategy",
    "9-基本面分析": "trading-data",
    "10-": "trading-strategy",
    "11-易经推理系统": "strategy-execution",
    "12-三屏趋势系统": "strategy-execution",
    "13-": "strategy-execution",
    "14-V15经典马丁策略": "strategy-execution",
    "15-": "strategy-execution",
    "34-前端应用训练系统": "frontend-development",
    "35-广义认知系统协作模块": "memory-system",
    "36-通信系统层": "memory-system",
    "48-涌现架构": "python-development",
}


@dataclass
class B1IntentEngine:
    """基于 file_domains 的规则映射；无匹配时回退到多数类。"""

    fallback: TaskType = "general"
    _domain_counts: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    def fit(self, events: list[SessionEvent]) -> None:
        for e in events:
            for d in e.file_domains:
                self._domain_counts[d][e.task_type] += 1

    def predict(self, event: SessionEvent) -> tuple[TaskType, dict[TaskType, float]]:
        scores: Counter = Counter()
        for d in event.file_domains:
            if d in self._domain_counts:
                scores.update(self._domain_counts[d])
        if scores:
            total = sum(scores.values())
            probs = {k: v / total for k, v in scores.items()}
            top = max(probs, key=probs.get)
            return top, probs
        return self.fallback, {self.fallback: 1.0}


# ---- B3: kNN（session 嵌入 = file_domains ∪ recalled_skills 的 one-hot 余弦）----


def _embed(event: SessionEvent, vocab: dict[str, int]) -> list[float]:
    vec = [0.0] * len(vocab)
    for d in event.file_domains:
        if d in vocab:
            vec[vocab[d]] += 1.0
    for s in event.recalled_skills:
        key = f"skill:{s}"
        if key in vocab:
            vec[vocab[key]] += 1.0
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass
class B3KNN:
    k: int = 5
    _train_events: list[SessionEvent] = field(default_factory=list)
    _train_embeds: list[list[float]] = field(default_factory=list)
    _vocab: dict[str, int] = field(default_factory=dict)

    def fit(self, events: list[SessionEvent]) -> None:
        vocab: dict[str, int] = {}
        for e in events:
            for d in e.file_domains:
                vocab.setdefault(d, len(vocab))
            for s in e.recalled_skills:
                vocab.setdefault(f"skill:{s}", len(vocab))
        self._vocab = vocab
        self._train_events = list(events)
        self._train_embeds = [_embed(e, vocab) for e in events]

    def predict(self, event: SessionEvent) -> tuple[TaskType, dict[TaskType, float]]:
        e_vec = _embed(event, self._vocab)
        sims = [
            (_cosine(e_vec, tv), te.task_type)
            for tv, te in zip(self._train_embeds, self._train_events, strict=True)
        ]
        sims.sort(key=lambda x: x[0], reverse=True)
        top_k = sims[: self.k]
        votes: Counter = Counter()
        for sim, tt in top_k:
            votes[tt] += max(sim, 0.0)
        total = sum(votes.values())
        if total == 0:
            return "general", {"general": 1.0}
        probs = {k: v / total for k, v in votes.items()}
        top = max(probs, key=probs.get)
        return top, probs
