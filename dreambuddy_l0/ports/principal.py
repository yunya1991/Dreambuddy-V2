"""Port 层 Principal 硬门禁 — SPEC-L0-AGENT-TRAIN-BASE v0.1 §0.5.2（D1）

问题：PACKAGING Mandate 只在壳内拦截，跨域 agent 可以绕过壳直接
import port adapter 调用写接口。

修复（硬约束）：任何通过 port Protocol 调用写接口的代码必须携带
principal 信息。壳层自动注入 principal（从 envelope.meta.principal），
直接 import port adapter 的调用者必须显式提供，否则抛
PrincipalMissingError。

D1 硬约束：此门禁是 port 层 Python 硬门禁，不是壳层治理约束。

Principal 门禁表（§0.5.2）：
    MemoryPort  record / verify        允许 {user, agent_admin, trae}
    StorePort   write                  允许 {user, agent_admin}
    AnalysisPort verify_beta_adapter   允许 {user, agent_admin, trae}
    DataPort / SearchPort（只读）      N/A
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, FrozenSet


class PrincipalMissingError(Exception):
    """直接 import port adapter 但没带 _principal 的拦截。"""


# 各 port 写接口允许的 principal.role 集合（§0.5.2 门禁表）
ALLOWED_ROLES_MEMORY: FrozenSet[str] = frozenset({"user", "agent_admin", "trae"})
ALLOWED_ROLES_STORE: FrozenSet[str] = frozenset({"user", "agent_admin"})


def _check_role(principal: Dict[str, Any], allowed_roles: FrozenSet[str]) -> None:
    """校验 principal.role 是否在允许集合内（fail-closed：缺失即拒绝）。"""
    role = principal.get("role")
    if role not in allowed_roles:
        raise PrincipalMissingError(
            f"principal.role={role!r} not in allowed roles {sorted(allowed_roles)}. "
            "Write via port requires an authorized principal."
        )


def require_principal(allowed_roles: FrozenSet[str] = ALLOWED_ROLES_MEMORY) -> Callable:
    """Port 层 Principal 硬门禁装饰器（D1）。

    用法（挂载在 adapter 写接口上）：

        @require_principal(ALLOWED_ROLES_MEMORY)
        def record(self, ..., _principal: Optional[Dict] = None) -> ...:
            ...

    规则：
    - _principal 缺失（None）→ 抛 PrincipalMissingError（fail-closed）
    - _principal.role 不在 allowed_roles → 抛 PrincipalMissingError
    - 通过 → 剥离 _principal 后执行原方法（业务签名零感知）
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args: Any, **kwargs: Any) -> Any:
            principal = kwargs.pop("_principal", None)
            if principal is None:
                raise PrincipalMissingError(
                    f"{func.__name__} requires _principal kwarg. "
                    "Agent must pass principal through shell Mandate injection, "
                    "not bypass port directly."
                )
            _check_role(principal, allowed_roles)
            return func(self, *args, **kwargs)

        return wrapper

    return decorator
