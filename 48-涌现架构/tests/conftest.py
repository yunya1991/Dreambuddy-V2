"""48-涌现架构 测试公共配置：把 registry/ 加入 import 路径。"""

import sys
from pathlib import Path

_REGISTRY = Path(__file__).resolve().parents[1] / "registry"
if str(_REGISTRY) not in sys.path:
    sys.path.insert(0, str(_REGISTRY))
