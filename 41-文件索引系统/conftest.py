# -*- coding: utf-8 -*-
"""conftest.py — 41-文件索引系统 pytest 配置

确保 41 根目录在 sys.path 最前面，避免与其他模块的 core 命名空间包冲突。
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
