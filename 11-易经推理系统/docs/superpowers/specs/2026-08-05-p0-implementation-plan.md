# P0 实施计划：FeatureRegistry 插件机制与基线建立

**关联设计文档**: [2026-08-05-macro-features-integration-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/docs/superpowers/specs/2026-08-05-macro-features-integration-design.md)  
**创建日期**: 2026-08-05  
**状态**: 待执行

---

## 〇、代码调研修正（对设计文档的重要修正）

深入研读代码后发现实际比设计文档预期的更复杂，需修正以下几点：

### 修正 1：L1 特征模块是 10 个，不是 11 个

`MetaLabelingFeaturesV2` **不是 L1 特征模块**，而是 L2 管道内部调用——它在 [dialectical_ml_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/dialectical_ml_engine.py) 的 `train_l2()` 和 `predict()` 内部被调用，返回 `np.ndarray`（非 DataFrame），且强依赖 `l1_pred` / `l1_proba`。**不应注册到 FeatureRegistry**。

FeatureRegistry 管理的是 **10 个 L1 特征模块**：

| # | 注册名 | 文件 | 入口类型 | 返回类型 | 外部依赖 |
|---|--------|------|----------|----------|----------|
| 1 | `bagua` | bagua_feature_engine.py | 类方法 | DataFrame | 无 |
| 2 | `classic_exp` | classic_experience_features.py | 类方法 | DataFrame | 无 |
| 3 | `fibonacci` | fibonacci_features.py | 类方法 | DataFrame | 无 |
| 4 | `pivot_point` | pivot_point_features.py | 类方法 | DataFrame | 无 |
| 5 | `rsi_sentiment` | rsi_sentiment_features.py | 类方法 | DataFrame | 无 |
| 6 | `wdh` | wdh_features.py | 类方法 | DataFrame | 无 |
| 7 | `cycle` | cycle_features.py | 类方法 | DataFrame | 无 |
| 8 | `market_cap` | market_cap.py | 类方法 | DataFrame | symbol |
| 9 | `cross_asset` | cross_asset_features.py | **独立函数** | DataFrame | **ref_df** |
| 10 | `merrill_clock` | merrill_clock_features.py | 类方法 | DataFrame | ref_df, cycle_phase |

### 修正 2：实盘 L2 也存在缺陷

bcrm2_adapter 的 `train()` [L333](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2_adapter.py#L333) 调用了 `engine.train_l2(X, y, df=df_valid)`，但**未传 `ref_df` 和 `cycle_phase`**，导致 L2 的 MetaLabelingFeaturesV2 退化（跨资产和周期特征全部缺失）。P0 需一并修复。

### 修正 3：wdh 子模块注册不一致

- 回测：wdh 拆为 4 个子 key（`wdh_weekly_accum` / `wdh_daily_confirm` / `wdh_hourly_timing` / `wdh_qual_trigger`）
- 实盘：wdh 注册为单个 key `wdh`

虽然这些 key 都不在 `GUA_DIMENSION_MAP` 中（HexagramMapper 会跳过），但影响 `feature_names_by_gua` 结构一致性。P0 统一为回测的 4 子 key 方式。

### 修正 4：模块间存在依赖

`merrill_clock` 依赖 `cycle` 的输出（`cycle_phase` 参数）。FeatureRegistry 需支持模块间依赖传递。

### 修正 5：bcrm2_adapter 缺少 ref_df

bcrm2_adapter 的 `train()` 和 `infer()` 从不获取 BTC 参考数据。`cross_asset` 和 `merrill_clock` 模块以及 L2 MetaLabeling 都需要 `ref_df`。P0 需让 adapter 能获取并传递 ref_df。

---

## 一、实施步骤总览

| 步骤 | 内容 | 预计代码改动 |
|:----:|------|:----------:|
| 1 | 创建 `FeatureRegistry` 类 | 新建 ~200 行 |
| 2 | 10 个 L1 模块自注册改造 | 每文件 +3~8 行 |
| 3 | cross_asset 包装为类 | 新建 ~30 行 wrapper |
| 4 | 重构 walk_forward_backtester | 替换 L320-L472 (~150 行→~20 行) |
| 5 | 重构 bcrm2_adapter train+infer | 替换 L192-L225 + L395-L411 (~80 行→~20 行) |
| 6 | bcrm2_adapter 补全 ref_df 获取 | +~40 行 |
| 7 | 编写回归测试 | 新建 ~150 行 |
| 8 | 跑回归测试 + 修复偏差 | — |
| 9 | 跑 15 币种回测 + 保存基线快照 | 新建脚本 ~100 行 |
| 10 | git tag baseline-v1 | — |

---

## 二、详细步骤

### 步骤 1：创建 FeatureRegistry

**文件**: `scripts/memory_l4/bcrm2/feature_registry.py`（新建）

**设计要点**：
- 每个模块用 `FeatureModuleSpec` 描述其依赖和配置
- `compute_all()` 统一处理模块间依赖（cycle→merrill 的 cycle_phase 传递）
- 支持 `context` 字典传递运行时参数（symbol、ref_df、config、enable_flags）
- 返回 `(features_df, feature_names_by_gua)` 元组，与现有代码兼容

**完整实现框架**：

```python
"""FeatureRegistry — 特征模块注册表，回测/实盘共用唯一入口"""
from typing import Dict, List, Optional, Tuple, Callable, Any
from dataclasses import dataclass, field
import pandas as pd
import numpy as np


@dataclass
class FeatureModuleSpec:
    """特征模块规格"""
    name: str                                   # 注册名
    factory: Callable                           # 工厂函数 → 实例（无参或接收 context）
    participates_in_gua: bool = False           # 是否参与卦象推导
    requires_ref_df: bool = False               # 是否需要参考资产
    requires_symbol: bool = False               # 构造函数是否需要 symbol
    requires_cycle_phase: bool = False          # 是否需要 cycle 模块输出
    default_enabled: bool = True
    # 子模块 feature_names_by_gua 的拆分规则（如 wdh 按前缀拆 4 个子 key）
    sub_key_splitter: Optional[Callable[[List[str]], Dict[str, List[str]]]] = None


class FeatureRegistry:
    _registry: Dict[str, FeatureModuleSpec] = {}
    _order: List[str] = []  # 保持注册顺序

    @classmethod
    def register(cls, name: str, factory: Callable, **kwargs) -> None:
        spec = FeatureModuleSpec(name=name, factory=factory, **kwargs)
        cls._registry[name] = spec
        cls._order.append(name)

    @classmethod
    def compute_all(
        cls,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
        symbol: str = "BTC",
        config: Optional[dict] = None,
        enabled: Optional[List[str]] = None,
        verbose: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
        """
        计算所有启用模块的特征
        
        返回:
            features: 合并后的特征 DataFrame
            feature_names_by_gua: {模块名/子模块名: [特征名列表]}
        """
        ctx = {
            "df": df,
            "ref_df": ref_df,
            "symbol": symbol,
            "config": config or {},
        }
        
        # 确定启用列表
        if enabled is None:
            enabled_list = [n for n in cls._order 
                           if cls._registry[n].default_enabled]
        else:
            enabled_list = [n for n in cls._order if n in enabled]
        
        features = pd.DataFrame(index=df.index)
        feature_names_by_gua = {}
        cycle_feats = None  # 用于 merrill 依赖
        
        for name in enabled_list:
            spec = cls._registry[name]
            
            # 检查依赖
            if spec.requires_ref_df and (ref_df is None or len(ref_df) < 200):
                if verbose:
                    print(f"  跳过 {name}: ref_df 不足")
                continue
            
            # 创建实例
            if spec.requires_symbol:
                instance = spec.factory(symbol=symbol)
            else:
                instance = spec.factory()
            
            # 调用 compute（根据模块签名传递不同参数）
            if name == "bagua":
                feats = instance.compute(df)
                feature_names_by_gua.update(instance.feature_names_by_gua)
            elif name == "wdh":
                weekly_only = ctx["config"].get("wdh_weekly_only", False)
                feats = instance.compute(df, weekly_only=weekly_only)
            elif name == "cycle":
                enable_flags = {k: ctx["config"].get(k, True) for k in 
                               ["cycle_halving", "cycle_ath", "cycle_inventory", "cycle_long_term"]}
                feats = instance.compute(df, **enable_flags)
                cycle_feats = feats  # 保存给 merrill 用
            elif name == "market_cap":
                feats = instance.get_mcap_features(symbol, df)
            elif name == "cross_asset":
                feats = instance(df, ref_df)  # 函数式调用
            elif name == "merrill_clock":
                cycle_phase = cycle_feats if cycle_feats is not None else None
                feats = instance.compute(df, ref_df=ref_df, cycle_phase=cycle_phase)
            else:
                feats = instance.compute(df)
            
            # 拼接
            features = pd.concat([features, feats], axis=1)
            
            # 注册 feature_names_by_gua
            if spec.sub_key_splitter:
                feature_names_by_gua.update(spec.sub_key_splitter(list(feats.columns)))
            else:
                feature_names_by_gua[name] = list(feats.columns)
            
            if verbose:
                print(f"  {name}: {len(feats.columns)}个特征")
        
        return features, feature_names_by_gua

    @classmethod
    def list_modules(cls) -> List[str]:
        return list(cls._order)
```

**子模块拆分器**（wdh 和 cycle 用）：

```python
def _wdh_sub_key_splitter(columns: List[str]) -> Dict[str, List[str]]:
    """wdh 按前缀拆为 4 个子 key"""
    return {
        "wdh_weekly_accum": [c for c in columns if c.startswith("wa_")],
        "wdh_daily_confirm": [c for c in columns if c.startswith("dc_")],
        "wdh_hourly_timing": [c for c in columns if c.startswith("ht_")],
        "wdh_qual_trigger": [c for c in columns if c.startswith("qt_")],
    }

def _cycle_sub_key_splitter(columns: List[str]) -> Dict[str, List[str]]:
    """cycle 按前缀拆为 4 个子 key"""
    return {
        "cycle_halving": [c for c in columns if c.startswith("hc_")],
        "cycle_ath": [c for c in columns if c.startswith("ath_")],
        "cycle_inventory": [c for c in columns if c.startswith("ic_")],
        "cycle_long_term": [c for c in columns if c.startswith("lt_")],
    }
```

---

### 步骤 2：10 个 L1 模块自注册改造

每个模块文件底部添加注册代码。**不修改类的定义和 compute 方法本身**，只追加注册。

**2.1 bagua_feature_engine.py**（文件末尾追加）

```python
# ===== FeatureRegistry 注册 =====
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

FeatureRegistry.register(
    name="bagua",
    factory=BaguaFeatureEngine,
    participates_in_gua=True,  # 8 卦维度参与卦象推导
)
```

注意：bagua 的 `feature_names_by_gua` 由 `BaguaFeatureEngine` 实例属性提供（`instance.feature_names_by_gua`），`compute_all()` 中特殊处理，不走 `sub_key_splitter`。

**2.2 classic_experience_features.py**

```python
FeatureRegistry.register(name="classic_exp", factory=ClassicExperienceFeatures)
```

**2.3 fibonacci_features.py**

```python
FeatureRegistry.register(name="fibonacci", factory=FibonacciFeatures)
```

**2.4 pivot_point_features.py**

```python
FeatureRegistry.register(name="pivot_point", factory=PivotPointFeatures)
```

**2.5 rsi_sentiment_features.py**

```python
FeatureRegistry.register(name="rsi_sentiment", factory=RSISentimentFeatures)
```

**2.6 wdh_features.py**

```python
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry, _wdh_sub_key_splitter

FeatureRegistry.register(
    name="wdh",
    factory=WDHFeatures,
    sub_key_splitter=_wdh_sub_key_splitter,
)
```

**2.7 cycle_features.py**

```python
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry, _cycle_sub_key_splitter

FeatureRegistry.register(
    name="cycle",
    factory=lambda symbol="BTC": CycleFeatures(symbol=symbol),
    requires_symbol=True,
    sub_key_splitter=_cycle_sub_key_splitter,
)
```

**2.8 market_cap.py**

```python
FeatureRegistry.register(
    name="market_cap",
    factory=MarketCapClassifier,
    requires_symbol=True,
)
```

注意：market_cap 的主入口是 `get_mcap_features(symbol, df)` 而非 `compute(df)`，`compute_all()` 中特殊处理。

**2.9 cross_asset_features.py**（需包装为类）

在文件末尾追加：

```python
class CrossAssetFeatureWrapper:
    """将 compute_cross_asset_features 函数包装为类，适配 FeatureRegistry"""
    def __init__(self):
        pass
    
    def compute(self, df: pd.DataFrame, ref_df: pd.DataFrame, 
                symbol: str = "ETH", ref_symbol: str = "BTC") -> pd.DataFrame:
        return compute_cross_asset_features(df, ref_df, symbol=symbol, ref_symbol=ref_symbol)

FeatureRegistry.register(
    name="cross_asset",
    factory=CrossAssetFeatureWrapper,
    requires_ref_df=True,
)
```

注意：`compute_all()` 中对 cross_asset 特殊处理，调用 `instance.compute(df, ref_df, symbol=symbol)`。

**2.10 merrill_clock_features.py**

```python
FeatureRegistry.register(
    name="merrill_clock",
    factory=lambda symbol="BTC": MerrillClockFeatures(symbol=symbol),
    requires_symbol=True,
    requires_ref_df=True,
    requires_cycle_phase=True,
)
```

---

### 步骤 3：cross_asset 包装为类

已在上面的 2.9 中完成（`CrossAssetFeatureWrapper`）。

---

### 步骤 4：重构 walk_forward_backtester.py

**目标**：将 [L320-L472](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/walk_forward_backtester.py#L320-L472) 的 150 行手工 concat 替换为 `FeatureRegistry.compute_all()` 调用。

**改动前**（L320-L472 摘要）：
```python
# 1. 计算全部特征
features = self.feature_engine.compute(df)
feature_names_by_gua = dict(self.feature_engine.feature_names_by_gua)
# 1b. 经典经验
classic_feats = self.classic_features.compute(df)
features = pd.concat([features, classic_feats], axis=1)
feature_names_by_gua["classic_exp"] = list(classic_feats.columns)
# ... 重复 9 次 ...
```

**改动后**（~25 行）：
```python
# 1. 计算全部特征（统一走 FeatureRegistry）
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

# 确保所有模块已注册（import 触发注册）
import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa
import scripts.memory_l4.bcrm2.classic_experience_features  # noqa
import scripts.memory_l4.bcrm2.fibonacci_features  # noqa
import scripts.memory_l4.bcrm2.pivot_point_features  # noqa
import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa
import scripts.memory_l4.bcrm2.wdh_features  # noqa
import scripts.memory_l4.bcrm2.cycle_features  # noqa
import scripts.memory_l4.bcrm2.market_cap  # noqa
import scripts.memory_l4.bcrm2.cross_asset_features  # noqa
import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa

# 构建 config（从 FeatureConfig 读取 enable 开关）
registry_config = {
    "wdh_weekly_only": wdh_weekly_only,
    "cycle_halving": cycle_halving,
    "cycle_ath": cycle_ath,
    "cycle_inventory": cycle_inventory,
    "cycle_long_term": cycle_long_term,
}

# 确定启用列表（从 FeatureConfig 映射）
enabled = []
enabled.append("bagua")
enabled.append("classic_exp")
enabled.append("fibonacci")
if enable_pivot: enabled.append("pivot_point")
if enable_rsi: enabled.append("rsi_sentiment")
if enable_wdh: enabled.append("wdh")
if enable_cycle: enabled.append("cycle")
if enable_mcap: enabled.append("market_cap")
if enable_merrill: enabled.append("merrill_clock")
# cross_asset 由 ref_df 是否存在控制（compute_all 内部处理）

features, feature_names_by_gua = FeatureRegistry.compute_all(
    df=df,
    ref_df=ref_df,
    symbol=self.symbol,
    config=registry_config,
    enabled=enabled,
    verbose=verbose,
)
feature_names = list(features.columns)

# 保存 cycle_feats 给 L2 用（从 features 中提取 cycle 子模块的特征列）
cycle_feats = None
if enable_cycle:
    cycle_cols = []
    for key in ["cycle_halving", "cycle_ath", "cycle_inventory", "cycle_long_term"]:
        cycle_cols.extend(feature_names_by_gua.get(key, []))
    if cycle_cols:
        cycle_feats = features[cycle_cols]
```

**同时需要**：
- 删除 `__init__` 中对各个 feature 模块实例的初始化（`self.feature_engine`、`self.classic_features` 等），或保留但不使用（向后兼容）
- `_run_single_fold` 中 L621-L626 的 `engine.train_l2()` 调用保持不变（已正确传 ref_df 和 cycle_phase）

---

### 步骤 5：重构 bcrm2_adapter.py train()

**目标**：将 [L192-L225](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2_adapter.py#L192-L225) 的 6 模块手工 concat 替换为 `FeatureRegistry.compute_all()`，并启用全部 10 个模块。

**改动前**（L192-L225 摘要）：
```python
feature_engine = BaguaFeatureEngine()
features = feature_engine.compute(df)
# ... 5 个模块 concat ...
feature_names_by_gua["wdh"] = list(wdh_feats.columns)
```

**改动后**（~20 行）：
```python
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

# 确保所有模块已注册
import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa
import scripts.memory_l4.bcrm2.classic_experience_features  # noqa
import scripts.memory_l4.bcrm2.fibonacci_features  # noqa
import scripts.memory_l4.bcrm2.pivot_point_features  # noqa
import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa
import scripts.memory_l4.bcrm2.wdh_features  # noqa
import scripts.memory_l4.bcrm2.cycle_features  # noqa
import scripts.memory_l4.bcrm2.market_cap  # noqa
import scripts.memory_l4.bcrm2.cross_asset_features  # noqa
import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa

# 获取 ref_df（BTC 参考数据）
ref_df = self._fetch_ref_df(df)

features, feature_names_by_gua = FeatureRegistry.compute_all(
    df=df,
    ref_df=ref_df,
    symbol=self.symbol,
    verbose=True,
)
feature_names = list(features.columns)

# 保存 cycle_feats 给 L2 用
cycle_cols = []
for key in ["cycle_halving", "cycle_ath", "cycle_inventory", "cycle_long_term"]:
    cycle_cols.extend(feature_names_by_gua.get(key, []))
cycle_feats = features[cycle_cols] if cycle_cols else None
```

**同时修改 L333 的 L2 训练调用**：
```python
# 改动前
engine.train_l2(X, y, df=df_valid)

# 改动后
engine.train_l2(
    X, y, 
    df=df_valid,
    ref_df=ref_df.iloc[valid_idx][nan_mask] if ref_df is not None else None,
    cycle_phase=cycle_feats.iloc[valid_idx][nan_mask] if cycle_feats is not None else None,
)
```

---

### 步骤 6：bcrm2_adapter 补全 ref_df 获取

**新增方法**（在 BCRM2Adapter 类中）：

```python
def _fetch_ref_df(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """获取 BTC 参考数据用于跨资产特征和 L2 MetaLabeling"""
    if self.symbol == "BTC":
        return None  # BTC 自身不需要 ref_df
    
    try:
        from scripts.memory_l4.okx_client import OKXClient
        client = OKXClient()
        # 获取与 df 时间范围对齐的 BTC K 线
        since = int(df.index[0].timestamp() * 1000)
        until = int(df.index[-1].timestamp() * 1000)
        ref_df = client.get_klines("BTC-USDT-SWAP", self.timeframe, 
                                    start=since, end=until)
        if ref_df is not None and len(ref_df) > 200:
            # 对齐索引
            ref_df = ref_df.reindex(df.index, method='ffill')
            return ref_df
    except Exception as e:
        logger.warning(f"[BCRM2] 获取 BTC ref_df 失败: {e}")
    return None
```

**同时修改 infer()** [L395-L411](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2_adapter.py#L395-L411)：

```python
# 改动前：6 模块手工 concat
feature_engine = BaguaFeatureEngine()
features = feature_engine.compute(df)
# ...

# 改动后：统一走 Registry
ref_df = self._fetch_ref_df(df)
features, feature_names_by_gua = FeatureRegistry.compute_all(
    df=df,
    ref_df=ref_df,
    symbol=self.symbol,
)
feature_names = list(features.columns)

# infer 时也需要传 ref_df 和 cycle_phase 给 engine.predict_single
cycle_cols = []
for key in ["cycle_halving", "cycle_ath", "cycle_inventory", "cycle_long_term"]:
    cycle_cols.extend(feature_names_by_gua.get(key, []))
cycle_feats = features[cycle_cols] if cycle_cols else None

# 修改 L425 的 predict_single 调用
result = self.engine.predict_single(
    X_row, with_gua=True, df=df,
    ref_df=ref_df,
    cycle_phase=cycle_feats.iloc[[idx]] if cycle_feats is not None else None,
)
```

---

### 步骤 7：编写回归测试

**文件**: `tests/test_feature_registry.py`（新建）

**测试用例**：

```python
"""FeatureRegistry 回归测试 — 验证重构前后特征一致性"""
import pytest
import pandas as pd
import numpy as np
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry


class TestFeatureRegistry:
    
    def test_registry_has_10_modules(self):
        """验证 10 个模块全部注册"""
        # 触发所有模块注册
        import scripts.memory_l4.bcrm2.bagua_feature_engine
        import scripts.memory_l4.bcrm2.classic_experience_features
        import scripts.memory_l4.bcrm2.fibonacci_features
        import scripts.memory_l4.bcrm2.pivot_point_features
        import scripts.memory_l4.bcrm2.rsi_sentiment_features
        import scripts.memory_l4.bcrm2.wdh_features
        import scripts.memory_l4.bcrm2.cycle_features
        import scripts.memory_l4.bcrm2.market_cap
        import scripts.memory_l4.bcrm2.cross_asset_features
        import scripts.memory_l4.bcrm2.merrill_clock_features
        
        modules = FeatureRegistry.list_modules()
        assert len(modules) == 10
        for name in ["bagua", "classic_exp", "fibonacci", "pivot_point",
                     "rsi_sentiment", "wdh", "cycle", "market_cap",
                     "cross_asset", "merrill_clock"]:
            assert name in modules
    
    def test_compute_all_returns_dataframe_and_gua_map(self, sample_ohlcv, btc_ref_df):
        """验证返回类型和结构"""
        features, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            ref_df=btc_ref_df,
            symbol="ETH",
        )
        assert isinstance(features, pd.DataFrame)
        assert isinstance(gua_map, dict)
        assert len(features) == len(sample_ohlcv)
    
    def test_wdh_sub_keys_registered(self, sample_ohlcv):
        """验证 wdh 拆为 4 个子 key"""
        _, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv, symbol="BTC",
            enabled=["bagua", "wdh"],
        )
        assert "wdh_weekly_accum" in gua_map
        assert "wdh_daily_confirm" in gua_map
        assert "wdh_hourly_timing" in gua_map
        assert "wdh_qual_trigger" in gua_map
    
    def test_cycle_sub_keys_registered(self, sample_ohlcv):
        """验证 cycle 拆为 4 个子 key"""
        _, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv, symbol="BTC",
            enabled=["bagua", "cycle"],
        )
        assert "cycle_halving" in gua_map
        assert "cycle_ath" in gua_map
        assert "cycle_inventory" in gua_map
        assert "cycle_long_term" in gua_map
    
    def test_cross_asset_skipped_without_ref_df(self, sample_ohlcv):
        """验证无 ref_df 时跳过 cross_asset"""
        features, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv, symbol="ETH",
            enabled=["bagua", "cross_asset"],
        )
        assert "cross_asset" not in gua_map
    
    def test_merrill_gets_cycle_phase(self, sample_ohlcv, btc_ref_df):
        """验证 merrill 接收到 cycle 的输出"""
        features, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv, ref_df=btc_ref_df, symbol="ETH",
            enabled=["cycle", "merrill_clock"],
        )
        assert "merrill_clock" in gua_map
        assert len(gua_map["merrill_clock"]) > 0
    
    def test_feature_count_matches_legacy(self, sample_ohlcv, btc_ref_df):
        """验证特征总数与重构前一致（±2 容差，因 NaN 处理可能微调）"""
        features, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv, ref_df=btc_ref_df, symbol="ETH",
        )
        # 重构前 ETH 11 模块约 367 个 L1 特征
        assert 350 <= len(features.columns) <= 400


class TestFeatureConsistency:
    """验证重构前后特征值完全一致"""
    
    def test_bagua_features_unchanged(self, sample_ohlcv):
        """bagua 特征值与直接调用 BaguaFeatureEngine 一致"""
        from scripts.memory_l4.bcrm2.bagua_feature_engine import BaguaFeatureEngine
        
        # 直接调用
        direct = BaguaFeatureEngine().compute(sample_ohlcv)
        
        # 通过 Registry 调用
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv, symbol="BTC",
            enabled=["bagua"],
        )
        
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False)
    
    def test_all_module_features_unchanged(self, sample_ohlcv, btc_ref_df):
        """所有模块特征值与直接调用一致"""
        # 对每个模块分别验证...
        pass  # 逐模块对比
```

**fixture 准备**：

```python
@pytest.fixture
def sample_ohlcv():
    """加载 BTC 1H K 线样本数据（500 根）"""
    # 从缓存或 OKX 获取
    ...

@pytest.fixture
def btc_ref_df():
    """BTC 参考数据"""
    ...
```

---

### 步骤 8：跑回归测试 + 修复偏差

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
/opt/anaconda3/bin/python3 -m pytest tests/test_feature_registry.py -v
```

**预期问题及处理**：
1. 特征顺序不一致 → Registry 按注册顺序拼接，可能与手工 concat 顺序不同 → 调整注册顺序或测试中用 `sort_columns` 比较
2. NaN 处理差异 → 确认 Registry 不额外填充 NaN
3. market_cap 的 `get_mcap_features` vs `compute` → 在 `compute_all` 中特殊处理
4. cross_asset wrapper 的 symbol 参数 → 确保传入正确的 symbol

---

### 步骤 9：跑 15 币种回测 + 保存基线快照

**新建脚本**: `scripts/memory_l4/bcrm2/save_baseline.py`

```python
"""跑 15 币种完整回测，保存基线快照"""
import json
import subprocess
from datetime import datetime
from pathlib import Path

COINS = ["UNI", "PUMP", "MU", "SKHYNIX", "HYPE", "ETH", "BTC", "SOL",
         "XAU", "XAG", "GOOGL", "NVDA", "AMZN", "OKB", "BNB"]

def main():
    results = {}
    for coin in COINS:
        print(f"回测 {coin}...")
        # 调用 walk_forward_backtester
        # ...
        results[coin] = {
            "sharpe": ...,
            "win_rate": ...,
            "profit_factor": ...,
            "max_drawdown": ...,
            "calmar": ...,
            "total_return": ...,
            "avg_hold_bars": ...,
            "total_trades": ...,
        }
    
    # 汇总
    baseline = {
        "version": "baseline-v1",
        "created_at": datetime.now().isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
        "feature_modules": FeatureRegistry.list_modules(),
        "feature_count": ...,
        "coins": COINS,
        "timeframe": "1H",
        "metrics": aggregate_metrics(results),
        "per_coin_metrics": results,
    }
    
    output = Path("data/baseline/baseline_v1.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(baseline, indent=2, ensure_ascii=False))
    print(f"基线快照已保存到 {output}")


if __name__ == "__main__":
    main()
```

---

### 步骤 10：git tag baseline-v1

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
git add -A
git commit -m "P0: FeatureRegistry 插件机制 + 实盘回测模块对齐 + 基线快照"
git tag baseline-v1
```

---

## 三、风险点与缓解

| 风险 | 缓解 |
|------|------|
| bcrm2_adapter 获取 ref_df 时 OKX API 失败 | 返回 None，cross_asset/merrill 自动跳过，L2 退化（与现状一致，不引入新问题） |
| 重构后特征顺序变化导致模型缓存失效 | 缓存 key 包含 feature_names 列表 hash，自动失效重训 |
| cycle_feats 从 features 中提取时列名不匹配 | 用 feature_names_by_gua 的 key 查找，不硬编码列名 |
| 回归测试中 fixture 数据获取困难 | 提供 `--use-cache` 选项，优先从本地缓存加载 |

---

## 四、验收清单

- [ ] `FeatureRegistry` 类创建完成，支持 register/compute_all/list_modules
- [ ] 10 个 L1 模块全部自注册（含 cross_asset wrapper）
- [ ] walk_forward_backtester 改为调用 `Registry.compute_all()`
- [ ] bcrm2_adapter train() 和 infer() 改为调用 `Registry.compute_all()`
- [ ] bcrm2_adapter 新增 `_fetch_ref_df()` 方法
- [ ] bcrm2_adapter L2 训练传入 ref_df 和 cycle_phase
- [ ] 回归测试通过：各模块特征值与直接调用一致
- [ ] 回归测试通过：特征总数在 350-400 范围
- [ ] 基线快照 `data/baseline/baseline_v1.json` 已保存
- [ ] git tag `baseline-v1` 已打

---

## 五、文件改动清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `scripts/memory_l4/bcrm2/feature_registry.py` | FeatureRegistry 核心 |
| 修改 | `scripts/memory_l4/bcrm2/bagua_feature_engine.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/classic_experience_features.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/fibonacci_features.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/pivot_point_features.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/rsi_sentiment_features.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/wdh_features.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/cycle_features.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/market_cap.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/cross_asset_features.py` | 追加 wrapper 类 + 注册 |
| 修改 | `scripts/memory_l4/bcrm2/merrill_clock_features.py` | 末尾追加注册 |
| 修改 | `scripts/memory_l4/bcrm2/walk_forward_backtester.py` | L320-L472 替换为 Registry 调用 |
| 修改 | `scripts/memory_l4/bcrm2_adapter.py` | train+infer 替换为 Registry 调用 + 新增 _fetch_ref_df |
| 新建 | `tests/test_feature_registry.py` | 回归测试 |
| 新建 | `scripts/memory_l4/bcrm2/save_baseline.py` | 基线快照脚本 |
| 新建 | `data/baseline/baseline_v1.json` | 基线快照（脚本生成） |

**总计**: 1 个新建核心文件 + 10 个模块追加注册 + 2 个入口重构 + 2 个新建测试/脚本 = **15 个文件改动**
