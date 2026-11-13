"""风控资金子包（自 16-调控系统 迁入）
=====================================
- capital_control   ：账户级 USDT 预算（CapitalControlComponent）
- capital_allocator ：币种级 Kelly/层级/扩展定容（CapitalAllocatorComponent）

两者均通过 ``core.registry`` / ``core.factory`` 消费 13 的风控基础设施，
是 13 成为「唯一风控模块」后的资金层实现。
"""

__all__ = ["capital_control", "capital_allocator"]
