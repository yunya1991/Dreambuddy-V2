"""
dreambuddy_dal.protocols.risk_repo — RiskRepository Protocol（风控域）
对齐 SCHEMA_DESIGN.md §6 rs_state + rs_cases；其中 rs_state 为单行 id=1 + 乐观锁 version
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from dreambuddy_dal.unified_models import RiskCaseRecord, RiskLevel, RiskState


class RiskRepository(ABC):
    """
    风控状态 / 案例 Repository。核心约束：
    - get_state / update_state 强制单行（id=1），DB 层 CHECK(id=1) + 乐观锁 version
    - update_state 必须带 expected_version（DB 触发器 WHERE version=预期才 update；否则抛并发冲突）
    """

    @abstractmethod
    def get_state(self, id: int = 1) -> Optional[RiskState]:
        """
        取系统风控状态。永远 id=1。
        返回 None 意味着系统还未初始化任何风险快照（首次启动需写入初始状态）。
        """
        ...

    @abstractmethod
    def update_state(
        self,
        new_state: RiskState,
        *,
        expected_version: Optional[int] = None,
    ) -> bool:
        """
        乐观锁更新 RiskState。
        - expected_version = 当前 RiskState.version（get_state 时拿到的）
        - 若 DB 实际 version != expected_version → 返回 False（并发冲突，让调用方重试）
        - new_state.version 忽略不读（version 完全由 DB 触发器维护）
        """
        ...

    @abstractmethod
    def add_case(self, case: RiskCaseRecord) -> bool:
        """记录一条风控拦截 / 放行案例（rs_cases）"""
        ...

    @abstractmethod
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
        """风控案例查询（含按 severity ≥ min_severity 过滤）"""
        ...
