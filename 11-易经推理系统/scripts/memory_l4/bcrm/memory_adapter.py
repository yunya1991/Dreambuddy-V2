"""
BCRM 记忆适配器。

从 L4 记忆系统中检索相似案例，为 BCRM 推理提供历史参考。
"""

import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from random import Random


@dataclass
class BCRMMemoryCase:
    """BCRM 记忆案例。"""
    case_id: str = ""
    bagua: str = ""
    hexagram: str = ""
    direction: str = ""
    accumulation: float = 0.5
    is_qualitative_change: bool = False
    price_change: float = 0.0
    dominant_side_switched: bool = False
    gua_flipped: bool = False
    similarity: float = 0.0
    regime: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "bagua": self.bagua,
            "hexagram": self.hexagram,
            "direction": self.direction,
            "accumulation": self.accumulation,
            "is_qualitative_change": self.is_qualitative_change,
            "price_change": self.price_change,
            "dominant_side_switched": self.dominant_side_switched,
            "gua_flipped": self.gua_flipped,
            "similarity": self.similarity,
            "regime": self.regime,
        }


class MockMemoryAdapter:
    """
    Mock 记忆适配器。

    用于测试和演示，生成合成记忆案例。
    """

    def __init__(self, num_cases: int = 20, seed: int = 42):
        self.num_cases = num_cases
        self.seed = seed
        self._cases: List[BCRMMemoryCase] = []
        self._generate_mock_cases()

    def _generate_mock_cases(self):
        """生成 mock 案例。"""
        rng = Random(self.seed)
        guas = ["qian", "kun", "zhen", "xun", "kan", "li", "gen", "dui"]
        directions = ["UP", "DOWN", "UP", "UP", "DOWN"]
        regimes = ["bull", "bear", "ranging"]

        for i in range(self.num_cases):
            self._cases.append(BCRMMemoryCase(
                case_id=f"mock_case_{i:03d}",
                bagua=rng.choice(guas),
                hexagram="",
                direction=rng.choice(directions),
                accumulation=rng.uniform(0.3, 0.9),
                is_qualitative_change=rng.random() > 0.7,
                price_change=rng.uniform(-0.05, 0.05),
                dominant_side_switched=rng.random() > 0.6,
                gua_flipped=rng.random() > 0.8,
                similarity=0.0,
                regime=rng.choice(regimes),
            ))

    def retrieve_similar(self,
                         snapshot: Dict[str, Any],
                         top_k: int = 5) -> List[BCRMMemoryCase]:
        """检索相似案例。"""
        rng = Random(hash(json.dumps(snapshot, sort_keys=True, default=str)) % (2**32))

        # 随机选择一些案例作为"相似"
        cases = list(self._cases)
        rng.shuffle(cases)
        selected = cases[:min(top_k, len(cases))]

        # 分配相似度
        for i, c in enumerate(selected):
            c.similarity = 1.0 - (i * 0.1)

        return sorted(selected, key=lambda x: -x.similarity)

    def retrieve_by_gua(self,
                        gua: str,
                        top_k: int = 5) -> List[BCRMMemoryCase]:
        """按卦象检索。"""
        matching = [c for c in self._cases if c.bagua == gua]
        return matching[:top_k]

    def retrieve_by_hexagram(self,
                             hexagram: str,
                             top_k: int = 5) -> List[BCRMMemoryCase]:
        """按六十四卦检索。"""
        matching = [c for c in self._cases if c.hexagram == hexagram]
        return matching[:top_k]


class L4MemoryAdapter:
    """
    L4 记忆系统适配器。

    从 L4 cases 目录中读取案例并进行相似度检索。
    """

    def __init__(self, cases_dir: str = None):
        self.cases_dir = cases_dir
        self._all_cases_cache: Optional[List[BCRMMemoryCase]] = None

    def _load_all_cases(self) -> List[BCRMMemoryCase]:
        """加载所有案例。"""
        if self._all_cases_cache is not None:
            return self._all_cases_cache

        cases = []
        if not self.cases_dir or not os.path.exists(self.cases_dir):
            self._all_cases_cache = cases
            return cases

        cases_path = Path(self.cases_dir)
        for f in cases_path.glob("*.json"):
            try:
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                case = self._parse_case(data)
                if case:
                    cases.append(case)
            except Exception:
                continue

        self._all_cases_cache = cases
        return cases

    def _parse_case(self, data: Dict) -> Optional[BCRMMemoryCase]:
        """解析 L4 case 为 BCRMMemoryCase。"""
        try:
            env = data.get("environment_snapshot", {})
            outcome = data.get("decision_outcome", {})
            tags = data.get("tags", [])

            # 从 tags 中提取卦象
            bagua = ""
            for tag in tags:
                if tag.startswith("gua_"):
                    bagua = tag[4:]
                    break

            # 从 thinking_chain 提取卦象
            if not bagua:
                chain = data.get("thinking_chain", [])
                for step in chain:
                    if step.get("bagua"):
                        bagua = step["bagua"]
                        break

            direction = outcome.get("direction",
                                    env.get("trend_direction", "UNKNOWN"))

            return BCRMMemoryCase(
                case_id=data.get("case_id", ""),
                bagua=bagua,
                hexagram=data.get("bcrm_output", {}).get("hexagram", {}).get("hexagram_name", ""),
                direction=direction,
                accumulation=outcome.get("accumulation", 0.5),
                is_qualitative_change=outcome.get("is_qualitative_change", False),
                price_change=outcome.get("pnl_pct", 0),
                dominant_side_switched=outcome.get("dominant_side_switched", False),
                gua_flipped=outcome.get("gua_flipped", False),
                similarity=0.0,
                regime=env.get("regime", ""),
            )
        except Exception:
            return None

    def retrieve_similar(self,
                         snapshot: Dict[str, Any],
                         top_k: int = 5) -> List[BCRMMemoryCase]:
        """检索相似案例。"""
        all_cases = self._load_all_cases()
        if not all_cases:
            return []

        # 简化的相似度计算：基于 regime 和 trend_direction
        regime = snapshot.get("regime", "")
        trend = snapshot.get("trend_direction", "")

        scored = []
        for case in all_cases:
            score = 0.0
            if case.regime == regime:
                score += 0.5
            if case.direction.upper() == trend.upper():
                score += 0.3
            # 随机增加一点变化
            score += hash(case.case_id) % 100 / 1000
            case.similarity = score
            scored.append(case)

        scored.sort(key=lambda x: -x.similarity)
        return scored[:top_k]

    def retrieve_by_gua(self,
                        gua: str,
                        top_k: int = 5) -> List[BCRMMemoryCase]:
        """按卦象检索。"""
        all_cases = self._load_all_cases()
        matching = [c for c in all_cases if c.bagua == gua]
        return matching[:top_k]

    def invalidate_cache(self):
        """使缓存失效。"""
        self._all_cases_cache = None


def default_memory_adapter() -> MockMemoryAdapter:
    """获取默认记忆适配器。"""
    return MockMemoryAdapter(num_cases=20)
