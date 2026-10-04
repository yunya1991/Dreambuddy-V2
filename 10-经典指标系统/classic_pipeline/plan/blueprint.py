"""C6 计划生成 Blueprint（骨架）。

路由前缀：`/strategy`
路由将随 `_strategy_*` 函数迁移逐步填充。
"""
from flask import Blueprint

bp = Blueprint("c6_plan", __name__, url_prefix="/strategy")
