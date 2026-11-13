"""兼容 shim：capital_control 已迁入 13-通用风控模块/risk_capital。

本文件不做任何实现，仅把旧路径导入重定向到真实模块，保证 11 等调用方
无需改动；子模块（component / types / capital_rules.*）同样按旧路径可用。
"""

from _risk_capital_shim import install

install("capital_control", "risk_capital.capital_control")
