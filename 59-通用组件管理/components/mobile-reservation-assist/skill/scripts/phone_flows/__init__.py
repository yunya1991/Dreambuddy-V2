"""平台流程层：剪映 / 抖音的 u2 点击路径。

流程与手机端 Auto.js 脚本保持同一条真机路径，只替换执行器；
失败一步即抛 U2Error（带页面文本与截图），由 runner 问千问，不本地盲试。
"""

from __future__ import annotations
