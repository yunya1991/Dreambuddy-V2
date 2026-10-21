# -*- coding: utf-8 -*-
"""语义蒸馏采集器 — S 层 term_lookup/semantic_knowledge 意图训练数据源。

从 39-金融语义蒸馏系统产出中采集训练样本（SPEC v0.8 分层语义架构）：
  1. 五大术语表（indicator/strategy/theory/finance/algorithm）→ 术语查询样本
  2. 实操语义（practical_semantics.json）→ 实操知识样本
  3. 复杂语义（complex_semantics.json）→ 共现/状态/因果描述样本

样本形态: (message=术语查询问法, intent_type=term_lookup) + 语义知识 outcome。
FAIL-OPEN: 39 产出缺失/解析失败返回空列表，不阻塞训练。
"""
import json
import os
import random
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase

_DISTILL_DIR = os.path.join(_PROJECT_ROOT, "39-金融语义蒸馏系统")

_DOMAIN_DESC = {
    "indicator": "技术指标",
    "strategy": "交易策略",
    "theory": "交易理论",
    "finance": "金融概念",
    "algorithm": "交易算法",
}

_QUERY_TEMPLATES = [
    "什么是{term}",
    "{term}是什么意思",
    "解释一下{term}",
    "{term}的定义",
    "帮我说明{term}",
    "查询{term}的含义",
    "{term}指的是什么",
    "说说{term}",
]


class SemanticDistillCollector(TrainingDataProvider):
    """从 39 蒸馏产出生成 term_lookup 意图训练样本。"""

    def get_source_name(self) -> str:
        return "semantic_distill"

    def get_quality_threshold(self) -> str:
        return "B"

    def _load_json(self, filename: str) -> dict:
        path = os.path.join(_DISTILL_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def fetch_cases(self, limit: int = 100, since: Optional[str] = None) -> List[TrainingCase]:
        cases: List[TrainingCase] = []
        rng = random.Random(42)

        # 1) 五大术语表 → 术语查询样本
        for domain, desc in _DOMAIN_DESC.items():
            table = self._load_json(f"{domain}_terms.json")
            terms = table.get("terms", [])
            rng.shuffle(terms)
            for t in terms:
                if len(cases) >= limit:
                    break
                term = t.get("term", "")
                definition = t.get("definition", "")
                if not term or not definition:
                    continue
                tpl = rng.choice(_QUERY_TEMPLATES)
                cases.append(TrainingCase(
                    intent="term_lookup",
                    actions=[f"term:{term}", f"domain:{domain}"],
                    outcome_text=tpl.format(term=term),
                    learned=[f"{desc} | {term}: {definition[:150]}"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.7,
                    source="semantic_distill",
                    metadata={
                        "term": term,
                        "domain": domain,
                        "definition": definition,
                        "term_quality": t.get("quality", "A"),
                        "engine_hint": "39-金融语义蒸馏系统",
                    },
                ))
            if len(cases) >= limit:
                break

        # 2) 实操语义 → 实操知识样本
        if len(cases) < limit:
            practical = self._load_json("practical_semantics.json")
            for name, info in practical.get("terms", {}).items():
                if len(cases) >= limit:
                    break
                occurrences = info.get("occurrences", 0)
                top_values = info.get("top_values", {})
                if occurrences <= 0:
                    continue
                vals_desc = "/".join(f"{k}×{v}" for k, v in list(top_values.items())[:3])
                cases.append(TrainingCase(
                    intent="semantic_knowledge",
                    actions=[f"practical:{name}"],
                    outcome_text=f"{name}在真实交易中的表现如何",
                    learned=[f"实操语义 | {name}: 真实触发 {occurrences} 次, 取值分布 {vals_desc}"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.7,
                    source="semantic_distill",
                    metadata={
                        "term": name,
                        "occurrences": occurrences,
                        "top_values": top_values,
                        "engine_hint": "39-金融语义蒸馏系统/第二圈实操归纳",
                    },
                ))

        # 3) 复杂语义 → 共现/因果描述样本（仅强证据）
        if len(cases) < limit:
            complex_sem = self._load_json("complex_semantics.json")
            for c in complex_sem.get("cooccurrence", []):
                if len(cases) >= limit:
                    break
                if c.get("evidence") != "strong":
                    continue
                a, b = c.get("pair", ["?", "?"])
                cases.append(TrainingCase(
                    intent="semantic_knowledge",
                    actions=[f"cooccur:{a}|{b}"],
                    outcome_text=f"{a}和{b}的关系",
                    learned=[f"时序共现 | {a}与{b}窗口共现率 {c.get('cooccur_rate', 0)}（n={c.get('n', 0)}）"],
                    layer_tags=["S"],
                    quality="B",
                    confidence=0.6,
                    source="semantic_distill",
                    metadata={
                        "pair": [a, b],
                        "cooccur_rate": c.get("cooccur_rate", 0),
                        "n": c.get("n", 0),
                        "engine_hint": "39-金融语义蒸馏系统/P3组织层",
                    },
                ))

        return cases[:limit]
