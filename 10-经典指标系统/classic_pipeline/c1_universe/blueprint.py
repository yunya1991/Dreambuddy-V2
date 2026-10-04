"""C1 品种筛选 Blueprint（骨架）。

路由前缀：`/universe`
路由将随 `_universe_*` 函数迁移逐步填充。
"""
from flask import Blueprint

bp = Blueprint("c1_universe", __name__, url_prefix="/universe")
