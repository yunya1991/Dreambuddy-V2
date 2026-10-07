# 同赛道估值对比模型（Sector Valuation Comparison）— Spec

> **版本**: v1.0
> **日期**: 2026-10-07
> **状态**: Draft（待审核）
> **定位**: 在 BDSM 子系统下新增「同赛道横向估值对比」能力，从热门赛道中挖掘低估潜力币种（跟涨机会），并以赛道整体估值水位作为离场/做空信号
> **前置依赖**: BDSM E8 板块横向估值（`compute_e8_cross_sector_valuation`，已存在）

***

## 0. 背景与目标

### 0.1 设计动机

1. **龙头暴涨后的同赛道跟涨机会**：热门赛道龙头（如 DEX 的 UNI、L2 的 OP）暴涨后，同赛道中估值较低的币种存在均值回归性跟涨潜力。传统金融中这是「行业轮动 + 相对估值修复」的经典策略。
2. **赛道整体高估 = 离场信号**：当某赛道所有成员估值均处于历史/横向高位时，该赛道可能进入泡沫末期，是持仓离场的重要信号，也是潜在做空机会。
3. **BDSM 现有 E8 的局限**：现有 `compute_e8_cross_sector_valuation` 是**单币视角**（给定币→算它在赛道的百分位），缺少：
   - **赛道整体水位**：无法判断「该赛道是否普遍高估」
   - **全赛道扫描**：无法遍历所有赛道找出低估币
   - **多维估值**：仅 MC/Fees 单一维度，缺少 MC/TVL、增长调整倍数
   - **跟涨催化**：没有「龙头动量 + 同赛道低估」的共振因子
4. **扩展 BDSM 研究范围**：BDSM 权威池仅 10 币，保持重点研究全套分析；本模型作为「潜力币种挖掘器」，从更大范围的同赛道币种中发现买入机会。

### 0.2 核心原则（铁律）

| #  | 铁律 | 违反后果 |
| -- | ---- | -------- |
| R1 | **赛道内对比才有意义**：跨赛道估值倍数不可比（DEX 的 MC/Fees 与 L1 的 NVT 量纲不同），所有横向百分位必须在同赛道内计算 | 跨赛道对比 = 苹果比橘子 |
| R2 | **中位数优先于均值**：估值倍数分布右偏严重，用中位数（median）而非均值（mean）作为赛道中枢，抗异常值 | 均值被极端值拉偏 → 误判 |
| R3 | **多维交叉验证**：低估判断需至少 2 个维度（如 MC/Fees + MC/TVL）同时低估才确认，单维度低估可能是「价值陷阱」（基本面差导致的便宜） | 单维低估 = 价值陷阱 |
| R4 | **FAIL-OPEN 中性**：数据不足（赛道成员 < 3 / 该币无数据）→ 返回中性（不触发任何信号），不阻塞 BDSM 主链路 | 数据故障不应阻断主链路 |
| R5 | **跟涨需龙头动量确认**：仅「同赛道低估」不足以买入，需叠加「赛道龙头近期强势」作为跟涨催化条件 | 低估但无催化 = 可能长期低估 |

***

## 1. 传统金融方法论借鉴

### 1.1 可比公司分析（Comparable Company Analysis, Comps）

Comps 是华尔街最广泛使用的估值方法，核心逻辑：**相似公司应交易在相似估值倍数**。

| 步骤 | 传统金融做法 | 加密对应 |
| ---- | ------------ | -------- |
| 1. 选择可比公司 | 同行业、相似规模、增长、利润率 | 同赛道（SECTOR_MAP）、相似市值 |
| 2. 收集财务数据 | EV、Revenue、EBITDA、Net Income | Market Cap、Fees(30d)、TVL |
| 3. 计算估值倍数 | EV/EBITDA、EV/Revenue、P/E、P/B | MC/Fees、NVT、MC/TVL |
| 4. 分析倍数分布 | mean / median / range，排除异常值 | median / percentile / IQR |
| 5. 应用到目标 | 目标指标 × 行业中位数 = 隐含价值 | 目标币倍数在赛道中的百分位 |
| 6. 理解差异原因 | 增长、利润率、风险差异解释倍数偏离 | 费用增长率、TVL 增速解释偏离 |

### 1.2 关键估值倍数映射

| 传统金融倍数 | 加密对应 | 适用赛道 | 数据来源 |
| ------------ | -------- | -------- | -------- |
| EV/EBITDA | **MC/Fees**（市值/30d 费用） | DeFi（DEX/Lending/Perp_DEX） | DeFiLlama fees + CoinGecko market_cap |
| P/E（市盈率） | **NVT**（市值/链上转账量） | L1（BTC/ETH/SOL 等） | L1 chain metrics |
| EV/Revenue | **MC/Revenue** | 有收入的协议 | DeFiLlama revenue |
| P/B（市净率） | **MC/TVL**（市值/锁仓量） | DeFi 协议 | DeFiLlama TVL + CoinGecko |
| PEG（市盈率/增长） | **(MC/Fees) / Fees_Growth** | 所有有费用的赛道 | MC/Fees + 费用环比增速 |

### 1.3 Damodaran 四步理解倍数（质量门控）

1. **定义一致性**：分子分母必须对同一索取权人（MC 对 Fees，不能 MC 对 Revenue）
2. **描述性测试**：知道倍数的横截面分布（均值、中位数、标准差、异常值处理）
3. **分析测试**：理解驱动倍数的基本面（增长、风险、现金流）
4. **应用测试**：可比公司应在基本面（增长/风险/现金流）上相似，而非仅同行业

> **本 SPEC 落地第 4 步**：同赛道内，用「费用增长率」「TVL 增速」对倍数进行调整，避免简单百分位导致的误判。

***

## 2. 现有 BDSM E8 实现分析

### 2.1 已有能力

| 模块 | 文件 | 能力 |
| ---- | ---- | ---- |
| SECTOR_MAP | `coin_fundamental_crypto.py:78-85` | 6 个赛道定义（DEX/Lending/L1/L2/Meme/Perp_DEX），每赛道 3-6 币 |
| `_SECTOR_COIN_META` | `coin_fundamental_crypto.py:89-122` | 赛道成员的 coingecko_id + defillama_slug 映射 |
| `compute_e8_cross_sector_valuation` | `coin_fundamental_crypto.py:179-219` | 单币在赛道内 MC/Fees（L1 用 NVT）百分位 → [-1, +1] |
| E8 消费 | `bdsm_snapshot_writer.py:774,849` | 写入快照 `e8_cross_sector_valuation`，参与 `value_exit` 离场判断 |

### 2.2 现有 E8 的局限

| 局限 | 说明 | 本 SPEC 解决方案 |
| ---- | ---- | ---------------- |
| 单币视角 | 只能算「给定币在赛道的位置」，不能「扫描全赛道找低估」 | 新增 `scan_sector_undervalued` 全赛道扫描 |
| 单一维度 | 仅 MC/Fees（L1 用 NVT），缺少 MC/TVL、增长调整 | 新增多维估值合成 `compute_multi_dim_valuation` |
| 无赛道水位 | 没有「赛道整体估值百分位」指标 | 新增 `compute_sector_waterline` |
| 无跟涨催化 | 低估但无催化可能长期低估 | 新增龙头动量确认 `check_leader_momentum` |
| 币种范围有限 | 仅 BDSM 池 + 少量竞对 | 扩展 SECTOR_MAP 成员池（不修改 BDSM_COINS） |

### 2.3 不变的部分

| 模块 | 状态 | 说明 |
| ---- | ---- | ---- |
| `BDSM_COINS`（10 币权威池） | 不变 | 重点研究池保持全套分析 |
| `bds_score` 计算（e5/e6/e7） | 不变 | 本模型新增独立维度，不修改 bds_score |
| `compute_e8_cross_sector_valuation` | 不变 | 复用，作为多维估值的一个输入 |
| 三层置信度递进开仓框架 | 不变 | 本模型输出作为「潜力币种发现」的辅助信号 |

***

## 3. 设计目标与核心指标

### 3.1 三大目标

| 目标 | 输出 | 用途 |
| ---- | ---- | ---- |
| **G1 挖掘低估潜力币** | `SectorUndervaluedScan` 结果（赛道 → 低估币列表 + 低估分数） | 跟涨买入候选 |
| **G2 赛道整体水位** | `SectorWaterline`（赛道整体估值百分位 + 过热判断） | 离场信号 |
| **G3 做空机会识别** | `SectorOverheatSignal`（赛道普遍高估 + 龙头动量衰竭） | 做空候选 |

### 3.2 核心指标定义

#### 指标 1：赛道整体估值水位（Sector Valuation Waterline）

```
sector_waterline = median(各币 MC/Fees 在赛道内的历史百分位)
```

- 取值 [0, 100]
- waterline ≥ 80：赛道过热（overheated）→ 离场信号
- waterline ≤ 20：赛道低估（undervalued）→ 关注机会
- 20 < waterline < 80：中性

#### 指标 2：多维度低估分数（Multi-dim Undervalued Score）

对赛道内每个币，计算多个估值维度的百分位，取最低（最便宜）的维度加权合成：

```
undervalued_score = 1.0 - weighted_percentile
  weighted_percentile = w1 * pct(MC/Fees) + w2 * pct(MC/TVL) + w3 * pct(PEG_adjusted)
```

- 取值 [-1, +1]
- score > +0.3：多维低估（潜在买入候选）
- score < -0.3：多维高估（潜在离场/做空）

#### 指标 3：跟涨催化因子（Follow-up Catalyst）

```
catalyst = leader_momentum × sector_breadth
  leader_momentum = 赛道龙头近 7d 收益率（归一化到 [-1, +1]）
  sector_breadth = 赛道内近 7d 上涨币占比 [0, 1]
```

- catalyst > 0.3：龙头强势 + 赛道广度好 → 跟涨概率高
- catalyst < -0.3：龙头弱势 + 赛道广度差 → 回避

#### 指标 4：综合潜力分数（Opportunity Score）

```
opportunity_score = undervalued_score * 0.6 + catalyst * 0.4
```

- 仅当 undervalued_score > 0 且 catalyst > 0 时计算（低估 + 有催化）
- opportunity_score > 0.5：高优先级跟涨候选

***

## 4. 模块设计

### 4.1 模块清单

| 模块 | 文件（新增/修改） | 职责 |
| ---- | ----------------- | ---- |
| `sector_waterline.py` | 新增 | 赛道整体估值水位计算 |
| `sector_undervalued_scanner.py` | 新增 | 全赛道低估扫描器 |
| `multi_dim_valuation.py` | 新增 | 多维度相对估值（MC/Fees + MC/TVL + PEG） |
| `follow_up_catalyst.py` | 新增 | 跟涨催化因子（龙头动量 + 赛道广度） |
| `sector_valuation_orchestrator.py` | 新增 | 编排以上模块，输出综合结果 |
| `coin_fundamental_crypto.py` | 修改 | 扩展 SECTOR_MAP、_SECTOR_COIN_META；新增 MC/TVL 倍数获取 |
| `bdsm_snapshot_writer.py` | 修改 | 快照新增 `sector_waterline`、`undervalued_peers`、`overheat_signal` 字段 |

### 4.2 赛道估值水位（SectorWaterline）

```python
@dataclass
class SectorWaterline:
    sector: str                          # 赛道名称
    median_percentile: float             # 赛道整体估值百分位 [0, 100]
    member_count: int                    # 有效数据成员数
    overheated: bool                     # waterline >= 80
    undervalued: bool                    # waterline <= 20
    leader: str                          # 赛道龙头（市值最大）
    leader_momentum_7d: float            # 龙头 7d 收益率
    timestamp: str
```

**计算逻辑**：
1. 取赛道所有成员的当前 MC/Fees（或 NVT）
2. 对每个币，计算其 MC/Fees 在**自身历史序列**中的百分位（纵向）
3. 取所有币纵向百分位的**中位数**作为赛道水位
4. 龙头动量 = 赛道市值最大币的 7d 价格收益率

> **设计决策**：水位用「纵向百分位的中位数」而非「横向百分位的中位数」。
> - 横向百分位只能告诉你「该币在赛道中相对便宜/贵」，无法判断「赛道整体是否处于历史高位」
> - 纵向百分位能告诉你「该币自身是否处于历史高位」，中位数反映赛道整体泡沫程度

### 4.3 全赛道低估扫描器（SectorUndervaluedScanner）

```python
@dataclass
class UndervaluedCoin:
    coin: str
    sector: str
    undervalued_score: float             # [-1, +1]
    multi_dim_details: Dict[str, float]  # {MC/Fees_pct, MC/TVL_pct, PEG_pct}
    leader_momentum: float               # 赛道龙头 7d 动量
    opportunity_score: float             # 综合潜力分
    rank: str                            # S/A/B/C（同 BDSM rank 体系）

@dataclass
class SectorUndervaluedScan:
    timestamp: str
    sectors: Dict[str, List[UndervaluedCoin]]  # 赛道 → 低估币列表
    top_opportunities: List[UndervaluedCoin]   # 全赛道 Top N 潜力币
```

**扫描逻辑**：
1. 遍历所有 SECTOR_MAP 赛道
2. 对赛道内每个币，调用 `compute_multi_dim_valuation`
3. 过滤 `undervalued_score > 0.3` 的币
4. 计算 `opportunity_score = undervalued_score * 0.6 + catalyst * 0.4`
5. 按 opportunity_score 降序排列，输出 Top N

### 4.4 多维度相对估值（MultiDimValuation）

```python
def compute_multi_dim_valuation(coin: str, db_path: str) -> Dict[str, float]:
    """返回多维度估值百分位。
    
    维度：
      - mc_fees_pct: MC/Fees 在赛道内的横向百分位 [0, 100]
      - mc_tvl_pct: MC/TVL 在赛道内的横向百分位 [0, 100]（仅 DeFi）
      - peg_pct: (MC/Fees)/Fees_Growth 在赛道内的横向百分位 [0, 100]
      - multi_dim_score: 合成 [-1, +1]，>0 表示低估
    """
```

**维度权重**（仅当数据可用时计入）：
- MC/Fees: 0.5（主维度，复用 E8 逻辑）
- MC/TVL: 0.3（DeFi 专用，反映资本效率）
- PEG 调整: 0.2（增长调整，高增长可承受高估值）

**合成公式**：
```
multi_dim_score = 1.0 - (w1*pct1 + w2*pct2 + w3*pct3) / 50.0
  映射到 [-1, +1]，与 E8 一致
```

### 4.5 跟涨催化因子（FollowUpCatalyst）

```python
def compute_follow_up_catalyst(sector: str, db_path: str) -> Dict[str, float]:
    """返回跟涨催化因子。
    
    leader_momentum: 龙头 7d 收益率归一化 [-1, +1]
    sector_breadth: 赛道内 7d 上涨币占比 [0, 1]
    catalyst: leader_momentum * sector_breadth
    """
```

**龙头识别**：赛道内市值最大的币。
**动量归一化**：7d 收益率映射到 [-1, +1]（±20% 为满量程）。

### 4.6 编排器（SectorValuationOrchestrator）

```python
class SectorValuationOrchestrator:
    """同赛道估值对比编排器。
    
    整合 waterline + scanner + multi_dim + catalyst，
    输出 G1（低估潜力币）、G2（赛道水位）、G3（过热做空信号）。
    """
    
    def run(self, db_path: str = None) -> SectorValuationResult:
        ...
```

```python
@dataclass
class SectorValuationResult:
    timestamp: str
    waterlines: List[SectorWaterline]           # 所有赛道水位
    undervalued_scan: SectorUndervaluedScan     # 低估扫描结果
    overheat_signals: List[SectorOverheatSignal] # 过热/做空信号
```

***

## 5. 信号输出与应用

### 5.1 跟涨买入信号（G1）

**触发条件**（AND）：
1. `undervalued_score > 0.3`（多维低估）
2. `catalyst > 0.3`（龙头强势 + 赛道广度好）
3. `opportunity_score > 0.5`（综合潜力高）
4. 该币不在 BDSM 权威池的「禁止开仓」状态

**输出**：`{coin, sector, opportunity_score, suggested_entry, discount_to_median}`

**与 BDSM 集成**：
- 作为 BDSM 独立开仓的「潜力币种候选池」输入
- 不直接开仓，需经过 BDSM 三层置信度框架确认（bds_score > 0 + 战略层放行）
- 仓位参照 BDSM L1（0.05），因为是新挖掘币种，数据质量可能不足

### 5.2 离场信号（G2）

**触发条件**（OR）：
1. 持仓币所在赛道 `waterline >= 80`（赛道整体过热）
2. 持仓币 `undervalued_score < -0.5`（多维高估）

**输出**：`{coin, sector, waterline, reason, suggested_action: "reduce" | "exit"}`

**与 BDSM 集成**：
- 写入快照 `overheat_signal` 字段
- 作为 `value_exit` 的补充触发条件（与现有 E8 + valuation_percentile 并列）

### 5.3 做空信号（G3）

**触发条件**（AND）：
1. 赛道 `waterline >= 85`（严重过热）
2. 龙头 `leader_momentum_7d < -0.1`（龙头开始转弱）
3. 赛道内 ≥ 60% 币 `undervalued_score < -0.3`（普遍高估）

**输出**：`{sector, waterline, leader_momentum, overvalued_ratio, confidence}`

**与 BDSM 集成**：
- 作为 BDSM 做空试错（`ENABLE_BDSM_SHORT_TRIAL`）的赛道级确认信号
- 不直接做空，需经过 BDSM 三层置信度框架确认（bds_score < 0 + 战略层放行做空）

***

## 6. 与 BDSM 快照集成

### 6.1 快照新增字段

在 `bdsm_snapshot_writer.py` 的 coin entry 中新增：

```python
{
    # ... 现有字段不变 ...
    "e8_cross_sector_valuation": 0.0,       # 现有，不变
    
    # === 本 SPEC 新增字段 ===
    "sector_waterline": {                    # 该币所在赛道的整体水位
        "sector": "DEX",
        "median_percentile": 45.0,
        "overheated": False,
        "undervalued": False,
        "leader": "UNI",
        "leader_momentum_7d": 0.15,
    },
    "multi_dim_valuation": {                 # 多维度估值详情
        "mc_fees_pct": 30.0,
        "mc_tvl_pct": 25.0,
        "peg_pct": 40.0,
        "multi_dim_score": 0.55,
    },
    "undervalued_peers": [                   # 同赛道低估伙伴（跟涨候选）
        {"coin": "1INCH", "opportunity_score": 0.62},
        {"coin": "SUSHI", "opportunity_score": 0.48},
    ],
    "overheat_signal": {                     # 过热/做空信号
        "triggered": False,
        "waterline": 45.0,
        "confidence": 0.0,
    },
}
```

### 6.2 顶层快照新增字段

```python
{
    # ... 现有字段不变 ...
    "sector_valuation_summary": {            # 全赛道估值概览
        "generated_at": "...",
        "waterlines": [...],                 # 所有赛道水位
        "top_opportunities": [...],          # Top N 潜力币
        "overheat_sectors": [...],           # 过热赛道列表
    },
}
```

***

## 7. 开关与 FAIL-OPEN

### 7.1 开关

| 开关 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `ENABLE_SECTOR_VALUATION` | True | 同赛道估值对比总开关 |
| `ENABLE_SECTOR_WATERLINE` | True | 赛道水位计算开关 |
| `ENABLE_UNDERVALUED_SCAN` | True | 低估扫描开关 |
| `ENABLE_MULTI_DIM_VALUATION` | True | 多维度估值开关 |
| `ENABLE_FOLLOW_UP_CATALYST` | True | 跟涨催化因子开关 |
| `ENABLE_OVERHEAT_SIGNAL` | True | 过热/做空信号开关 |

### 7.2 FAIL-OPEN 原则

| 异常场景 | 行为 |
| -------- | ---- |
| 赛道成员 < 3 | waterline 返回 None（不触发过热/低估） |
| 该币无估值数据 | multi_dim_score = 0.0（中性），不进入低估候选 |
| MC/TVL 数据缺失 | 该维度权重置 0，仅用可用维度加权 |
| 龙头价格数据缺失 | catalyst = 0.0（中性），跟涨信号不触发 |
| DB 查询失败 | 整模块返回中性结果，不阻塞快照生成 |
| 开关关闭 | 对应字段返回中性默认值 |

***

## 8. 验证计划

### 8.1 单元测试

1. **SectorWaterline**：
   - 3 币赛道，纵向百分位分别 [20, 30, 40] → median = 30，undervalued=True
   - 3 币赛道，纵向百分位 [85, 90, 95] → median = 90，overheated=True
   - 成员 < 3 → None

2. **MultiDimValuation**：
   - 三维度百分位 [20, 25, 30]，权重 [0.5, 0.3, 0.2] → score = +0.52
   - 单维度可用（仅 MC/Fees=20）→ score = +0.6
   - 全部维度缺失 → score = 0.0

3. **FollowUpCatalyst**：
   - 龙头 7d +15%，广度 0.8 → catalyst = 0.6
   - 龙头 7d -10%，广度 0.3 → catalyst = -0.15

4. **SectorUndervaluedScanner**：
   - 扫描后仅返回 undervalued_score > 0.3 的币
   - 按 opportunity_score 降序排列

### 8.2 回测验证

1. **跟涨策略回测**：
   - 假设：龙头暴涨后，同赛道低估币 7d 收益率 > 赛道平均
   - 数据：2024-2025 历史数据，赛道 = DEX/L1/L2
   - 指标：胜率、平均收益率、最大回撤

2. **过热离场回测**：
   - 假设：waterline >= 80 后，赛道未来 30d 收益率 < 0
   - 指标：离场后 30d 规避跌幅、离场时机准确率

3. **做空信号回测**：
   - 假设：waterline >= 85 + 龙头转弱后，赛道未来 14d 收益率 < -5%
   - 指标：做空胜率、盈亏比

### 8.3 与现有 BDSM 回归测试

1. 新增字段不影响现有 bds_score / 三层置信度开仓逻辑
2. 开关关闭时，快照与改动前字节等价（中性默认值）
3. BDSM_COINS 10 币的分析结果不变

***

## 9. 风险与缓解

| 风险 | 等级 | 缓解措施 |
| ---- | ---- | -------- |
| 赛道整体高估可能是「全市场泡沫」而非「该赛道泡沫」 | 中 | waterline 同时计算纵向（自身历史）百分位，不依赖横向对比 |
| Meme 币无费用数据，MC/Fees 失效 | 高 | Meme 赛道用 MC/Volume 或纯动量维度，不参与 MC/Fees 对比 |
| 低估 = 价值陷阱（基本面差导致的便宜） | 中 | 多维交叉验证（R3），需至少 2 维度同时低估 + 龙头动量确认 |
| 跟涨逻辑在熊市失效 | 中 | 战略层 direction_state 过滤（仅在 LONG_ONLY/LONG_PREFER/NEUTRAL 时触发） |
| 小币种数据覆盖率低 | 中 | FAIL-OPEN 中性，数据不足不触发信号；优先覆盖头部赛道 |
| 赛道分类不准确（一币多赛道） | 低 | SECTOR_MAP 允许一币多赛道，扫描时按主赛道归属 |

***

## 10. 开发任务（TDD）

```yaml
development_tasks:
  - id: TDD-SVC-001
    hypothesis: "赛道内 ≥3 币的纵向估值百分位中位数能准确反映赛道整体水位"
    test_assertion: "assert compute_sector_waterline('DEX', db)['median_percentile'] == median([pct for coin in DEX])"
    priority: P0
    depends_on: []
    target_skill: dream-tdd-dev-workflow
    evidence: "传统金融 Comps 中位数比均值可靠（Damodaran 描述性测试）"

  - id: TDD-SVC-002
    hypothesis: "多维度估值（MC/Fees + MC/TVL + PEG）比单一 MC/Fees 更能识别真实低估"
    test_assertion: "assert multi_dim_score(coin) > 0.3 requires at least 2 dimensions below 40th percentile"
    priority: P0
    depends_on: [TDD-SVC-001]
    target_skill: dream-tdd-dev-workflow
    evidence: "R3 多维交叉验证铁律；价值陷阱风险"

  - id: TDD-SVC-003
    hypothesis: "龙头强势 + 赛道广度好时，同赛道低估币跟涨概率显著高于无条件选股"
    test_assertion: "assert backtest_follow_up(catalyst>0.3)['win_rate'] > backtest_random()['win_rate']"
    priority: P1
    depends_on: [TDD-SVC-002]
    target_skill: dream-tdd-dev-workflow
    evidence: "R5 跟涨需龙头动量确认铁律"

  - id: TDD-SVC-004
    hypothesis: "waterline >= 80 时赛道未来 30d 收益率显著为负，可作为离场信号"
    test_assertion: "assert backtest_waterline_exit(80)['avg_return_30d'] < 0"
    priority: P1
    depends_on: [TDD-SVC-001]
    target_skill: dream-tdd-dev-workflow
    evidence: "传统金融行业轮动过热离场策略"

  - id: TDD-SVC-005
    hypothesis: "waterline >= 85 + 龙头转弱 + 普遍高估时，赛道未来 14d 跌幅 > 5%"
    test_assertion: "assert backtest_overheat_short()['avg_return_14d'] < -0.05"
    priority: P2
    depends_on: [TDD-SVC-001]
    target_skill: dream-tdd-dev-workflow
    evidence: "做空信号需三重确认（过热+动量衰竭+普遍高估）"
```

***

## 11. 5 维交叉验证评分

| 维度 | 评分 | 说明 |
| ---- | ---- | ---- |
| 完整性 | 8/10 | 覆盖传统 Comps 方法论 + 加密 MC/Fees/NVT/MC/TVL；缺远期数据回测 |
| 可落地性 | 9/10 | 数据源就绪，E8 可复用，模块化新增 |
| 工程适配性 | 8/10 | FAIL-OPEN 复用，不修改 bds_score，开关控制 |
| 风险识别 | 7/10 | 识别价值陷阱、Meme 无费用、熊市失效等风险 |
| 创新性 | 7/10 | Comps + 赛道轮动 + 跟涨催化的加密特化应用 |

**综合评分：7.8/10** → 进入开发阶段（P1 优先级）。

***

## 12. 参考文献

1. Aswath Damodaran, "Relative Valuation", NYU Stern
2. CFA Institute Equity Valuation Curriculum — Comparable Company Analysis
3. Schwab Asset Management, "A Framework for Valuing Cryptocurrencies", 2026
4. Fidelity Digital Assets, "Signals Report Q2 2026" — NUPL / Dominance / Usage Metrics
5. Synthos Research, "Flagship Crypto Portfolio" — 四维评分 + 赛道权重框架
6. 现有 BDSM E8 实现：`coin_fundamental_crypto.py:compute_e8_cross_sector_valuation`
7. 现有 BDSM 三层置信度 spec：`2026-09-18-bdsm-tiered-confidence-open-spec.md`
