# -*- coding: utf-8 -*-
"""
45-评测系统 测试会话配置
=========================
问题：仓库根 conftest.py 会把 12/13/14 等子系统目录插入 sys.path，
其中存在同名 `core` 包，会劫持 `from core.xxx import ...` 的解析。

对策：在 45 自己的测试会话中，把本模块根目录插入 sys.path[0]。
本 conftest 在根 conftest 之后、测试模块导入之前执行，
因此 `core` / `storage` / `api` 均稳定解析到本模块。
"""

import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))
else:
    sys.path.insert(0, sys.path.pop(sys.path.index(str(MODULE_ROOT))))
