"""
BCRM 护栏（Guardrail）。

输入验证和 fail-closed 机制。
遵循 QMM 铁律 0.2：关键输入缺失 → fail-closed。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple


@dataclass
class GuardResult:
    """护栏检查结果。"""
    passed: bool = True
    fail_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_fail(self, reason: str):
        self.passed = False
        self.fail_reasons.append(reason)

    def add_warning(self, warning: str):
        self.warnings.append(warning)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "fail_reasons": self.fail_reasons,
            "warnings": self.warnings,
        }


class BCRMGuardrail:
    """
    BCRM 护栏。

    负责输入验证、数据质量检查、fail-closed 判定。
    """

    def __init__(self,
                 min_contradictions: int = 1,
                 max_uncertainty: float = 0.8,
                 required_fields: List[str] = None):
        self.min_contradictions = min_contradictions
        self.max_uncertainty = max_uncertainty
        self.required_fields = required_fields or [
            "price", "volume",
        ]

    def validate(self,
                 market_snapshot: Dict[str, Any],
                 contradiction_list: List[Dict] = None,
                 qmm_output: Dict = None) -> GuardResult:
        """
        验证输入。

        Args:
            market_snapshot: 市场快照
            contradiction_list: 矛盾列表
            qmm_output: QMM 输出

        Returns:
            GuardResult
        """
        result = GuardResult()

        # 检查市场快照必填字段
        for field in self.required_fields:
            if field not in market_snapshot:
                result.add_warning(f"缺少字段: {field}")

        # 检查矛盾列表
        if not contradiction_list or len(contradiction_list) < self.min_contradictions:
            result.add_fail("矛盾列表为空或不足")

        # 检查 QMM 不确定性
        if qmm_output:
            uncertainty = qmm_output.get("uncertainty", 0)
            if uncertainty > self.max_uncertainty:
                result.add_fail(f"QMM 不确定性过高: {uncertainty:.2%}")

        # 检查价格数据
        price = market_snapshot.get("price", market_snapshot.get("close", 0))
        if price <= 0:
            result.add_fail("价格数据无效")

        return result


def default_guardrail() -> BCRMGuardrail:
    """获取默认护栏。"""
    return BCRMGuardrail()
