"""dreambuddy_core — 向后兼容 shim
自 2026-09-04 起所有自进化系统代码迁移至:
  23-四层闭环自进化交易架构/dreambuddy_evolution/

本包仅做路径注入 + re-export，不持有实际代码。
旧代码 `from dreambuddy_core.default_weights import WEIGHTS` 仍可工作。
新代码应直接 `from dreambuddy_evolution.weights import WEIGHTS`。
"""
import sys
from pathlib import Path

_evolution_dir = Path(__file__).resolve().parent.parent / "23-四层闭环自进化交易架构"
if str(_evolution_dir) not in sys.path:
    sys.path.insert(0, str(_evolution_dir))
