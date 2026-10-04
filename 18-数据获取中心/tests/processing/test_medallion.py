"""W3b-2 RED 测试 — 奖章架构清洗链路 Bronze→Silver→Gold。

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §6.3 / §9.3 测试 8-12

测试清单:
  8.  test_silver_layer_dedup_unique_constraint   — (timestamp, symbol) 唯一
  9.  test_silver_layer_3sigma_filter              — 3σ 异常值过滤
  10. test_silver_layer_iqr_filter                 — IQR 异常值过滤
  11. test_silver_layer_atr_filter                — 动态 ATR 异常值过滤
  12. test_gold_layer_schema_validation           — Gold 层 Schema 验证

设计原则:
  - 纯数据处理逻辑，不依赖外部 API
  - FAIL-OPEN 铁律: 异常 → 保留原始数据不阻塞
  - project_memory 硬约束: Bronze 保留原始，Silver 清洗，Gold Schema 验证
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_center.processing.silver_layer import (
    SilverLayerCleaner,
    dedup_by_timestamp_symbol,
    filter_3sigma,
    filter_iqr,
    filter_dynamic_atr,
)
from data_center.processing.gold_layer import (
    GoldLayerValidator,
    validate_schema,
    WASHOUT_SCHEMAS,
)


# ============================================================
# 测试 8: Silver 层去重 (timestamp, symbol) 唯一
# ============================================================
def test_silver_layer_dedup_unique_constraint():
    """Silver 层去重: (timestamp, symbol) 组合唯一。"""
    df = pd.DataFrame([
        {"timestamp": "2026-01-01T00:00:00Z", "symbol": "BTC", "cvd_value": 100.0},
        {"timestamp": "2026-01-01T00:00:00Z", "symbol": "BTC", "cvd_value": 200.0},  # 重复
        {"timestamp": "2026-01-01T00:00:00Z", "symbol": "ETH", "cvd_value": 50.0},
        {"timestamp": "2026-01-01T00:05:00Z", "symbol": "BTC", "cvd_value": 150.0},
    ])
    result = dedup_by_timestamp_symbol(df)
    # 去重后 3 条（第二条 BTC 重复被去除）
    assert len(result) == 3
    # 保留第一条（last=False 默认）
    btc_0000 = result[(result["symbol"] == "BTC") & (result["timestamp"] == "2026-01-01T00:00:00Z")]
    assert len(btc_0000) == 1
    assert btc_0000["cvd_value"].iloc[0] == 100.0


# ============================================================
# 测试 9: Silver 层 3σ 异常值过滤
# ============================================================
def test_silver_layer_3sigma_filter():
    """Silver 层 3σ 过滤: |value - mean| > 3σ 的记录被过滤。"""
    np.random.seed(42)
    normal = np.random.normal(100, 5, 50)  # 均值 100，标准差 5
    df = pd.DataFrame({"cvd_value": normal.tolist()})
    # 添加一个明显异常值 (mean=100, std=5, 3σ=15, 200 远超 115)
    df.loc[len(df)] = 200.0  # 异常值
    result = filter_3sigma(df, "cvd_value")
    # 异常值被过滤
    assert 200.0 not in result["cvd_value"].values
    # 正常值保留
    assert len(result) == 50


# ============================================================
# 测试 10: Silver 层 IQR 异常值过滤
# ============================================================
def test_silver_layer_iqr_filter():
    """Silver 层 IQR 过滤: 超出 [Q1-1.5*IQR, Q3+1.5*IQR] 的记录被过滤。"""
    np.random.seed(42)
    normal = np.random.normal(100, 5, 50)
    df = pd.DataFrame({"cvd_value": normal.tolist()})
    # 添加一个明显异常值
    df.loc[len(df)] = 500.0  # 远超 Q3 + 1.5*IQR
    result = filter_iqr(df, "cvd_value")
    # 异常值被过滤
    assert 500.0 not in result["cvd_value"].values
    assert len(result) == 50


# ============================================================
# 测试 11: Silver 层动态 ATR 异常值过滤
# ============================================================
def test_silver_layer_atr_filter():
    """Silver 层动态 ATR 过滤: |value - prev| > k*ATR 的记录被过滤。"""
    # 构造平稳序列 + 一个突变
    values = [100.0 + i * 0.1 for i in range(30)]  # 平稳上升
    values.append(200.0)  # 突变，远超 ATR 动态阈值
    df = pd.DataFrame({"cvd_value": values})
    result = filter_dynamic_atr(df, "cvd_value", window=14, k=3.0)
    # 突变值被过滤
    assert 200.0 not in result["cvd_value"].values
    # 大部分平稳值保留
    assert len(result) >= 28


# ============================================================
# 测试 12: Gold 层 Schema 验证
# ============================================================
def test_gold_layer_schema_validation():
    """Gold 层 Schema 验证: 缺字段/类型错误 → 拦截。"""
    # WASHOUT_SCHEMAS 定义了各表所需字段
    assert "cvd_clean" in WASHOUT_SCHEMAS
    assert "ofi_clean" in WASHOUT_SCHEMAS
    assert "long_short_ratio_clean" in WASHOUT_SCHEMAS

    # 正常数据 → 通过
    good_cvd = pd.DataFrame([
        {"timestamp": "2026-01-01T00:00:00Z", "symbol": "BTC",
         "cvd_value": 100.0, "buy_volume": 500.0, "sell_volume": 400.0},
    ])
    assert validate_schema(good_cvd, "cvd_clean") is True

    # 缺字段 → 拦截
    bad_cvd = pd.DataFrame([
        {"timestamp": "2026-01-01T00:00:00Z", "symbol": "BTC",
         "cvd_value": 100.0},  # 缺 buy_volume/sell_volume
    ])
    assert validate_schema(bad_cvd, "cvd_clean") is False

    # 类型错误 (cvd_value 是字符串而非数值) → 拦截
    wrong_type = pd.DataFrame([
        {"timestamp": "2026-01-01T00:00:00Z", "symbol": "BTC",
         "cvd_value": "not_a_number", "buy_volume": 500.0, "sell_volume": 400.0},
    ])
    assert validate_schema(wrong_type, "cvd_clean") is False


# ============================================================
# SilverLayerCleaner 集成测试
# ============================================================
def test_silver_layer_cleaner_full_pipeline():
    """SilverLayerCleaner 完整清洗链路: 去重→3σ→IQR→ATR。"""
    cleaner = SilverLayerCleaner()
    np.random.seed(42)
    normal = np.random.normal(100, 5, 30)
    df = pd.DataFrame({
        "timestamp": [f"2026-01-01T00:{i:02d}:00Z" for i in range(30)],
        "symbol": ["BTC"] * 30,
        "cvd_value": normal.tolist(),
    })
    # 添加重复行
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    # 添加异常值
    df.loc[len(df)] = ["2026-01-01T00:31:00Z", "BTC", 999.0]

    result = cleaner.clean(df, value_field="cvd_value")
    # 去重 + 异常值过滤后，数据更干净
    assert len(result) <= 31  # 至少去除了重复行和异常值
    assert 999.0 not in result["cvd_value"].values
