"""50 测试路径注入：使 `from core...` 可用。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
