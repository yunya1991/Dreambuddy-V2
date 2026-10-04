"""29-事件驱动策略系统测试配置。

确保 29 号目录在 sys.path 中，使 event_driven 包可被 import。
同时添加 23 号目录路径，支持跨子系统集成测试（如 EventDominanceController 与 agi_config 的开关门控）。
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 29 号目录（event_driven 包）
_29_DIR = str(_PROJECT_ROOT / "29-事件驱动策略系统")
if _29_DIR not in sys.path:
    sys.path.insert(0, _29_DIR)

# 23 号目录（agi_config 等跨子系统依赖）
_23_DIR = str(_PROJECT_ROOT / "23-四层闭环自进化交易架构")
if _23_DIR not in sys.path:
    sys.path.insert(0, _23_DIR)
