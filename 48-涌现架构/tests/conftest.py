"""48-涌现架构 测试公共配置：把 registry/ 与 bus/ 加入 import 路径。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _sub in ("registry", "bus", "reflection", "metrics"):
    _p = str(_ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
