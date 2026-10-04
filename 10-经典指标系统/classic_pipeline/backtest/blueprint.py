"""C3 回测验证 Blueprint（骨架）。

路由前缀：`/backtest`
路由将随 `_bt_*` 函数迁移逐步填充。
"""
from flask import Blueprint

bp = Blueprint("c3_backtest", __name__, url_prefix="/backtest")
