"""C2 信号识别 Blueprint（骨架）。

路由前缀：`/signals`, `/quant`, `/three_screen`
路由将随 signal/quant/three_screen 函数迁移逐步填充。
"""
from flask import Blueprint

bp = Blueprint("c2_signals", __name__)
