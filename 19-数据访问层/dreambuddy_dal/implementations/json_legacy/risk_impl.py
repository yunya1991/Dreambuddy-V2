"""JsonLegacyRiskRepository（P0 内存实现：单行 RiskState id=1 + RiskCases 列表）"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from dreambuddy_dal.protocols.risk_repo import RiskRepository
from dreambuddy_dal.unified_models import RiskCaseRecord, RiskLevel, RiskState

_RISK_STATE_STORE: Dict[int, RiskState] = {}
_RISK_CASES: List[RiskCaseRecord] = []


class JsonLegacyRiskRepository(RiskRepository):
    def get_state(self, id: int = 1) -> Optional[RiskState]:
        return _RISK_STATE_STORE.get(id)

    def update_state(
        self,
        new_state: RiskState,
        *,
        expected_version: Optional[int] = None,
    ) -> bool:
        """乐观锁（P0 内存简单版：仅比较 expected_version == 当前 version）"""
        if expected_version is not None:
            old = _RISK_STATE_STORE.get(new_state.id)
            if old is not None and old.version != expected_version:
                return False
        # version +1（模拟 DB 触发器，P0 Python 层简单模拟）
        new_state.version = (new_state.version + 1) if new_state.id in _RISK_STATE_STORE else 0
        _RISK_STATE_STORE[new_state.id] = new_state
        return True

    def add_case(self, case: RiskCaseRecord) -> bool:
        _RISK_CASES.append(case)
        return True

    def query_cases(
        self,
        *,
        start_ts: Optional[datetime] = None,
        end_ts: Optional[datetime] = None,
        min_severity: Optional[int] = None,
        risk_level: Optional[RiskLevel] = None,
        symbol: Optional[str] = None,
        limit: int = 500,
    ) -> List[RiskCaseRecord]:
        out: List[RiskCaseRecord] = []
        for c in _RISK_CASES:
            if start_ts and c.detected_at < start_ts:
                continue
            if end_ts and c.detected_at > end_ts:
                continue
            if min_severity is not None and (c.severity_score or 0) < min_severity:
                continue
            if risk_level and c.risk_level != risk_level:
                continue
            if symbol and c.symbol != symbol:
                continue
            out.append(c)
            if len(out) >= limit:
                break
        return out


__all__ = ["JsonLegacyRiskRepository"]
