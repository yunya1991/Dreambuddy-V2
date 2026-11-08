"""
风控规则集 - 可插拔的默认规则
"""

from .exit_rules import register_default_exit_rules
from .gate_rules import register_default_gate_rules
from .position_rules import register_default_position_rules

__all__ = [
    "register_default_gate_rules",
    "register_default_position_rules",
    "register_default_exit_rules",
]
