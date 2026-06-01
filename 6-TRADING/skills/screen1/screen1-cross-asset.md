# /screen1-cross-asset

**Screen 1 — A系列：跨资产宏观对冲配置（Dalio All-Weather × BTC）**

跨资产多空配置 SKILL。基于美林时钟象限定位，输出多空对冲配置矩阵，生成 Screen 1 A系列最终输出（标的、方向、权重、马丁参数），写入 `screen1_cross_asset_annotation.json`。

> **BTC-centered**: 以 BTC 为核心研究标的，通过跨资产对冲放大组合效率。ETH/SOL 仅作为对冲标的出现，不独立运行此 SKILL。

---

## 一、Dalio 全天候框架 × BTC 适配理论

### 1.1 原版全天候核心思想

桥水全天候（All-Weather）基于以下认知：

```
任何资产在不同宏观环境下表现迥异。
驱动资产回报的核心宏观变量只有两个：
  ① 经济增长（GDP）：高于/低于预期
  ② 通货膨胀（CPI）：高于/低于预期

四种环境的组合形成四个象限：
  GDP↑ CPI↓ → 复苏    → 风险资产领涨
  GDP↑ CPI↑ → 过热    → 商品领涨
  GDP↓ CPI↑ → 滞胀    → 防御资产领涨
  GDP↓ CPI↓ → 再通胀  → 债券/黄金领涨

真正的"全天候"：在每个象限都持有该象限的领涨资产。
```

**风险平价原则**：
```
传统 60/40（60% 股票 + 40% 债券）:
  90% 的风险来自股票
  → 股票下跌时组合大幅亏损

风险平价（All-Weather）:
  每个象限分配等量"风险预算"（而非等量资金）
  → 无论哪个象限，组合均有受益资产
  → 最大回撤和波动率均大幅降低
```

### 1.2 BTC 中心化适配

BTC 不是传统意义上的"避险资产"，其角色随宏观周期动态变化：

```
Recovery (GDP↑ CPI↓):
  BTC = 高贝塔做多标的
  原因: 流动性宽松 + 风险偏好最高 + 机构ETF买入
  历史: 2020-2021 Recovery期 BTC +1700%（领跑所有资产）
  策略: 满仓做多，主力配置

Overheat (GDP↑ CPI↑):
  BTC = 轻仓做多（宽间隔等待回调）
  原因: 通胀升温 → Fed加息预期 → BTC高估值承压
  但增长仍强 → 不做空，轻仓持有
  策略: 缩减仓位，能源/黄金替代主力

Stagflation (GDP↓ CPI↑):
  BTC = 高贝塔空头对冲标的
  原因: 双重压制（增长萎缩 + 流动性收紧）
  BTC 2022年Stagflation: -75%（最大回撤历史第二）
  策略: 做空BTC/ETH，做多防御商品对冲

Reflation (GDP↓ CPI↓):
  BTC = 左侧积累建仓
  原因: 衰退通缩 → Fed降息空间打开 → 流动性拐点临近
  BTC 2023年Reflation: +300%（领先其他资产）
  策略: 宽间隔低频布局，等待流动性拐点确认
```

### 1.3 与传统全天候的三大差异

| 维度 | 桥水原版 | BTC中心化适配 |
|------|---------|-------------|
| 多空方向 | 仅多头 + 债券对冲 | 允许高贝塔空头（BTC/ETH空） |
| 资产类别 | 股票/债券/商品 | 加密货币+代币化股票/商品ETF |
| 象限策略 | 平滑切换 | Stagflation极端防御，Recovery极端进攻 |

---

## 二、四象限配置矩阵（核心）

### 2.1 Recovery（春天）— BTC 最优阶段

```
条件: GDP>3% + CPI<2%
仓位乘数: 1.0（满仓进攻）
BTC角色: 高贝塔多头主力（high_beta_long）

多头配置:
  BTC   40%  [标准马丁: 间隔8%×vm, TP4%×vm, L3]
  ETH   20%  [标准马丁]
  SOL   10%  [标准马丁]
  NVDA  15%  [权益马丁: 间隔4%×vm, TP2%×vm, L2]
  TSLA  10%  [权益马丁]

空头配置: 无

现金: 5%
止损规则: 20% 组合回撤强制全平

逻辑: BTC/ETH/SOL高贝塔同向杠杆，NVDA/TSLA代币化科技股跟随
对冲对: Long SOL + Long BTC（相关0.65，同向加杠杆）
```

### 2.2 Overheat（夏天）— 商品 > 股票 > BTC

```
条件: GDP>0% + CPI>2% 且 CPI持续上行
仓位乘数: 0.6（缩减敞口）
BTC角色: 轻仓多头（light_long，宽止损等待）

多头配置:
  XLE   25%  [权益马丁: 能源ETF受益通胀]
  GOLD  15%  [权益马丁: 黄金抗通胀]
  BTC   20%  [轻型马丁: 间隔12%×vm, TP6%×vm, L2, 宽间隔防震荡]

空头配置:
  SPY   10%  [单层不加仓: 对冲股市下行风险]

现金: 30%
止损规则: 15% 组合回撤止损

逻辑: 通胀受益资产作主力，BTC轻仓降低集中度，空SPY对冲尾部风险
对冲对: Long XLE + Short SPY（相关0.40，方向差即利润）
```

### 2.3 Stagflation（秋天）— 防御优先，空高贝塔

```
条件: GDP<0%（或接近零/负增长）+ CPI>2%
仓位乘数: 0.4（最保守）
BTC角色: 高贝塔空头对冲标的（high_beta_short）

多头配置:
  XLP   25%  [权益马丁: 消费必需品抗衰退]
  XLE   20%  [权益马丁: 能源仍受益通胀]
  GOLD  15%  [权益马丁: 黄金双重避险]

空头配置:
  BTC   10%  [宽间隔马丁: 间隔12%×vm, TP6%×vm, L3, 防逼空]
  ETH    5%  [单层不加仓: 高波动空头，单层保护]

现金: 25%
止损规则: 10% 组合回撤止损（防御模式最严格）

逻辑: XLP/ETH为最佳对冲对（相关-0.10），做多防御资产+做空高贝塔
对冲对: Long XLP + Short ETH（相关-0.10，最佳对冲对）
```

### 2.4 Stagflation Lite（轻度秋天）— 当前策略

```
条件: GDP>0%但<3% + CPI>2%（轻度滞胀，非经典衰退）
策略: 同Stagflation，但GDP仍正增长
特点: BTC阶段性反弹概率更高（非纯衰退）
     可适当缩减空头规模或提高止盈目标

配置: 与Stagflation相同，strategy_note注明GDP正增长
```

### 2.5 Reflation（冬天）— 等待流动性拐点

```
条件: GDP<0% + CPI<2%（通缩式衰退）
仓位乘数: 0.5（中度保守）
BTC角色: 左侧积累建仓（accumulation_lhs）

多头配置:
  SPY   30%  [权益马丁: 衰退末期股市先行反弹]
  BTC   20%  [左侧BTC马丁: 间隔12%×vm, TP8%×vm, L2, 宽止盈等待反转]

空头配置: 无

现金: 35%（保留最多弹药）
止损规则: 15% 组合回撤止损

逻辑: SPY债券先行+BTC宽间隔左侧布局，保留大量弹药应对不确定性
对冲对: Long SPY + Long GOLD（相关0.05，几乎独立）
```

---

## 三、马丁参数矩阵

| 模式名 | 加仓间隔 | 止盈 | 最大层数 | 是否单层 | 适用场景 |
|--------|---------|------|---------|---------|---------|
| standard | 8%×vm | 4%×vm | 3 | 否 | 加密主力多头（Recovery BTC/ETH/SOL） |
| light | 12%×vm | 6%×vm | 2 | 否 | 轻仓多头（Overheat BTC） |
| wide_interval | 12%×vm | 6%×vm | 3 | 否 | 宽间隔空头（Stagflation BTC空，防逼空） |
| single_layer | 0% | 5%×vm | 1 | 是 | 高波动空头（ETH空，不加仓防止扩损） |
| equity | 4%×vm | 2%×vm | 2 | 否 | 代币化股票/商品ETF（XLE/XLP/GOLD/NVDA/TSLA） |
| reflation_btc | 12%×vm | 8%×vm | 2 | 否 | 左侧建仓（Reflation BTC，宽止盈等待反转） |

> `vm` = `vol_mult`（动态历史波动率乘数），来自 Screen1 `vol_mult` 字段

---

## 四、资产相关性矩阵

| 资产对 | 相关系数 | 最佳用途 |
|--------|---------|---------|
| XLP / ETH | **-0.10** | Stagflation最佳对冲对 |
| SPY / GOLD | **0.05** | Reflation几乎独立组合 |
| BTC / GOLD | -0.10 | 黄金对冲BTC极端风险 |
| XLE / SPY | 0.40 | Overheat方向差套利 |
| SOL / BTC | 0.65 | Recovery同向加杠杆 |
| BTC / ETH | 0.75 | 高度相关，不同时做多空 |
| ETH / SOL | 0.80 | 极高相关，不宜同向 |

**选对冲对原则**：相关越低（越负），对冲效果越好；两个高度正相关资产不应同时持有同方向仓位。

---

## 五、Phase 1 / Phase 2 资产管理

```
Phase 2 资产: XLE, XLP, GOLD（代币化传统ETF，依赖RWA 2.0上线）

Phase 1 限制（phase1_only=True）:
  多头中的 Phase 2 资产 → 权重全部转入 USDT（现金）
  空头不受影响（BTC/ETH空头正常执行）

Phase 2 开启后:
  全部按配置矩阵执行，XLE/XLP/GOLD正常做多
  预期完整版: Stagflation 从"全现金防御"变为"60%多头(XLP/XLE/GOLD)+15%空(BTC/ETH)+25%现"

当前状态（2026-06）: Phase 1
  Stagflation_Lite Phase1: 仅保留BTC/ETH空头，XLP/XLE/GOLD多头转现金
```

---

## 六、象限切换触发规则

| 当前象限 | 转入目标 | 触发条件 |
|---------|---------|---------|
| Stagflation_Lite | Recovery | CPI连续2月<2.5% AND 10Y<4% 或 Fed首次降息 |
| Stagflation_Lite | Overheat | GDP>3% AND CPI>3%（增长超预期） |
| Stagflation_Lite | Reflation | GDP<0 AND CPI<2%（滑入衰退+通胀回落） |
| Stagflation_Lite | Stagflation | GDP转负，维持高通胀 |
| Stagflation | Recovery | CPI连续2月<2.5% AND 10Y<4% 或 Fed首次降息 |
| Stagflation | Overheat | GDP>3% AND CPI>3% |
| Stagflation | Reflation | GDP<0 AND CPI<2% |
| Recovery | Overheat | CPI连续2月>3% AND GDP>2% |
| Recovery | Stagflation | GDP<1% AND CPI>3%（紧急防御） |
| Overheat | Stagflation | GDP开始下行 AND CPI仍>2% |
| Overheat | Recovery | CPI明显回落<2% AND GDP>2%（软着陆） |
| Reflation | Recovery | GDP触底反弹>0 AND CPI<2%（拐点确认）|
| Reflation | Stagflation | GDP未反弹，CPI再起（二次通胀） |

---

## 七、执行步骤

### Step 1 — 运行代码基线

```bash
cd /c/tmp && python cross_asset_allocator.py
```

查看四象限配置矩阵输出，确认当前 clock_stage 下的默认配置。

---

### Step 2 — 读取跨市场维度 annotation

```bash
cat C:\tmp\Dreambuddy-V2\6-TRADING\screen1_cross_market_annotation.json
```

提取关键字段：
- `clock_stage` → 象限定位（RECOVERY/OVERHEAT/STAGFLATION/STAGFLATION_LITE/REFLATION）
- `gold_vs_stocks` → 防御/进攻模式判断
- `clock_transition_outlook` → 象限切换时间窗口预期

---

### Step 3 — 验证象限稳定性（Tavily 搜索）

使用 `mcp__tavily__tavily-search`。**禁止使用 WebSearch/WebFetch/curl。**

1. `"US GDP growth CPI inflation 2026 latest data"` — 确认象限未发生切换
2. `"Bitcoin ETF net flow institutional 2026"` — 机构ETF流量（影响Phase 2时机）
3. `"XLE XLP tokenized ETF crypto 2026"` — Phase 2 资产上线状态确认

---

### Step 4 — Phase 2 状态判断

根据 Step 3 搜索结果：

| 条件 | Phase 状态 | 配置影响 |
|------|----------|---------|
| XLE/XLP/GOLD代币化ETF已在目标交易所上线且流动性充足 | Phase 2 开启 | `phase1_only=False` |
| 未上线 或 上线但流动性不足（日成交<100万USDT） | Phase 1 | `phase1_only=True` |

> 当前（2026-06）：Phase 1，XLE/XLP/GOLD多头权重转现金。

---

### Step 5 — 计算 A系列配置输出

调用代码：
```python
from cross_asset_allocator import calc_cross_asset_allocation, format_screen1_a_summary
result = calc_cross_asset_allocation(
    clock_stage="STAGFLATION_LITE",
    regime="STRONG_BEAR",
    phase1_only=True,  # 或 False（根据Step 4判断）
)
print(format_screen1_a_summary(result))
```

输出结构：
```json
{
  "ml_clock_phase":      "STAGFLATION_LITE",
  "btc_role":            "high_beta_short",
  "season":              "Autumn",
  "position_multiplier": 0.4,
  "allocation": {
    "long":  [],
    "short": [
      {"asset": "BTC", "weight": 0.10, "direction": "SHORT", "martin_mode": "wide_interval", "martin_params": {...}},
      {"asset": "ETH", "weight": 0.05, "direction": "SHORT", "martin_mode": "single_layer",  "martin_params": {...}}
    ],
    "cash":  0.85
  },
  "total_deployed":  0.15,
  "regime_trigger":  {"to_recovery": "CPI<2.5%×2月...", ...},
  "best_hedge_pair": {"long_asset": "XLP", "short_asset": "ETH", "note": "相关-0.10，最佳对冲对"},
  "excluded_phase2": ["XLP", "XLE", "GOLD"],
  "strategy_note":   "Stagflation Lite: ...",
  "stop_rule":       "10% 组合回撤止损"
}
```

---

### Step 6 — 象限切换触发核查

对照当前宏观数据检查是否触发象限切换：

```
当前象限: STAGFLATION_LITE
检查触发条件:
  → to_recovery: CPI 最近2月是否均<2.5%? 10Y 是否<4%?
  → to_overheat: GDP 是否>3% AND CPI>3%?
  → to_reflation: GDP 是否<0 AND CPI<2%?

若触发: 更新 clock_stage → 重新运行 Step 5 → 输出新象限配置
若未触发: 维持当前配置
```

---

### Step 7 — 写入注释文件

写入 `C:\tmp\Dreambuddy-V2\6-TRADING\screen1_cross_asset_annotation.json`：

```json
{
  "updated": "<今日日期 YYYY-MM-DD>",
  "clock_stage": "<当前象限>",
  "btc_role": "<BTC角色>",
  "skill_regime": "<A3 SKILL 研判结论: STRONG_BULL/WEAK_BULL/CONSOLIDATION/WEAK_BEAR/STRONG_BEAR>",
  "phase1_only": <true/false>,
  "position_multiplier": <值>,
  "allocation_long": [{"asset": "<>", "weight": <>, "martin_mode": "<>"}],
  "allocation_short": [{"asset": "<>", "weight": <>, "martin_mode": "<>"}],
  "cash_pct": <值>,
  "total_deployed": <值>,
  "best_hedge_pair": {"long_asset": "<>", "short_asset": "<>", "note": "<>"},
  "excluded_phase2": ["<>"],
  "regime_trigger": {"to_recovery": "<>", "to_overheat": "<>", "to_reflation": "<>"},
  "clock_transition_risk": "<本周期象限切换概率与时间预期>",
  "strategy_note": "<当前策略叙事>",
  "stop_rule": "<止损规则>",
  "confidence": <0.70~0.95>
}
```

---

### Step 8 — 输出 Screen 1 最终摘要

```
=== Screen 1 A系列 跨资产多空配置 ===
当前日期: YYYY-MM-DD
象限定位:    [象限] ([季节]) | 仓位乘数: X.X
BTC 角色:    [角色中文描述]
总敞口:      XX% | 现金: XX% | Phase: [1/2]
─────────────────────────────────────────────────
多头配置:
  [资产] XX%   [间隔N%×vm | TPM%×vm | LN]  [马丁模式说明]
空头配置:
  [资产] XX%   [间隔N%×vm | TPM%×vm | LN]  [马丁模式说明]
Phase 2 跳过: [资产列表] → 合并现金
─────────────────────────────────────────────────
最佳对冲对:  Long [资产] + Short [资产] ([相关性说明])
象限切换触发:
  → 转入 Recovery: [条件]
  → 转入 Overheat: [条件]
  → 转入 Reflation: [条件]

注释已写入: C:\tmp\Dreambuddy-V2\6-TRADING\screen1_cross_asset_annotation.json
```

---

## 八、Screen 1 最终输出格式（完整）

将 A系列 与 技术/周期牛熊锚 合并后的最终摘要：

```
Screen 1 最终输出（BTC 示例，当前状态）:
  ├── 牛熊锚:      BEAR（技术维度 + 减半周期 + 矿工经济 + 链上估值合成）
  ├── 象限定位:    Stagflation Lite（GDP+2%, CPI 3.5%）
  ├── BTC 角色:    高贝塔空头对冲标的
  ├── 多空配置:
  │     Long  —（Phase 1，XLP/XLE/GOLD转现金）
  │     Short BTC 10%（宽间隔马丁L3）+ ETH 5%（单层）
  │     Cash  85%
  ├── 仓位乘数:    0.4（防御模式）
  ├── 最佳对冲对:  Long XLP + Short ETH（相关 -0.10）
  ├── 下一触发:    CPI<2.5%×2月 → 转入 Recovery
  └── 止损规则:    10% 组合回撤止损
```

---

## 九、回退逻辑

| 场景 | 行为 | 数据来源 |
|------|------|---------|
| 跨市场 annotation + SKILL 搜索 | 全量象限验证 + Phase 状态更新 | Tavily 实时数据 |
| 仅跨市场 annotation | 直接读取 clock_stage，跳过 Step 3 | annotation 文件 |
| annotation 不存在 | 默认 STAGFLATION_LITE，phase1_only=True | 代码默认值 |
| cross_asset_allocator import 失败 | A系列输出空字典，控制台警告 | 维度关闭 |
| 象限切换触发 | 更新 clock_stage → 重新生成配置 | 新象限矩阵 |

---

## 十、常见误区

| 误区 | 正确认知 |
|------|---------|
| "Stagflation 全清仓等待" | Phase 1 下仍保留 BTC/ETH 空头，空头受益于下跌趋势 |
| "做空 BTC 用单层即可" | Stagflation 空头用 wide_interval（L3宽间隔）防止逼空吃损 |
| "Recovery 直接买 BTC 不对冲" | Recovery 最优，ETH/SOL 同向加杠杆提升高贝塔回报 |
| "相关性越高对冲效果越好" | 错误！相关越低（越负）才是好对冲；XLP/ETH=-0.10是最佳对冲对 |
| "Phase 2 流动性不足也可以配" | 流动性不足（<100万USDT/日）的资产不应进入马丁配置，强制转现金 |
| "象限切换当天立即全仓换配置" | 象限切换需2-3个数据点确认，建议分批过渡（1/3→2/3→全换）|

---

## 注意事项

- **搜索工具**: 必须使用 `mcp__tavily__tavily-search`，禁止 WebSearch/WebFetch/curl
- **Phase 2 优先级**: 在 Phase 1 阶段，XLE/XLP/GOLD 多头权重自动转现金，由代码处理
- **象限跟踪**: 每次 GDP 初值发布（每季度）和 CPI 数据后必须重新验证象限定位
- **马丁参数 vm**: `interval_pct` 和 `tp_pct` 均需乘以 `vol_mult`（来自 Screen1Output.vol_mult）
- **更新频率**: 建议 TeamA 每月运行一次，配合跨市场维度同步更新
- **数据文件路径**: 确保 `C:\tmp\Dreambuddy-V2\6-TRADING\` 目录存在
