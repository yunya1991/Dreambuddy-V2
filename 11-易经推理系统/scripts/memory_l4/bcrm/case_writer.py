"""
BCRM 案例写入器。

将 BCRM 推理结果写入 L4 记忆系统，支持：
- 实时写入
- 批量写入
- 结果标注
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from .output_contract import BCRMOutput


class CaseWriter:
    """
    BCRM 案例写入器。
    """

    def __init__(self,
                 cases_dir: str = None,
                 auto_flush: bool = True,
                 max_queue_size: int = 100):
        self.cases_dir = cases_dir
        self.auto_flush = auto_flush
        self.max_queue_size = max_queue_size
        self._queue: List[Dict] = []

    def _ensure_dir(self):
        """确保目录存在。"""
        if not self.cases_dir:
            return False
        os.makedirs(self.cases_dir, exist_ok=True)
        return True

    def write_case(self,
                   market_snapshot: Dict[str, Any],
                   bcrm_output: BCRMOutput,
                   actual_outcome: Dict = None,
                   contradiction_list: List[Dict] = None,
                   memory_cases: List[Dict] = None,
                   qmm_output: Dict = None,
                   case_id: str = None,
                   symbol: str = "UNKNOWN",
                   timeframe: str = "1h") -> str:
        """
        写入单个案例。

        Args:
            market_snapshot: 市场快照
            bcrm_output: BCRM 输出
            actual_outcome: 实际结果
            contradiction_list: 矛盾列表
            memory_cases: 记忆案例
            qmm_output: QMM 输出
            case_id: 案例 ID
            symbol: 交易标的
            timeframe: 时间周期

        Returns:
            case_id
        """
        if case_id is None:
            case_id = f"bcrm_{symbol}_{timeframe}_{int(time.time())}_{uuid.uuid4().hex[:8]}"

        case = self._build_case(
            case_id=case_id,
            market_snapshot=market_snapshot,
            bcrm_output=bcrm_output,
            actual_outcome=actual_outcome,
            contradiction_list=contradiction_list,
            memory_cases=memory_cases,
            qmm_output=qmm_output,
            symbol=symbol,
            timeframe=timeframe,
        )

        if self.auto_flush:
            self._flush_case(case)
        else:
            self._queue.append(case)
            if len(self._queue) >= self.max_queue_size:
                self.flush()

        return case_id

    def _build_case(self,
                    case_id: str,
                    market_snapshot: Dict[str, Any],
                    bcrm_output: BCRMOutput,
                    actual_outcome: Dict = None,
                    contradiction_list: List[Dict] = None,
                    memory_cases: List[Dict] = None,
                    qmm_output: Dict = None,
                    symbol: str = "UNKNOWN",
                    timeframe: str = "1h") -> Dict[str, Any]:
        """构建案例结构。"""
        # 构建 thinking_chain 供 L4 检索
        thinking_chain = []

        # 步骤 1: 矛盾识别
        if contradiction_list:
            thinking_chain.append({
                "step": 1,
                "name": "矛盾识别",
                "contradictions": contradiction_list,
            })

        # 八卦状态
        thinking_chain.append({
            "step": "bagua_state",
            "bagua": bcrm_output.bagua,
            "direction": bcrm_output.next_state.direction if bcrm_output.next_state else "UNKNOWN",
        })

        # 六十四卦结果
        if bcrm_output.hexagram and bcrm_output.hexagram.hexagram_name:
            thinking_chain.append({
                "step": "yijing",
                "hexagram": bcrm_output.hexagram.hexagram_name,
                "changing_yaos": bcrm_output.hexagram.changing_yaos,
            })

        # 构建 tags
        tags = [
            "bcrm",
            f"gua_{bcrm_output.bagua}",
            f"regime_{market_snapshot.get('regime', 'unknown')}",
            f"direction_{bcrm_output.next_state.direction if bcrm_output.next_state else 'unknown'}",
        ]

        # 质变判定：通过 transformation_trigger.probability 判断
        if (bcrm_output.transformation_trigger and
                bcrm_output.transformation_trigger.probability == "HIGH"):
            tags.append("qualitative_change")

        if bcrm_output.hexagram and bcrm_output.hexagram.hexagram_name:
            tags.append(f"hex_{bcrm_output.hexagram.hexagram_name}")

        # P1-1: 测试数据标记，与 UnifiedCaseRegistry._detect_is_test 逻辑一致
        _TEST_KEYWORDS = ("test", "qmm_test", "backup", "demo", "sample", "mock")
        is_test = any(kw in case_id.lower() for kw in _TEST_KEYWORDS)

        case = {
            "case_id": case_id,
            "schema_version": "4.0",
            # P0-2: 统一来源标识，与 UnifiedCaseRegistry v0.3 的 system_source 对齐，
            # 使下游 ReviewEngine/DistillEngine/l4_stats_adapter 可按 system_source 统一过滤，
            # 不再依赖 case_id 前缀区分来源。
            "system_source": "yijing_inference",
            # P1-1: 测试数据标记，下游消费时按 is_test=False 过滤训练集
            "is_test": is_test,
            "symbol": symbol,
            "timeframe": timeframe,
            "snapshot_ts": market_snapshot.get("snapshot_ts",
                                               datetime.now(timezone.utc).isoformat()),
            "environment_snapshot": {
                "price": market_snapshot.get("price", market_snapshot.get("close", 0)),
                "regime": market_snapshot.get("regime", ""),
                "trend_direction": market_snapshot.get("trend_direction", ""),
                "supply_demand_score": market_snapshot.get("supply_demand_score", 0.5),
                "technical_score": market_snapshot.get("technical_score", 0.5),
                "capital_flow_score": market_snapshot.get("capital_flow_score", 0.5),
                "sentiment_score": market_snapshot.get("sentiment_score", 0.5),
                "volatility": market_snapshot.get("volatility", 0.0),
                "volume_ratio": market_snapshot.get("volume_ratio", 1.0),
            },
            "thinking_chain": thinking_chain,
            "contradictions": contradiction_list or [],
            "bcrm_output": bcrm_output.to_dict(),
            "qmm_output": qmm_output or {},
            "memory_cases_refs": [c.get("case_id", "") for c in (memory_cases or [])],
            "decision_outcome": actual_outcome or {},
            "tags": tags,
            "embedding": {
                "version": "mock_v1",
                "vector": [],
                "bagua": bcrm_output.bagua,
            },
            "performance_metrics": {
                "dialectic_confidence": (
                    bcrm_output.next_state.confidence if bcrm_output.next_state else 0.0),
                "memory_used": len(memory_cases) if memory_cases else 0,
            },
        }

        return case

    def _flush_case(self, case: Dict):
        """写入单个案例到文件。"""
        if not self._ensure_dir():
            return

        case_id = case.get("case_id", "unknown")
        filepath = Path(self.cases_dir) / f"{case_id}.json"

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(case, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def flush(self):
        """刷新队列。"""
        for case in self._queue:
            self._flush_case(case)
        self._queue.clear()

    def update_outcome(self,
                       case_id: str,
                       actual_outcome: Dict[str, Any],
                       is_correct: bool = None,
                       price_change: float = None,
                       dominant_side_switched: bool = None,
                       gua_flipped: bool = None):
        """
        更新案例的实际结果。

        Args:
            case_id: 案例 ID
            actual_outcome: 实际结果
            is_correct: 是否正确
            price_change: 价格变化
            dominant_side_switched: 主导方是否切换
            gua_flipped: 卦象是否翻转
        """
        if not self.cases_dir:
            return

        filepath = Path(self.cases_dir) / f"{case_id}.json"
        if not filepath.exists():
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                case = json.load(f)

            outcome = case.get("decision_outcome", {})
            outcome.update(actual_outcome)

            if is_correct is not None:
                outcome["is_correct"] = is_correct
            if price_change is not None:
                outcome["price_change"] = price_change
            if dominant_side_switched is not None:
                outcome["dominant_side_switched"] = dominant_side_switched
            if gua_flipped is not None:
                outcome["gua_flipped"] = gua_flipped

            case["decision_outcome"] = outcome

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(case, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def batch_write(self, cases: List[Dict]):
        """批量写入。"""
        for case in cases:
            if self.auto_flush:
                self._flush_case(case)
            else:
                self._queue.append(case)

        if not self.auto_flush and len(self._queue) >= self.max_queue_size:
            self.flush()

    def get_queue_size(self) -> int:
        """获取队列大小。"""
        return len(self._queue)


def default_case_writer(cases_dir: str = None) -> CaseWriter:
    """获取默认案例写入器。"""
    return CaseWriter(cases_dir=cases_dir, auto_flush=True)
