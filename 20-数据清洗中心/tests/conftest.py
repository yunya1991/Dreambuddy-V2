"""20号测试 conftest：统一处理跨包 import（18-data_center / 20-data_cleaning）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]        # 20-数据清洗中心/
PROJECT = Path(__file__).resolve().parents[2]     # dreambuddy-v2/

# 20号主包（data_cleaning）
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 18号（data_center 供 quality/alerting 复用）
DATA_18 = PROJECT / "18-数据获取中心"
if str(DATA_18) not in sys.path:
    sys.path.insert(0, str(DATA_18))

# 19号（dreambuddy_dal 供 DalSink 写入）
DAL_19 = PROJECT / "19-数据访问层"
if str(DAL_19) not in sys.path:
    sys.path.insert(0, str(DAL_19))

# 21号（feature_hub 供 GoldReader + FeaturePipeline E2E）
FH_21 = PROJECT / "21-特征工程中心"
if str(FH_21) not in sys.path:
    sys.path.insert(0, str(FH_21))

# 让 Python 认定 data_cleaning 是根包（相对导入不走父目录）
# ——（conftest.py 会在测试前运行，所以这会先生效）
