"""C4 风险评估 Blueprint（骨架）。

路由前缀：`/carry`, `/governance`
路由将随 `_carry_*`/`_governance_*` 函数迁移逐步填充。
"""
from flask import Blueprint

bp = Blueprint("c4_risk", __name__)
