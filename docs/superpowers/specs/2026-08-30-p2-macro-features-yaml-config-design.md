# P2 宏观特征 YAML 配置化设计

> **Spec ID**: 2026-08-30-p2-macro-features-yaml-config
> **日期**: 2026-08-30
> **状态**: Approved (用户逐节批准 §1-§3)
> **前置**: P1 FinBERT 双引擎升级完工（84 TC GREEN + Shadow 生产验证 Δdao=+0.034）

---

## §1 背景与目标

### 现状

`MacroFeatures.FEATURE_TO_DIM` 在 `scripts/memory_l4/bcrm2/macro_features.py:L55-92` 硬编码 37 个特征→8 维度映射。修改特征列表需改代码+重启进程，无法在回测实验中快速切换特征子集。

`build_macro_feat_config()` 在 4 个文件中重复出现（macro_feature_select_v2 / macro_feature_optimize_v3 / macro_feature_optimize_v4 / macro_feature_validate_v2），均通过 `MacroFeatures.ALL_FEATURES` 引用特征列表。

### 目标

将 `FEATURE_TO_DIM` 映射抽取为 YAML 配置文件，支持初始化加载 + `reload()` 手动刷新，保留硬编码作为 FAIL-OPEN fallback。

### 四项硬约束

1. **下游代码零改动**：`MacroFeatures.FEATURE_TO_DIM` / `MacroFeatures.ALL_FEATURES` 类变量引用方式不变
2. **FAIL-OPEN 铁律**：YAML 文件缺失/解析失败/格式错误 → fallback 到 `_DEFAULT_FEATURE_TO_DIM` 硬编码默认值，不抛异常
3. **不改变计算逻辑**：`compute()` 中 `_feat_enabled()` 两级开关行为一字不动
4. **字节等价**：YAML 内容与现有硬编码映射完全一致时，所有下游输出字节等价

---

## §2 架构 + 接口契约

### 文件清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `configs/macro_features.yaml` | 新建 | 37 个特征→8 维度映射的 YAML 声明 |
| `scripts/memory_l4/bcrm2/macro_features.py` | 修改 | 加载逻辑 + reload() + fallback |

### YAML 结构

```yaml
# 宏观特征 → 维度映射配置
# 修改后调用 MacroFeatures.reload() 或重启进程生效
# FAIL-OPEN：本文件缺失/解析失败 → 使用代码内 _DEFAULT_FEATURE_TO_DIM 硬编码默认值

features:
  # ── 情绪 (sentiment) ──
  fgi_zscore: sentiment
  fgi_extreme_fear: sentiment
  fgi_extreme_greed: sentiment
  fgi_divergence: sentiment
  fgi_trend_7d: sentiment
  # ── 资金/衍生品 (funding) ──
  funding_rate_zscore: funding
  funding_extreme_positive: funding
  funding_extreme_negative: funding
  oi_change_rate: funding
  funding_divergence: funding
  # ── 流动性 (liquidity) ──
  stablecoin_growth: liquidity
  liquidity_expanding: liquidity
  liquidity_contracting: liquidity
  tvl_change_7d: liquidity
  # ── 链上 (onchain) ──
  hash_rate_trend: onchain
  miner_accumulation: onchain
  miners_revenue_zscore: onchain
  # ── 聪明钱/社交 (smart_money) ──
  smart_money_direction: smart_money
  smart_money_divergence: smart_money
  social_hype_zscore: smart_money
  hype_extreme: smart_money
  # ── 估值 (valuation) ──
  market_cap_rank: valuation
  ath_drop_pct: valuation
  undervalued: valuation
  # ── 宏观金融扩展 (macro_finance_ext) ──
  vix_zone: macro_finance_ext
  us_macro_regime: macro_finance_ext
  sp500_7d_break: macro_finance_ext
  dxy_strength: macro_finance_ext
  btc_etf_flow_3d: macro_finance_ext
  rwa_liquidity_pulse: macro_finance_ext
  treasury_balance_delta: macro_finance_ext
  stablecoin_minus_rwa: macro_finance_ext
  # ── BTC 链上扩展 (btc_onchain_ext) ──
  whale_netflow_pulse: btc_onchain_ext
  exchange_btc_30d: btc_onchain_ext
  defi_breadth: btc_onchain_ext
  oi_liq_pressure: btc_onchain_ext
  btc_dom_delta: btc_onchain_ext
```

### macro_features.py 改动点（3 处）

**改动点 1 — 模块级重命名**：

原 `FEATURE_TO_DIM` 重命名为 `_DEFAULT_FEATURE_TO_DIM`（硬编码 fallback 保留，内容一字不动）。

**改动点 2 — 模块级路径变量 + 加载函数**：

新增模块级变量 `_YAML_PATH`（可被 TC monkeypatch）和 `_load_yaml_config()` 函数。

**加载顺序**：模块 import 时先定义 `_DEFAULT_FEATURE_TO_DIM` → 定义 `class MacroFeatures` → 调用 `_load_yaml_config()` 覆盖类变量。

```python
# ── 模块级 YAML 路径（可被 TC monkeypatch 覆盖）──
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))       # bcrm2/
_l4   = _os.path.dirname(_here)                            # memory_l4/
_scripts = _os.path.dirname(_l4)                           # scripts/
_ROOT = _os.path.dirname(_scripts)                         # 11-易经推理系统/
_YAML_PATH = _os.path.join(_ROOT, "configs", "macro_features.yaml")

# ── 硬编码默认值（FAIL-OPEN fallback）──
_DEFAULT_FEATURE_TO_DIM: Dict[str, str] = {
    # ... 原 FEATURE_TO_DIM 内容一字不动 ...
}

class MacroFeatures:
    FEATURE_TO_DIM = dict(_DEFAULT_FEATURE_TO_DIM)         # 初始=默认值
    ALL_FEATURES = list(FEATURE_TO_DIM.keys())
    REQUIRED_COLS = { ... }                                  # 不变
    # ... 原类体不变 ...
    
    @classmethod
    def reload(cls) -> bool:
        """重新从 YAML 加载特征→维度映射。返回 True=YAML 成功，False=fallback 默认。"""
        return _load_yaml_config()


def _load_yaml_config() -> bool:
    """从 _YAML_PATH 加载特征→维度映射。
    
    FAIL-OPEN：文件缺失/解析失败 → 返回 False，使用 _DEFAULT_FEATURE_TO_DIM。
    TC 可 monkeypatch macro_features._YAML_PATH 指向临时文件。
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        import yaml
        with open(_YAML_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"YAML root is {type(raw).__name__}, expected dict")
        features = raw.get("features")
        if not isinstance(features, dict):
            raise ValueError(f"'features' key is {type(features).__name__}, expected dict")
        
        new_map: Dict[str, str] = {}
        for k, v in features.items():
            if not isinstance(k, str) or not isinstance(v, str):
                logger.warning("macro_features.yaml bad entry: %r=%r, skipped", k, v)
                continue
            new_map[k] = v
        
        if not new_map:
            raise ValueError("YAML loaded but features dict is empty")
        
        MacroFeatures.FEATURE_TO_DIM = new_map
        MacroFeatures.ALL_FEATURES = list(new_map.keys())
        logger.info("macro_features.yaml loaded %d features", len(new_map))
        return True
        
    except FileNotFoundError:
        logger.warning("macro_features.yaml not found at %s, using defaults", _YAML_PATH)
    except Exception as e:
        logger.warning("macro_features.yaml parse error: %s, using defaults", e)
    
    # Fallback：用硬编码默认值
    MacroFeatures.FEATURE_TO_DIM = dict(_DEFAULT_FEATURE_TO_DIM)
    MacroFeatures.ALL_FEATURES = list(_DEFAULT_FEATURE_TO_DIM.keys())
    return False


# ── 模块 import 时自动加载一次（类定义 + 函数定义后）──
_load_yaml_config()
```

**改动点 3 — 类方法 reload()**：

```python
class MacroFeatures:
    # ... 原有类体不变 ...
    
    @classmethod
    def reload(cls) -> bool:
        """重新从 YAML 加载特征→维度映射。
        
        Returns:
            True = YAML 成功加载；False = fallback 到默认值
        """
        return _load_yaml_config()
```

### 接口契约不变

| 接口 | 类型 | 说明 |
|---|---|---|
| `MacroFeatures.FEATURE_TO_DIM` | `Dict[str, str]` 类变量 | 下游引用方式不变（`MacroFeatures.FEATURE_TO_DIM` 或实例 `self.FEATURE_TO_DIM`） |
| `MacroFeatures.ALL_FEATURES` | `List[str]` 类变量 | 自动从 FEATURE_TO_DIM 重建 |
| `MacroFeatures.REQUIRED_COLS` | `set` 类变量 | 不变 |
| `MacroFeatures.compute()` | 方法 | 行为不变 |
| `MacroFeatures.reload()` | `@classmethod` 新增 | 返回 bool，手动刷新配置 |

---

## §3 错误处理 + 字节等价 + 测试清单

### FAIL-OPEN 错误矩阵（3 层防护）

| 层级 | 触发条件 | 行为 | 日志 |
|---|---|---|---|
| L0 | YAML 文件不存在 | 用 `_DEFAULT_FEATURE_TO_DIM` | `logger.warning("not found, using defaults")` |
| L1 | YAML 语法错误 / 非字典 / features key 缺失 | 用 `_DEFAULT_FEATURE_TO_DIM` | `logger.warning("parse error: {e}, using defaults")` |
| L2 | YAML 条目 key/value 非 str | 跳过该条，其余正常加载 | `logger.warning("bad entry: {k}={v}, skipped")` |
| OK | YAML 正常加载 | 覆盖 `FEATURE_TO_DIM` | `logger.info("loaded {n} features from yaml")` |

### 字节等价保证

- YAML 内容与 `_DEFAULT_FEATURE_TO_DIM` 完全一致时 → `FEATURE_TO_DIM` 字典 key/value/顺序全等 → 下游 `ALL_FEATURES` / `build_macro_feat_config()` / `compute()` 输出字节等价
- YAML 缺失时 → `_DEFAULT_FEATURE_TO_DIM` 即原 `FEATURE_TO_DIM`，零变化

### 测试清单（6 TC，TDD RED→GREEN）

| TC# | 名称 | 断言 |
|---|---|---|
| TC1 | 接口不变 | `MacroFeatures.FEATURE_TO_DIM` 是 dict[str,str]；`ALL_FEATURES` 是 list[str]；`len(ALL_FEATURES)==37`；`REQUIRED_COLS` 不变 |
| TC2 | YAML 正常加载 | monkeypatch YAML 路径指向临时文件 → `reload()` 返回 True；`FEATURE_TO_DIM` 含临时特征 |
| TC3 | YAML 缺失 FAIL-OPEN | monkeypatch 路径指向不存在文件 → `reload()` 返回 False；`FEATURE_TO_DIM` == `_DEFAULT_FEATURE_TO_DIM` |
| TC4 | YAML 语法错误 FAIL-OPEN | 临时文件写乱码 → `reload()` 返回 False；`FEATURE_TO_DIM` == 默认值 |
| TC5 | 字节等价 | YAML 内容 == 默认值 → `reload()` 后 `FEATURE_TO_DIM == _DEFAULT_FEATURE_TO_DIM` 且 `ALL_FEATURES == list(_DEFAULT_FEATURE_TO_DIM.keys())` |
| TC6 | compute 行为不变 | YAML 加载后 `compute()` 输出 DataFrame 列名与默认配置一致（用空 macro_df 验证返回空 DataFrame） |

---

## §4 影响范围

### 改动文件

| 文件 | 改动量 | 说明 |
|---|---|---|
| `configs/macro_features.yaml` | 新建 ~50 行 | 37 特征→8 维度映射 |
| `scripts/memory_l4/bcrm2/macro_features.py` | ~40 行新增 | `_DEFAULT_FEATURE_TO_DIM` 重命名 + `_load_yaml_config()` + `reload()` |
| `tests/test_p2_macro_features_yaml.py` | 新建 ~150 行 | 6 TC TDD |

### 不改动文件（零影响确认）

- `macro_feature_select_v2.py` — 通过 `MacroFeatures.ALL_FEATURES` 引用，接口不变
- `macro_feature_optimize_v3.py` — 同上
- `macro_feature_optimize_v4.py` — 同上
- `macro_feature_validate_v2.py` — 同上
- `walk_forward_backtester.py` — 通过 `macro_config` dict 传入，不直接引用 `FEATURE_TO_DIM`
- `baseline_config.json` — 独立配置，无关联
- `polling_trader.py` — 不直接引用 `MacroFeatures` 类

### 运维

- 首次部署：创建 `configs/macro_features.yaml` 后无需重启（模块 import 时自动加载）
- 修改 YAML 后：调用 `MacroFeatures.reload()` 或重启进程
- 紧急回滚：删除或重命名 YAML 文件 → 自动 fallback 到硬编码默认值

---

## §5 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| YAML 文件被误删 | 低 | 自动 fallback 默认值，无影响 | FAIL-OPEN L0 |
| YAML 格式错误 | 中 | 自动 fallback 默认值 | FAIL-OPEN L1 + TC4 验证 |
| YAML 新增特征名拼写错误 | 中 | 该特征不生效（不在 ALL_FEATURES 中） | 下游 `build_macro_feat_config` 只遍历 ALL_FEATURES |
| PyYAML 未安装 | 低 | fallback 默认值 | import yaml 在 try 内 |
| 模块 import 时序问题 | 低 | `_load_yaml_config` 在类定义后调用 | 代码顺序保证 |

---

## 附录 A：YAML 完整内容

见 §2 YAML 结构部分（37 个特征，8 个维度，与现有 `_DEFAULT_FEATURE_TO_DIM` 完全一致）。

## 附录 B：_DEFAULT_FEATURE_TO_DIM 完整内容

即现有 `macro_features.py:L55-92` 的 `FEATURE_TO_DIM` 字典，重命名后内容一字不动。
