# 21-特征工程中心 — 接口规格文档

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 子系统对外接口规格，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.3

---

## 1. 接口概览

### 1.1 接口类型

| 类型 | 数量 | 说明 |
|------|------|------|
| Python API | 2 | FeaturePipeline / FeatureRegistry |
| 特征模块 | 9 | 每个模块暴露 `compute(df, **kw) -> pd.DataFrame` |
| CLI 命令 | 4 | fh list/inspect/run-sample/export-schema |

### 1.2 接口列表

| 接口 | 类型 | 签名 | 说明 |
|------|------|------|------|
| `FeaturePipeline.run` | Python | `run(set_name, df, symbol, ref_df, macro_df, y) -> FeatureVector` | 特征编排主入口 |
| `FeaturePipeline.register_module` | Python | `register_module(name, compute_fn) -> None` | 注册本地模块 |
| `FeatureRegistry.compute_all` | Python | `compute_all(df, ref_df, symbol) -> tuple` | 回测/实盘统一入口 |
| `FeatureRegistry.register` | Python | `register(name, factory, participates_in_gua) -> None` | 注册模块到全局注册表 |
| `load_default_sets` | Python | `load_default_sets(pipe) -> None` | 一键注册 9 模块 + YAML 集合 |

---

## 2. 认证方式

| 方式 | 说明 |
|------|------|
| 无需认证 | SDK 集成，直接 import |

---

## 3. 接口详情

### 3.1 FeaturePipeline（编排管道）

**模块**：`feature_hub.pipeline.feature_pipeline`

#### `FeaturePipeline.__init__`

```python
def __init__(self) -> None
```

初始化空管道，内部创建 StandardCleaningChain。

#### `register_module`

```python
def register_module(self, name: str, compute_fn: Callable[..., pd.DataFrame]) -> None
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | str | 模块名 |
| `compute_fn` | Callable | 计算函数 `compute(df, **kw) -> pd.DataFrame` |

#### `register_set`

```python
def register_set(self, set_name: str, modules: List[str]) -> None
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `set_name` | str | 集合名 |
| `modules` | List[str] | 模块名列表 |

#### `run`

```python
def run(
    self,
    set_name: str,
    df: pd.DataFrame,
    symbol: str = "",
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    y: Optional[Any] = None,
) -> FeatureVector
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `set_name` | str | 是 | 启用集合名（如 `btc_morphology_v6`） |
| `df` | pd.DataFrame | 是 | OHLCV 数据 |
| `symbol` | str | 否 | 交易标的 |
| `ref_df` | pd.DataFrame | 否 | 参考资产数据 |
| `macro_df` | pd.DataFrame | 否 | 宏观数据 |
| `y` | Any | 否 | 标签（IV 筛选用） |

**返回**：`FeatureVector(df, meta)`

**L1 fail-open**：单模块异常 → log.warning + 跳过，其他模块照常。

**L3 fail-fast**：set_name 不存在 → 抛 `FeatureSetNotFound`。

**示例**：
```python
from feature_hub.pipeline.feature_pipeline import FeaturePipeline
from feature_hub.modules.loader import load_default_sets

pipe = FeaturePipeline()
load_default_sets(pipe)

fv = pipe.run("btc_morphology_v6", df=ohlcv_df, symbol="BTC")
# fv.df 包含特征列
# fv.meta 包含元信息
```

### 3.2 FeatureRegistry（统一注册表）

**模块**：`feature_hub.hub.feature_registry`

#### `register`

```python
def register(name: str, factory: Callable, participates_in_gua: bool = False) -> None
```

在模块文件底部调用，将模块注册到全局注册表。

#### `compute_all`

```python
def compute_all(df: pd.DataFrame, ref_df: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, Dict]
```

回测/实盘共用入口，计算所有 `default_enabled=True` 的模块。

**返回**：`(features_df, feature_names_by_gua)`

### 3.3 load_default_sets（模块加载器）

**模块**：`feature_hub.modules.loader`

```python
def load_default_sets(pipe: FeaturePipeline) -> None
```

1. 注册 9 个 Native 模块（crypto_morphology/elder_ray/triple_screen_trend/classic_indicators/talib_aligned/five_domain_fc/martin_features/fundamental_ratios/yijing_cycle）
2. 从 `config/feature_sets.yaml` 加载启用集合

### 3.4 特征模块契约

每个特征模块必须实现：

```python
def compute(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """计算特征，返回带特征列的 DataFrame。"""
```

注册方式：
```python
# 方式1：通过 loader 自动注册（Native 模块）
# 方式2：通过 FeatureRegistry.register（FR 模块）
from feature_hub.hub.feature_registry import FeatureRegistry
FeatureRegistry.register("my_module", factory=MyFeatureEngine, participates_in_gua=True)
```

### 3.5 CLI 命令

**入口**：`fh` 或 `python -m feature_hub.cli.app`

| 命令 | 用法 | 说明 |
|------|------|------|
| `list` | `fh list` | 列出所有模块和启用集合 |
| `inspect` | `fh inspect --set <name>` | 检查集合的列数/模块/血缘 |
| `run-sample` | `fh run-sample --set <name> --symbol S` | 用合成 OHLCV 跑一次特征 |
| `export-schema` | `fh export-schema --set <name>` | 导出 JSON schema |

---

## 4. 错误码

| 异常 | 触发场景 |
|------|----------|
| `FeatureSetNotFound` | run() 的 set_name 不存在于已注册集合 |

**fail-open 约定**：
- 单模块 compute 异常 → 跳过该模块，不中断管道
- 模块 import 失败 → log.warning，不注册该模块

---

## 5. 版本管理

### 5.1 版本策略

- 特征集合通过版本号区分（btc_morphology_v1~v6）
- 新增集合不影响旧集合
- 模块 compute 接口稳定（df → df）

### 5.2 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-09-30 | 初始接口规格（FeaturePipeline + FeatureRegistry + 9 模块 + CLI） |

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
