"""shim — FeatureRegistry 已提拔至 21-特征工程中心/feature_hub/hub/feature_registry.py

H2 集成点：此文件仅做反向 re-export，保证所有 `from ...feature_registry import *` 调用方
零感知、零回归。实际实现请勿在此修改，统一到 feature_hub 维护。
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # dreambuddy-v2/
_21_ROOT = _PROJECT_ROOT / "21-特征工程中心"
if str(_21_ROOT) not in sys.path:
    sys.path.insert(0, str(_21_ROOT))

from feature_hub.hub.feature_registry import (  # noqa: F401,E402
    ENABLED_SETS,
    FeatureModuleSpec,
    FeatureRegistry,
    _cycle_sub_key_splitter,
    _wdh_sub_key_splitter,
)
