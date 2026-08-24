"""conftest.py — 21-特征工程中心 测试路径配置"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_21_ROOT = Path(__file__).resolve().parents[1]

for p in [str(_21_ROOT), str(_21_ROOT / "feature_hub")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# 19号（dreambuddy_dal 供 GoldReader 读取）
_DAL_19 = _PROJECT_ROOT / "19-数据访问层"
if str(_DAL_19) not in sys.path:
    sys.path.insert(0, str(_DAL_19))

# 18号（data_center 供 GoldReader 获取 OHLCV）
_DATA_18 = _PROJECT_ROOT / "18-数据获取中心"
if str(_DATA_18) not in sys.path:
    sys.path.insert(0, str(_DATA_18))

# 10号（供 T31 测试 Bot2StrategyTrend 策略一致性）
_CLASSIC_10 = _PROJECT_ROOT / "10-经典指标系统"
if str(_CLASSIC_10) not in sys.path:
    sys.path.insert(0, str(_CLASSIC_10))
