"""
19-数据访问层 pytest 配置
- 把子系统根目录加到 sys.path 保证 import dreambuddy_dal 可用
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DAL_ROOT = Path(__file__).resolve().parent.parent  # .../19-数据访问层
if str(DAL_ROOT) not in sys.path:
    sys.path.insert(0, str(DAL_ROOT))

# 保证测试期的 DATA_DIR 用单独的临时目录（不污染真实数据）
os.environ.setdefault("DATA_DIR", str(DAL_ROOT / "tests" / "_test_data"))
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)
os.environ.setdefault("DB_BACKEND", "json_legacy")
os.environ.setdefault("READ_SOURCE", "legacy")
