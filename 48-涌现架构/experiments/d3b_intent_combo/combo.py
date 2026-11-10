"""
D3-B IntentKnowledgeCombo 组装器。

从训练 session 中按 intent_proxy 聚合高频 memory/skill/file_domain，
构建意图→知识组合的映射。组合来源对应 SPEC §4.4：
  - 35 recall → recalled_memory_ids
  - SKILL 索引 → recalled_skills
  - 41 文件索引 → file_domains
  - 2-KNOWLEDGE RAG → 由 file_domains 派生（知识文档路径）
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent.parent  # 48-涌现架构/
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


@dataclass
class IntentKnowledgeCombo:
    intent_proxy: str
    memory_ids: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    file_domains: list[str] = field(default_factory=list)
    support: int = 0  # 训练集中该 intent 的 session 数

    @property
    def size(self) -> int:
        return len(self.memory_ids) + len(self.skills) + len(self.file_domains)

    def to_dict(self) -> dict:
        return {
            "intent_proxy": self.intent_proxy,
            "memory_ids": self.memory_ids,
            "skills": self.skills,
            "file_domains": self.file_domains,
            "support": self.support,
            "size": self.size,
        }


def _topn(counter: Counter, n: int, min_freq: int = 1) -> list[str]:
    return [item for item, freq in counter.most_common(n) if freq >= min_freq]


def build_combos(
    train_sessions: list[dict],
    top_memory: int = 10,
    top_skills: int = 8,
    top_domains: int = 6,
    min_support: int = 3,
) -> dict[str, IntentKnowledgeCombo]:
    """从训练 session 构建 intent_proxy → combo 映射。"""
    mem_c: dict[str, Counter] = defaultdict(Counter)
    skill_c: dict[str, Counter] = defaultdict(Counter)
    dom_c: dict[str, Counter] = defaultdict(Counter)
    support: dict[str, int] = defaultdict(int)

    for sess in train_sessions:
        proxy = sess.get("intent_proxy")
        if not proxy:
            continue
        support[proxy] += 1
        for mid in sess.get("recalled_memory_ids", []) or []:
            mem_c[proxy][mid] += 1
        for sk in sess.get("recalled_skills", []) or []:
            skill_c[proxy][sk] += 1
        signals = sess.get("intent_signals", {}) or {}
        for fd in signals.get("file_domains", []) or []:
            dom_c[proxy][fd] += 1

    combos: dict[str, IntentKnowledgeCombo] = {}
    for proxy, sup in support.items():
        if sup < min_support:
            continue
        combos[proxy] = IntentKnowledgeCombo(
            intent_proxy=proxy,
            memory_ids=_topn(mem_c[proxy], top_memory, min_freq=2),
            skills=_topn(skill_c[proxy], top_skills, min_freq=2),
            file_domains=_topn(dom_c[proxy], top_domains, min_freq=2),
            support=sup,
        )
    return combos


def load_events(path: str | Path) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def load_split(path: str | Path) -> tuple[list[str], list[str]]:
    m = json.load(open(path))
    return m["train_sessions"], m["test_sessions"]


def index_by_session(events: list[dict]) -> dict[str, dict]:
    return {e["session_id"]: e for e in events if e.get("session_id")}


if __name__ == "__main__":
    art = PKG_ROOT / "baselines" / "artifacts" / "d3_intent_events"
    events = load_events(art / "intent_events.jsonl")
    train_ids, test_ids = load_split(art / "split_manifest.json")
    idx = index_by_session(events)
    train = [idx[s] for s in train_ids if s in idx]
    combos = build_combos(train)
    print(f"built {len(combos)} combos from {len(train)} train sessions")
    for proxy, c in sorted(combos.items(), key=lambda x: -x[1].support)[:5]:
        print(f"  {proxy}: support={c.support} size={c.size} skills={c.skills[:3]}")
