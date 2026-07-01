"""
KR 模板库 (KR Templates)

包含单线模式和多线模式的预定义KR模板
"""

from .single_line import (
    SINGLE_LINE_TEMPLATES,
    get_single_line_template,
    has_single_line_template,
)
from .multi_line import (
    MULTI_LINE_TEMPLATES,
    get_multi_line_template,
    has_multi_line_template,
)

__all__ = [
    'SINGLE_LINE_TEMPLATES',
    'get_single_line_template',
    'has_single_line_template',
    'MULTI_LINE_TEMPLATES',
    'get_multi_line_template',
    'has_multi_line_template',
]
