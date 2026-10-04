"""N-P1b 角色分离 + 隔离区 + 验证宽限期。

设计来源：千问 N-P1b 角色分离交叉验证方案
核心机制：
1. 角色分离：构造者（creator_id）不能给自己验证，该信号视为 abstain
2. 隔离区：新记忆先入 quarantine，验证通过后释放
3. 验证宽限期：C 档记忆在 grace_verify_count 次内不因 fail 降权

硬约束：
- 角色违规 = abstain（不报错，FAIL-OPEN）
- 隔离区可开关（默认 ON）
- 宽限期可开关（默认 ON，仅 C 档）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 角色分离
# ---------------------------------------------------------------------------

def filter_self_verification(
    signals: List[Any],
    creator_id: str,
) -> List[Any]:
    """过滤构造者自验证信号（verdict → abstain）。

    不修改原信号，返回新列表（深拷贝语义：frozen dataclass 直接替换，dict 浅拷贝）。
    """
    filtered: List[Any] = []
    for s in signals:
        if isinstance(s, dict):
            verifier = s.get("verifier_id", "")
            new_s = dict(s)
            if verifier == creator_id:
                new_s["verdict"] = "abstain"
            filtered.append(new_s)
        else:
            verifier = getattr(s, "verifier_id", "")
            if verifier == creator_id:
                # frozen dataclass → 用 replace 重建
                try:
                    from dataclasses import replace
                    filtered.append(replace(s, verdict="abstain"))
                except Exception:
                    filtered.append(s)
            else:
                filtered.append(s)
    return filtered


@dataclass
class RolePolicy:
    """角色分离策略配置。"""
    enabled: bool = True

    def filter(self, signals: List[Any], creator_id: str) -> List[Any]:
        if not self.enabled:
            return list(signals)
        return filter_self_verification(signals, creator_id)


# ---------------------------------------------------------------------------
# 隔离区
# ---------------------------------------------------------------------------

@dataclass
class QuarantineManager:
    """记忆隔离区管理。

    新记忆默认在隔离区，需验证通过才能释放。
    状态机：unknown → quarantine → released
    """
    enabled: bool = True
    _state: Dict[str, str] = field(default_factory=dict)  # memory_id -> "quarantine" | "released"

    def quarantine(self, memory_id: str) -> None:
        if self.enabled:
            self._state[memory_id] = "quarantine"

    def release(self, memory_id: str, verified: bool = True) -> None:
        if not self.enabled:
            return
        if verified:
            self._state[memory_id] = "released"

    def is_quarantined(self, memory_id: str) -> bool:
        if not self.enabled:
            return False
        state = self._state.get(memory_id, "released")  # 未知 → 默认已释放（兼容存量记忆）
        return state == "quarantine"

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "quarantined_count": sum(1 for v in self._state.values() if v == "quarantine"),
        }


# ---------------------------------------------------------------------------
# 验证宽限期
# ---------------------------------------------------------------------------

@dataclass
class GracePolicy:
    """C 档验证宽限期策略。

    C 档记忆在 grace_verify_count 次 verify 内不因 fail 降权，
    对抗指数遗忘（C 档稳态 conf≈0.400 < A 档阈值 0.70）。
    """
    enabled: bool = True
    grace_verify_count: int = 3
    grace_quality: str = "C"

    def is_in_grace(self, quality: str, verify_count: int) -> bool:
        if not self.enabled:
            return False
        if quality != self.grace_quality:
            return False
        return verify_count < self.grace_verify_count

    def should_downgrade(self, quality: str, verify_count: int, success: bool) -> bool:
        """是否应降权。宽限期内的 C 档 fail 不降权。"""
        if success:
            return False  # pass 总是允许升级
        if self.is_in_grace(quality, verify_count):
            return False  # 宽限期内的 C 档 fail 被保护
        return True


# 模块级便捷函数（使用默认 GracePolicy）
_default_grace = GracePolicy()


def is_in_grace_period(quality: str, verify_count: int) -> bool:
    """便捷函数：使用默认宽限期策略判断。"""
    return _default_grace.is_in_grace(quality, verify_count)

