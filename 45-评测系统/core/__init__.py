# -*- coding: utf-8 -*-
"""
45-评测系统 包初始化。

注意：仓库根 conftest.py 会把多个子系统目录注入 sys.path，
其中存在同名 core 包（如 12-三屏趋势系统/core）。
本 __init__.py 使 45-评测系统/core 成为正规包，
配合 45-评测系统/conftest.py 将本模块根目录置于 sys.path[0]，
确保 `from core.xxx import ...` 稳定解析到本模块。
"""
