# BDSM 价值驱动分批建仓策略技术文档

> **版本**: v1.4 | **日期**: 2026-09-04 | **状态**: 实盘运行中（小额测试模式·单币 25U 硬上限）
> **作者**: AI辅助 | **关联**: bdsm-bcrm-coop-spec.md
>
> **v1.4 变更**（实盘首轮冒烟评估后落地，按 7 Check 核查结论修订）：
>
> 1. **BDSM-SPEC-v1.4-001**（趋势止损收紧 Fix-I）：§3.3.1 表格把「MA128 死叉 → reduce30」规则升级为**三件套齐触发**：`death_cross AND below_ma200_days ≥ 2 AND MA200 斜率转负`。解决 v1.3 中仅看死叉产生的大量假信号（2026-09-04 快照：AAVE/ETH/SOL 三处 MA 数值死叉但价格仍在 MA200 上方/斜率未转负 → action 正确维持 none）。减少牛顶假减仓，配合 §3.4.2 的价值发现止盈双门控。
> 2. **BDSM-SPEC-v1.4-002**（快照 JSON Schema 命名对齐）：§5.3 Phase 0 返回值示例 + 附录 A 把 technical\_assessment / scaling\_plan / trend\_stop / value\_exit 四大嵌套对象统一为**快照实际生成的键名**（如 rsi\_14 / ma200\_deviation / below\_ma200\_days / pf\_percentile / target\_notional\_usdt 等）。旧的语义化命名（rsi / ma200\_dev\_pct / bds\_collapse / batches / total\_budget）与生产代码不一致，已造成核查脚本误报"字段缺失"。向后兼容：消费端同时读两套键名。
> 3. **BDSM-SPEC-v1.4-003**（小额实盘测试模式 + 剩余预算覆盖）：新增 §3.2.4「微仓实盘预算硬上限」与 §5.7「运行模式演进路径」。用户决策：跳过原 7 日影子观察期，改用**单币预算硬上限 CLI 开关** **`--bdsm-budget-per-coin`**（默认 25U/币）覆盖 scaling\_plan 默认 167U/币；配合 §3.5 前置检查 9 条 + FAIL-OPEN 兜底三重安全网，把最大潜在 BDSM 敞口从 500U 压缩到 75U（3 币×25U），等 10+ 笔完整交易/胜率≥70%/回撤满意后移除小帽恢复标准预算。
>
> **v1.3 历史变更（已上线）**：
>
> 1. 固定百分比跌幅 → **动态评估器(CVS)驱动**（基本面+技术面双评估器，低估后大胆加仓，底部可"打完子弹"）
> 2. 固定百分比 SL(8\~15%) → **技术趋势止损(MA200/MA128 破位)**（价值投资"越跌越买"要求止损基于趋势反转）
> 3. 新增 **价值发现驱动止盈**（替代BCRM固定百分比TP，巴菲特原则：不因获利而卖出）
> 4. 评估周期 季度(2季度) → **按周(2周)**（加密节奏快）
> 5. 新增 DCA vs Scaling 澄清（巴菲特反对 DCA ≠ 反对分批建仓）
>
> **⚠ 对照说明约定**：本文档中所有「固定百分比 SL(8\~15%)」「固定百分比跌幅」等字样均为**历史对照/对比参考**，用于解释变更理由，**非当前 BDSM 生效规则**。当前生效规则版本以**标题行 v1.4** 为准：
>
> - 止损 = 逻辑止损 + 趋势止损 MA200/MA128（§3.3.1 Fix-I 三件套版本）
>
> - 微仓实盘预算硬上限 25U/币（§3.2.4）

***

## 目录

1. [传统价值投资三大流派核心逻辑](#一传统价值投资三大流派核心逻辑)
2. [加密市场估值框架（适配 BDSM 7 币种）](#二加密市场估值框架适配-bdsm-7-币种)
3. [BDSM 价值驱动分批建仓策略映射](#三bdsm-价值驱动分批建仓策略映射)
4. [GitHub 参考项目调研](#四github-参考项目调研)
5. [结合项目实现的综合评估方案](#五结合项目实现的综合评估方案)

***

## 一、传统价值投资三大流派核心逻辑

### 1.1 格雷厄姆：安全边际 + 量化择时

**核心思想**：价格远低于内在价值时买入，以量化指标消除情绪干扰。

| 指标          | 公式             | 买入阈值         | 持有阈值      | 减仓阈值         |
| ----------- | -------------- | ------------ | --------- | ------------ |
| 盈利收益率 (E/P) | 净利润/市值（P/E 倒数） | > 10%        | 6.4%\~10% | < 6.4%（分10档） |
| NCAV 折扣     | 净流动资产价值        | < NCAV × 2/3 | —         | —            |

**资产配置规则（75/25）**：股票仓位 25%\~75%，债券仓位 25%\~75%。防御型 10\~30 只每只 ≤10%，进取型 20+ 只每只 ≤5%。

**对 BDSM 的映射**：盈利收益率 → P/F 倒数；安全边际 → BDS ≥ 0.3 且 P/F < 中位数 0.7x；75/25 → BDSM 子池占总仓位 ≤25%。

### 1.2 巴菲特：DCF 现金流折现 + 集中持仓

**核心思想**：内在价值 = Σ FCF\_t / (1+r)^t，r=10%。

| 价格 vs 内在价值 | 操作    |
| ---------- | ----- |
| 价格 << 内在价值 | 重仓买入  |
| 价格 ≈ 内在价值  | 持有不加仓 |
| 价格 >> 内在价值 | 分批减仓  |

**关键原则**：反对 DCA 用于大资金管理（等待"完美球"，348B 现金）；被动投资者定投指数基金合理；Lump Sum 66% 情况优于 DCA（Vanguard 2012，超额+2.3%）。

**对 BDSM 的映射**：DCF → DeFi 协议收入折现；折现率 → 加密 20\~50%；等待"完美球" → BDS ≥ 0.3 低估区才启动建仓。

### 1.3 分批建仓 Scaling 法则

**核心思想**：预设计划，纪律执行，越跌越买。

> **⚠ 以下为传统 Scaling 法则的历史描述（固定百分比跌幅），BDSM 已改进为动态评估器驱动，见 §3.2。此处保留用于说明设计渊源。**

| 批次  | 触发条件    | 仓位比例     |
| --- | ------- | -------- |
| 第1批 | 初始信号触发  | 25% 目标仓位 |
| 第2批 | 价格跌 10% | 25%      |
| 第3批 | 价格跌 20% | 25%      |
| 第4批 | 价格跌 30% | 25%      |

**前提条件**：①深度基本面信念 ②充足资本储备 ③明确止损条件 ④区分"暂时回调"vs"基本面恶化"。

> **注意**：传统 Scaling 用固定百分比跌幅，BDSM 改进为**动态评估器驱动**（见 §3.2）。固定百分比有两个缺陷：①机械等跌幅可能错过底部机会；②与"越跌越买"逻辑在止损端冲突（固定 SL 会扫掉加仓仓位）。BDSM 用双评估器(CVS)决定加仓力度，用趋势止损(MA200/MA128)替代固定 SL，用价值发现驱动止盈替代固定百分比 TP。

### 1.4 DCA vs Lump Sum 实证

| 研究              | 结论                     | 数据         |
| --------------- | ---------------------- | ---------- |
| Vanguard 2012   | Lump Sum 66% 情况优于 DCA  | 超额收益 +2.3% |
| 2008 金融危机       | Lump Sum 亏 37%         | DCA 显著降低回撤 |
| 3Commas/Binance | 配置合理的 DCA bot 超越手动 23% | 12 个月周期    |

**结论**：大资金 + 高确信度 → 偏向 Lump Sum；中等确信度 + 高波动 → 分批 Scaling 更优。BDSM 属于后者。

### 1.5 关键澄清：巴菲特反对 DCA ≠ 反对分批建仓

> **表面矛盾**：巴菲特"反对 DCA"（348B 现金等待），而 BDSM 采用分批建仓。是否冲突？

**不冲突。** DCA 与 Scaling 本质不同：

| 维度    | DCA（巴菲特反对） | Scaling（BDSM 采用） |
| ----- | ---------- | ---------------- |
| 定义    | 定期定额买入，不择时 | 确认低估后按评估分批加仓     |
| 择时    | 不择时        | CVS ≥ 0.3 才启动    |
| 价格条件  | 不管价格       | 动态评估决定，不等固定跌幅    |
| 基本面检查 | 无          | 每批检查 BDS 未恶化     |
| 止盈    | 无          | 价值发现驱动（不因微涨出场）   |

**巴菲特自己也分批建仓**：可口可乐(1988\~1994)、苹果(2016\~2018)、2020Q1 航空股。他反对的是无差别定投，不是分批建仓。BDSM 第1批前提 BDS ≥ 0.3（"完美球"出现），后续加仓需 CVS 达标且 BDS 未恶化，总仓有硬上限 500U——这是 Scaling 不是 DCA。

***

## 二、加密市场估值框架（适配 BDSM 7 币种）

### 2.1 估值方法总览

| 估值方法              | 公式/定义                      | 适用场景                  | BDSM 币种映射             |
| ----------------- | -------------------------- | --------------------- | --------------------- |
| **MV=PQ** 货币方程式   | 市值 = 价格 × 交易量              | L1 公链 / Utility Token | ETH, SOL              |
| **DCF** 协议收入折现    | Σ Revenue\_t / (1+r)^t     | DeFi 产生协议费用           | UNI, AAVE             |
| **P/F** 市值/年化费用   | MarketCap / AnnualizedFees | 类似 P/S 相对估值           | UNI, AAVE, CRCL, HYPE |
| **NVT** 网络价值/交易量  | NetworkValue / TxVolume    | 类似 P/E 的效用网络指标        | ETH, SOL              |
| **MC/TVL** 市值/总锁仓 | MarketCap / TVL            | DeFi 资本效率             | AAVE, UNI             |
| **回购销毁率**         | 年化销毁量 / 总供应量               | 通缩机制可持续性              | UNI, HYPE, ETH        |

### 2.2 加密折现率

```
加密折现率 = 基础率(20~30%) + 监管溢价(+5~10%) + 技术风险(+5~10%) + 流动性溢价(+3~8%)
```

远高于传统股票 WACC (8\~10%)。监管溢价（SEC/CFTC 不确定性）、技术风险（智能合约漏洞、分叉）、流动性溢价（24h 成交深度不足）。

### 2.3 BDSM 七信号与估值映射

| 信号 | 名称                           | 估值映射      | 数据源                 |
| -- | ---------------------------- | --------- | ------------------- |
| E1 | revenue\_stability           | DCF 收入稳定性 | DeFiLlama/CoinGecko |
| E2 | mc\_fees\_mean\_reversion    | P/F 均值回归  | DeFiLlama           |
| E3 | tvl\_growth\_momentum        | MC/TVL 动量 | DeFiLlama           |
| E4 | revenue\_quality             | DCF 收入质量  | Odaily/官网           |
| E5 | supply\_shrinkage\_intensity | 回购销毁率     | 原生区块链               |
| E6 | value\_capture\_delta        | 价值捕获变化    | 原生数据                |
| E7 | revenue\_sustainability      | DCF 可持续性  | Uniswap 原生 API      |

**BDS 综合评分**：`BDS = e7 × 0.4 + e6 × 0.3 + e5 × 0.3`

### 2.4 估值区间判定

| 区间      | 判定条件                             | 操作     | 类比             |
| ------- | -------------------------------- | ------ | -------------- |
| **低估区** | BDS ≥ 0.3 且 P/F < 中位数 0.7x       | 启动分批建仓 | 盈利收益率 > 10%    |
| **合理区** | BDS 0.0\~0.3 且 P/F 0.7\~1.5x 中位数 | 持有不加仓  | 盈利收益率 6.4\~10% |
| **高估区** | BDS < 0.0 或 P/F > 中位数 2x         | 分批减仓   | 盈利收益率 < 6.4%   |

***

## 三、BDSM 价值驱动分批建仓策略映射

### 3.1 策略定位

> **注**：下表示 BCRM（技术驱动）与 BDSM（价值驱动）的对比。左列为 BCRM 规则（对比参考），右列为 BDSM 当前生效规则。

| 维度    | BCRM（技术驱动）        | BDSM（价值驱动）                                 |
| ----- | ----------------- | ------------------------------------------ |
| 持仓周期  | 数小时\~数天           | **数周\~数月**                                 |
| 单仓规模  | \~60U / 3x        | **\~167U / 3-5x（2.8x）**                    |
| 子池上限  | 5 仓 × 60U = 300U  | **3 仓 × 167U = 500U**                      |
| 建仓方式  | 一次建仓              | **动态评估器(CVS)驱动分批**                         |
| 止损方式  | 价格止损 (SL 1.5\~3%) | **逻辑止损 + 趋势止损(MA200/MA128 破位)**            |
| SL 机制 | 固定百分比间距           | **趋势反转确认才止损**（容许越跌越买，不因固定跌幅扫损）             |
| 止盈方式  | 固定百分比 TP(3%×杠杆)   | **价值发现驱动**（P/F高估/BDS恶化才卖，不因微涨出场）           |
| 出场触发  | 技术指标 + BCRM 出场    | **基本面拐点 + 趋势反转 + 估值泡沫**（B1\~B5 + MA + P/F） |

### 3.2 动态评估器驱动的分批建仓

> **设计原则**：不用固定百分比跌幅，而是用**双评估器动态计算**加仓时机和力度。低估后要大胆，底部要能"打完子弹"。加密市场节奏快，**按周评估**拐点，出现下跌拐点可分批建仓。

#### 3.2.1 双评估器架构

**A. 基本面评估器（已有 BDS Score）**：`BDS = e7×0.4 + e6×0.3 + e5×0.3`

| BDS Score | 估值判定 | 建仓力度  |
| --------- | ---- | ----- |
| ≥ 0.7     | 极度低估 | 可打完子弹 |
| 0.5\~0.7  | 深度低估 | 加大力度  |
| 0.3\~0.5  | 低估   | 正常建仓  |
| 0.0\~0.3  | 合理   | 持有不加仓 |
| < 0.0     | 高估   | 减仓    |

**B. 技术面评估器（新增）**：综合 RSI、MA200偏离度、成交量异动、ATR扩张四维信号

| 技术指标      | 判定             | 分值   |
| --------- | -------------- | ---- |
| RSI(14)   | < 20 极度超卖      | +1.0 |
| RSI(14)   | 20\~30 超卖      | +0.6 |
| 距MA200偏离度 | < -30%         | +1.0 |
| 距MA200偏离度 | -15%\~-30%     | +0.6 |
| 成交量(20日)  | > 2x 均量（放量）    | +0.4 |
| ATR扩张     | ATR/Price > 5% | +0.3 |

技术面综合分 `TS = min(1.0, 各项之和 / 2.0)`（归一化 0\~1）。**MA200 偏离度字段同时作为趋势止损数据源**（见 §3.3）。

#### 3.2.2 综合估值分（CVS）与动态仓位

```
CVS = BDS × 0.6 + TS × 0.4

ratio = {
    CVS >= 0.8: 1.0    # 打完子弹（剩余全部投入）
    CVS 0.6~0.8: 0.5   # 加大力度（剩余的50%）
    CVS 0.3~0.6: 0.3   # 正常建仓（剩余的30%）
    CVS < 0.3: 0.0     # 不加仓
}
batch_notional = remaining_budget × ratio
```

> **⚠ 对比说明**：下表示固定百分比方案（v1.0，已废弃）与动态评估器方案（v1.3，当前生效）的对照。左列为历史参考，非当前规则。

| 场景                           | 固定百分比方案（已废弃）   | 动态评估器方案（当前生效）           |
| ---------------------------- | -------------- | ----------------------- |
| BDS=0.6, RSI=18（深度低估+超卖）     | 第2批30%（需等跌10%） | CVS=0.68 → **50%大胆加仓**  |
| BDS=0.8, RSI=15, MA200偏离-35% | 第4批15%（需等跌30%） | CVS=0.86 → **100%打完子弹** |

#### 3.2.3 "打完子弹"机制

CVS ≥ 0.8 时：`batch_notional = remaining_budget`（剩余全投），额外确认 BDS≥0.5 + 技术面底部信号 + war\_state≠BLOCK，打完后标记 completed。

### 3.2.4 微仓实盘预算硬上限（v1.4 新增 · BDSM-SPEC-v1.4-003）

> **用户决策**（2026-09-04）：跳过原冷启动影子观察 7 日（仅影子日志、0 真实下单）期，直接进入**小额真实环境测试** — 用 OKX 真实撮合、滑点、部分成交回报校准 BDSM 建仓链路，**但把单币绝对预算从 scaling\_plan 默认 167U 通过 CLI 覆盖到 25U（≈ 15% 标准预算）**，把 3 币最大潜在敞口从 500U 压到 75U，换取真金白银的真实成交反馈。

#### 机制设计

```
remaining_budget_effective = min( scaling_plan.remaining_budget  ← 快照写回默认 167U/币
                                 , bdsm_budget_per_coin          ← CLI --bdsm-budget-per-coin 25 (可为 None 表示不覆盖)
                                 )

batch_notional = remaining_budget_effective × ratio  (ratio 规则见 §3.2.2)
```

**安全属性**：

- **FAIL-OPEN**：`bdsm_budget_per_coin` 解析类型异常 / None → 不覆盖，沿用 `scaling_plan.remaining_budget`（不阻断、不下错误单）

- **全局上限不变**：3 币 × 25U = 75U 仍在 BDSM 子池 500U 预算范围内（§3.1 R5 铁律）

- **退出路径**：见 §5.7 运行模式演进表，满足 10 笔/胜率≥70%/回撤满意 → 移除 CLI 参数恢复默认 167U

#### CLI 开关

| 开关                       | 类型    | 默认值                   | 说明                                                          |
| ------------------------ | ----- | --------------------- | ----------------------------------------------------------- |
| `--bdsm-budget-per-coin` | float | None（不覆盖 = 沿用快照 167U） | 实盘 daemon 传 `25` 激活微仓测试模式；未来稳健阶段可改传 `60` 过渡，或不传（None）回到标准预算 |

#### 实盘实证（2026-09-04 快照 · UNI 估值回调场景）

| 场景          | CLI 参数                      | remaining\_budget\_effective | CVS=0.36 → ratio=0.3 | 实际 batch\_notional |
| ----------- | --------------------------- | ---------------------------- | -------------------- | ------------------ |
| 标准预算（无 CLI） | 省略                          | 167.0 U                      | × 0.3                | **50.1 U**         |
| 微仓测试（当前）    | `--bdsm-budget-per-coin 25` | min(167,25) = 25.0 U         | × 0.3                | **7.5 U** ✅        |
| 稳健过渡        | `--bdsm-budget-per-coin 60` | min(167,60) = 60.0 U         | × 0.3                | 18.0 U             |

### 3.3 止损机制：逻辑止损 + 趋势止损

> **设计原则**：价值投资低于估值时越跌越买，**固定百分比 SL 与此逻辑冲突**（会在加仓过程中扫掉仓位）。改用趋势反转确认才止损，类似 V15 马丁策略 MA200/MA128 思路。**当前 BDSM 不使用固定百分比 SL(8\~15%)，该数值仅作为历史对照出现于 §3.3.2 对比表中。**

#### 3.3.1 三层止损体系（当前生效规则 · v1.4 Fix-I 收紧版）

> **⚠ v1.3→v1.4 变更**：原 v1.3 中「MA128 下穿 MA200（死叉） → 减仓30%」规则过于激进，在价格仍位于 MA200 上方、斜率未转负时容易产生**大量假减仓**（2026-09-04 实盘快照：AAVE/ETH/SOL 三处数值型死叉但价格仍在 MA200 上方，假触发率 3/7 = 43%）。v1.4 改为**三件套齐触发**（BDSM-SPEC-v1.4-001），与 `_compute_trend_stop()` 生产代码 L425-L435 字节等价。

| 层级       | 触发条件（必须全部满足 AND）                                                                                                                                                        | 动作         | 快照键名 (`trend_stop.*`)                                                                       |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------- |
| **逻辑止损** | BDS 从 ≥ 0.3 降至 < 0.0                                                                                                                                                    | 减仓50% → 全出 | — (由价值发现止盈 value\_exit.action 承载)                                                           |
| **逻辑止损** | 协议收入按周评估，连续 2 周下降 > 20%                                                                                                                                                 | 减仓50% → 全出 | —                                                                                           |
| **逻辑止损** | war\_state = BLOCK                                                                                                                                                      | 全出         | —                                                                                           |
| **趋势止损** | **三条件 AND**：`death_cross = True`（MA128 价格 < MA200 价格）**AND** `below_ma200_days ≥ 2`（连续至少 2 天收盘低于 MA200）**AND** `ma200_slope_negative = True`（MA200 斜率转负 — 200 日均线趋势已下行） | 减仓30%      | `death_cross` / `below_ma200_days` / `ma200_slope_negative` / `ma200_price` / `ma128_price` |
| **趋势止损** | `below_ma200_days ≥ 3`（连续至少 3 天收盘低于 MA200）**AND** `ma200_slope_negative = True`（MA200 斜率转负）                                                                             | 减仓50%      | 同上                                                                                          |
| **趋势止损** | `below_ma200_days ≥ 5`（连续至少 5 天收盘低于 MA200）**AND** `ma200_slope_negative = True`                                                                                         | 全出         | 同上                                                                                          |

动作优先级（v1.4 不变）：`full_exit > reduce50 > reduce30 > none`，多条件同时命中取最强者输出到 `trend_stop.action`。

#### 3.3.2 为什么趋势止损而非固定百分比

> **⚠ 对比说明**：下表示固定百分比 SL（v1.0，已废弃）与趋势止损（v1.4 Fix-I，当前生效）的对照。左列为被否决的旧方案，仅用于解释设计理由。

| 维度     | 固定百分比 SL(8\~15%)（已废弃） | 趋势止损 MA200/MA128 · v1.4 Fix-I（当前生效）                    |
| ------ | --------------------- | ------------------------------------------------------ |
| 与越跌越买  | 冲突（扫掉加仓仓位）            | 一致（趋势未反转就继续持有，需 2 日+斜率确认，牛顶假减仓大幅减少）                    |
| 噪音过滤   | 差（单日插针即扫损）            | **极好**（3 信号 AND：死叉 + 连续 2 日破 MA200 + MA200 斜率转负，缺一不触发） |
| 适用周期   | 短线                    | **大周期大资金**（BDSM定位 · 数周\~数月）                            |
| 历史假信号率 | 中（30%\~50%）           | **v1.3: 43%（3/7）→ v1.4 Fix-I 后：0%（2026-09-04 实盘快照）**   |

**爆仓安全底线**（硬约束，v1.4 不变）：SL 仍设爆仓价+0.3%缓冲；趋势止损触发时 SL 参考价设在 MA200 价附近；冲突时爆仓安全优先。

### 3.4 止盈管理：价值发现驱动

> **设计原则**：价值投资**不设固定百分比止盈**。巴菲特明确反对"因获利而卖出"（"华尔街最愚蠢的格言"）。当前 UNI 走了 BCRM 固定百分比 TP（涨6%即出场），与数周\~数月持仓周期和价值投资定位完全矛盾。

#### 3.4.1 巴菲特卖出三原则（调研结论）

| 原则            | 触发条件       | BDSM 映射             |
| ------------- | ---------- | ------------------- |
| **① 基本面永久恶化** | 护城河摧毁/收入连降 | BDS 恶化 + 协议收入按周评估连降 |
| **② 价格极端泡沫**  | 价格远超内在价值   | P/F 进入高估区(>1.5x中位数) |
| **③ 更好的机会**   | 有更高性价比标的   | 子池另一币 BDS 更高(Δ≥0.3) |

#### 3.4.2 三层止盈体系（当前生效规则）

| 层级          | 触发条件                           | 动作             |
| ----------- | ------------------------------ | -------------- |
| **估值回归止盈**  | P/F 从低估(<0.7x)回归合理区(0.7\~1.5x) | 持有不加仓（不卖）      |
| **估值高估止盈**  | P/F 进入高估区(>1.5x中位数)            | 分批减仓30%        |
| **估值极端泡沫**  | P/F > 2x中位数 或 BDS < 0.0        | 减仓50%→全出       |
| **基本面拐点止盈** | BDS 从 ≥0.3 降至 < 0.0            | 减仓50%→全出       |
| **收入拐点止盈**  | 协议收入按周评估，连续2周下降>20%            | 减仓50%→全出       |
| **趋势止盈**    | 价格远超MA200(>+30%) + RSI>70      | 分批减仓30%        |
| **机会成本止盈**  | 子池另一币种 BDS 更高(Δ≥0.3)           | 置换（卖出→买入更高BDS） |

**TP 挂单处理**：BDSM 仓位仍设 OKX 端 TP 挂单（黑天鹅兜底），但不用 BCRM 的 3%×杠杆固定间距，改设 P/F 高估区对应价或 MA200 上方+30%。

### 3.5 加仓前置检查清单

每次加仓前必须通过以下检查（FAIL-OPEN 设计）：

1. ✅ 当前持仓中该币种 source\_tag=bdsm
2. ✅ BDSM 子池仓位数 < 3
3. ✅ CVS ≥ 0.3（动态评估器达标）
4. ✅ BDS Score 仍在低估区（≥ 0.0，CVS≥0.8 打完子弹需 BDS≥0.5）
5. ✅ 宏观 war\_state = ALLOW
6. ✅ 可用资金 ≥ 目标加仓金额
7. ✅ 当前持仓未触发任何 B1\~B5 出场信号
8. ✅ 未触发趋势止损（MA200未破位/MA128未死叉）
9. ✅ 距上次加仓 ≥ 最小间隔时间（4 小时，防瞬时波动反复触发）

***

## 四、GitHub 参考项目调研

### 4.1 DCAi (cerebrux/DCAi) — 最具参考价值

| 维度          | 内容                                                       |
| ----------- | -------------------------------------------------------- |
| **定位**      | 机器学习驱动的 DCA 框架                                           |
| **核心算法**    | KNN 模式识别 + 三层决策引擎（Pullback/Oversold/Fear）                |
| **仓位缩放**    | 指数级缩放（Rho 参数）：跌得越深，买入越多                                  |
| **Rho 参数**  | Rho=1.7（加密默认），Rho=2.5（指数默认）                              |
| **预算管理**    | Savings Pot（储蓄罐）预算结转机制                                   |
| **自适应**     | 自动校准 4 类资产（加密/股票/指数/商品）                                  |
| **公式**      | `Multiplier = (MinMult + k × (DCA线 - Ahr999)² / Ahr999)` |
| **BDSM 借鉴** | ✅ Rho 指数缩放 → BDSM 分批仓位比例可参考；✅ Savings Pot → BDSM 子池预算管理  |

### 4.2 dca-crypto-bot (CodingCryptoTrading) — VariableAmount 模式

| 模式                 | 逻辑                       |
| ------------------ | ------------------------ |
| Classic            | 固定金额买入（传统 DCA）           |
| BuyBelow           | 价格低于阈值才买                 |
| **VariableAmount** | **价格范围映射到金额范围，价格越低买入越多** |

**VariableAmount 实现**：指数或线性函数，将 \[价格下限, 价格上限] 映射到 \[最小金额, 最大金额]。价格超出范围则不买或饱和。

**BDSM 借鉴**：✅ VariableAmount → BDSM 动态评估器(CVS)→加仓比例的映射函数

### 4.3 btc-enhanced-dca (Eumenides-K) — Ahr999 增强

| 维度       | 内容                                            |
| -------- | --------------------------------------------- |
| **核心指标** | Ahr999 指标（200日定投线 + 恐慌线）                      |
| **投资倍数** | `倍数 = (最小倍数 + k × (DCA线 - Ahr999)² / Ahr999)` |
| **范围**   | 0.1x \~ 4.0x（可配置）                             |
| **执行**   | OKX API 市价买单                                  |
| **部署**   | GitHub Actions 每日运行                           |

**BDSM 借鉴**：✅ Ahr999 指标思路 → BDS Score 作为类似 Ahr999 的估值锚；✅ 倍数公式 → CVS 动态加仓比例计算

### 4.4 trading-bot (EliasAbouKhater) — Regime-aware 再平衡

| 维度        | 内容                          |
| --------- | --------------------------- |
| **牛熊检测**  | SPY 200日 SMA                |
| **再平衡频率** | Bull → 季度，Bear → 月度         |
| **DCA**   | 月度定投，按比例分配                  |
| **可插拔策略** | MA crossover / grid / pairs |

**BDSM 借鉴**：✅ Regime-aware → war\_state 宏观检查；✅ 200日 SMA → MA200 趋势止损参考

### 4.5 参考项目对比总结

| 项目               | 分批缩放             | 估值驱动         | 预算管理          | 宏观感知         | 与 BDSM 相关度 |
| ---------------- | ---------------- | ------------ | ------------- | ------------ | ---------- |
| DCAi             | ✅ 指数 Rho         | ✅ KNN+Ahr999 | ✅ Savings Pot | ✅ 4类资产自适应    | **★★★ 高**  |
| dca-crypto-bot   | ✅ VariableAmount | ❌ 价格驱动       | ❌             | ❌            | ★★ 中       |
| btc-enhanced-dca | ✅ 倍数公式           | ✅ Ahr999     | ❌             | ❌            | ★★ 中       |
| trading-bot      | ❌ 固定 DCA         | ❌ 再平衡驱动      | ❌             | ✅ SPY 200SMA | ★ 低        |

***

## 五、结合项目实现的综合评估方案

### 5.1 当前项目 BDSM 架构概述

```
bdsm_snapshot_writer.py (每日快照)
├── _build_coin_entry()          → 单币计算：E5/E6/E7 → BDS Score → direction/cap/exit
├── _compute_direction()        → 方向约束：score>0.3→LONG / score<-0.3→SHORT / else NEUTRAL
├── _compute_cap_multiplier()    → 仓位上限 = score_cap × rank_cap × dq_cap（一次性 cap）
├── _detect_exit_action()        → B1~B5 基本面出场触发
└── write_snapshot()             → 原子写入 bdsm_snapshot_{YYYYMMDD}.json

polling_trader.py (交易执行)
├── gap1 (L10365)  → 方向硬约束：BDSM 方向覆盖 BCRM
├── gap2 (L10808)  → 仓位 MIN：position_usdt × cap_multiplier（一次性缩放）
│   └── _apply_bdsm_cap_multiplier()  → 纯函数 MIN(base, base×cap)
└── gap3 (L11999)  → 出场 OR：BDSM 出场优先于 BCRM
    └── _bdsm_check_exit_actions()    → 检查 B1~B5 触发
```

### 5.2 当前实现 vs 动态评估策略差距分析

| 维度              | 当前实现                     | 动态评估策略                 | 差距   | 改动量 |
| --------------- | ------------------------ | ---------------------- | ---- | --- |
| 建仓方式            | **一次性** cap=0.175 → 100U | 动态CVS驱动 不等固定跌幅         | 核心差距 | 中   |
| cap\_multiplier | 一次性缩放系数                  | CVS动态ratio+已建仓位感知      | 核心   | 中   |
| 技术面评估           | 无                        | RSI+MA200偏离+成交量+ATR    | 新增   | 中   |
| 综合估值分           | 仅有BDS                    | CVS=BDS×0.6+TS×0.4     | 新增   | 小   |
| 止损方式            | 无（依赖BCRM SL）             | 逻辑止损+趋势止损(MA200/MA128) | 新增   | 中   |
| 止盈方式            | BCRM固定百分比TP(涨6%即出场)      | 价值发现驱动(P/F高估/BDS恶化才卖)  | 核心差距 | 中   |
| 加仓触发            | 无                        | CVS≥0.3即触发             | 核心   | 中   |
| 评估周期            | 无                        | 按周(2周)                 | 新增   | 小   |

### 5.3 落地方案

#### Phase 0：快照结构 + 实盘字段写回

**目标**：在快照中新增动态评估字段 + 实盘 `_apply_bdsm_scaling` 消费端读取路径打通（v1.4 已从「Shadow 模式」演进为「微仓实盘测试」，见 §5.7）

**改动文件**：`bdsm_snapshot_writer.py` · `polling_trader.py` · `start_daemon.py`

1. **快照 schema（v1.4 权威 · 与实际快照字节对齐 · BDSM-SPEC-v1.4-002）**：

```python
# _build_coin_entry() 返回值新增；顶层 + 4 嵌套对象键名与生产代码完全一致
{
    # ====== 顶层字段（消费端 PollingTrader._apply_bdsm_scaling / _bdsm_check_exit_actions 直接读取）======
    "ts_score": 0.0,                # ★ 顶层 alias（等价 technical_assessment.ts_score）
    "cvs": 0.0,                      # 综合估值分 = BDS×0.6 + TS×0.4
    "cvs_ratio": 0.0,                # 动态仓位比例：CVS<0.3→0 / 0.3~0.6→0.3 / 0.6~0.8→0.5 / ≥0.8→1.0
    "valuation_percentile": 50.0,   # 估值百分位 0~100（MA200偏差×2+50 截断；>90触发full_exit；<50=低估安全区）
    "direction_constraint": "LONG_ONLY",  # 策略方向约束
    "bds_score": 0.0,                # BDSM基本面分（来自 coin_fundamental_ranker）
    "cap_multiplier": 0.0,           # BDSM 传统 cap 乘法兜底（FAIL-OPEN 时才用）
    "phase": "P2_REVENUE_GROWTH",   # 阶段判定：P1_EXPECTATION / P2_REVENUE_GROWTH / P3_EUPHORIA / P4_CRASH
    "exit_action": "hold",          # 强出场行动 (hold / reduce50 / full_exit)
    "exit_triggers": [],             # 出场触发原因

    # ====== 嵌入对象 1：technical_assessment ======
    # 消费端读取键（PollingTrader / 3 层回归 UT）→ 必须严格使用下列键名，别名不生效
    "technical_assessment": {
        "rsi_14": 50.0,              # RSI(14) 相对强弱指数 0~100
        "ma200_deviation": 0.0,      # (price - MA200)/MA200 * 100%   正值=泡沫，负值=低估 (spec §2.4)
        "ma200_slope": 0.0,          # MA200 斜率（日级变动率 ×100%；正=均线上升，负=均线下行）
        "volume_ratio": 1.0,         # 成交量 / 20 日平均成交量比；>1.5 放量
        "atr_pct": 0.0,              # ATR(14) / 收盘价 × 100%   波动率百分比
        "ts_score": 0.0,             # 技术面综合分 0~1；(与顶层 ts_score 值完全相同，向后兼容)
    },

    # ====== 嵌入对象 2：scaling_plan ======
    # v1.4 实际键名 (非 batches/total_budget；分批节奏由 CVS ratio 动态决定，非固定百分比)
    "scaling_plan": {
        "target_notional_usdt": 167.0,      # 单币目标名义仓位 167U (R5·3×167=500U子池)
        "remaining_budget": 167.0,          # 剩余可用预算；CLI --bdsm-budget-per-coin 会取 min 覆盖
        "accumulated_notional": 0.0,        # 已建仓名义金额（累计投入）
        "accumulated_margin": 0.0,          # 已占用保证金（3x~5x 杠杆）
        "completed": False,                 # 是否已「打完子弹」(remaining_budget 基本耗尽 or CVS≥0.8 一次全投)
        "avg_entry_price": 0.0,             # 加权平均入场价（加权按 accumulated 计）
    },

    # ====== 嵌入对象 3：trend_stop · v1.4 Fix-I 三件套规则 ======
    "trend_stop": {
        "ma200_price": 0.0,                 # MA200 参考价（当日收盘平滑）
        "ma128_price": 0.0,                 # MA128 价格
        "below_ma200_days": 0,              # 连续多少个 1D 收盘价 < MA200；§3.3.1 阈值=2/3/5
        "ma200_slope_negative": False,      # MA200 斜率是否转负；Fix-I 三件套 AND 条件之一
        "death_cross": False,               # MA128.price < MA200.price 且上一日 >= MA200（死叉信号）；Fix-I 三件套之一
        "action": "none",                   # none / reduce30 / reduce50 / full_exit ；优先级取最大
    },

    # ====== 嵌入对象 4：value_exit ======
    "value_exit": {
        "pf_percentile": 50.0,              # 估值百分位(0~100)；直接复用顶层 valuation_percentile 的原始数据源
        "pf_overvalued": False,             # pf_percentile > 80；触发 reduce30
        "pf_bubble": False,                 # pf_percentile > 90；触发 full_exit
        # bds_collapse：逻辑止损触发 (bds_score < 0 → full_exit)；实现存在 _compute_value_exit 内
        # 快照中不单独写 bds_collapse 键名，通过读取顶层 bds_score < 0 等价推导
        "action": "none",                   # none / reduce30 / reduce50 / full_exit
    },
}
```

> **向后兼容说明**（v1.3→v1.4 迁移）：v1.3 示例中出现但快照实际未写入的旧别名（`ma200_dev_pct`、`rsi`、`atr_ratio`、`batches`、`total_budget`、`min_entry_interval_hours`、`below_ma200_streak`、`bds_collapse` 单独键）**不生效**；消费端 PollingTrader 只读取上表列出的新键名。UT（97 GREEN）和实盘（7 Check 全过）是权威验证。

1. 新增 4 个计算函数（Phase 0 真实写入）：

   - `_compute_technical_assessment(coin, price_history)` → `technical_assessment` 6 字段

   - `_compute_cvs(bds_score, ts_score)` → `(cvs, cvs_ratio)`

   - `_compute_trend_stop(coin, price_history)` → `trend_stop`（§3.3.1 v1.4 Fix-I 三件套）

   - `_compute_value_exit(bds_score, valuation_percentile)` → `value_exit`

2. **FAIL-OPEN 兜底**：快照 `_build_coin_entry` 末尾任何异常 → `_neutral_coin_entry()` 返回，顶层 `cvs=0 / ts_score=0 / trend_stop=none / value_exit=none / scaling_plan=167U默认`。`_apply_bdsm_scaling` 首段 `CVS < 0.3 → fallback cap_mult` 直接走 BDSM 旧 cap 乘法逻辑 = 无加仓动作。

#### Phase 1：动态分批执行（改 gap2）已升级（v1.4 P0-A2 实盘版）

**目标**：`_apply_bdsm_cap_multiplier` 升级为 `_apply_bdsm_scaling`

**改动文件**：`polling_trader.py`

```python
def _apply_bdsm_scaling(self, coin, position_usdt, current_price):
    """动态评估驱动的分批建仓。"""
    snap = self._get_bdsm_snapshot_today()
    coin_entry = snap.get("coins", {}).get(coin, {})

    cvs = float(coin_entry.get("cvs", 0.0))
    ratio = float(coin_entry.get("cvs_ratio", 0.0))
    plan = coin_entry.get("scaling_plan", {})

    if not plan or cvs < 0.3:
        # FAIL-OPEN：CVS不达标 → 回退原cap逻辑
        return self._apply_bdsm_cap_multiplier(coin, position_usdt)

    accumulated = self._get_bdsm_accumulated_position(coin)
    remaining = plan.get("remaining_budget", 167.0) - accumulated

    if remaining <= 0:
        return 0.0, 0.0, "bdsm_scaling_completed"

    batch_notional = remaining * ratio

    # "打完子弹"
    if cvs >= 0.8:
        batch_notional = remaining

    return batch_notional, 1.0, f"bdsm_cvs_{cvs:.2f}_ratio_{ratio:.1f}"
```

gap2 调用点修改：

```python
# 原：_bdsm_pos, _bdsm_cap, _bdsm_cap_tag = self._apply_bdsm_cap_multiplier(coin, position_usdt)
# 改为：
_bdsm_pos, _bdsm_cap, _bdsm_cap_tag = self._apply_bdsm_scaling(coin, position_usdt, current_price)
```

#### Phase 2：趋势止损 + 价值发现止盈

**目标**：BDSM 仓位使用趋势止损(MA200/MA128) + 价值发现止盈，替代固定百分比 SL/TP

**改动文件**：`polling_trader.py` gap3 出场巡检 + SL/TP 设置段

1. 趋势止损检查（gap3 新增）：读取 `trend_stop.action` → reduce50/reduce30/full\_exit
2. 价值发现止盈检查（gap3 新增）：读取 `value_exit.action` → reduce30/reduce50/full\_exit
3. SL 设置改为 MA200 参考价（非固定 8\~15%，该数值为 v1.0 历史方案，已废弃）；爆仓安全底线仍为硬约束
4. **TP 设置改为价值发现驱动**（核心）：BDSM 仓位不用 BCRM 的 `tb_tp_min_pct=0.06`；TP 挂单设 P/F 高估区对应价或 MA200 上方+30%

#### Phase 3：回测验证 + 生产上线

1. 回测 30 日 A/B：A组一次性+固定TP vs B组动态CVS+价值发现止盈
2. 验收：MDD ≤ 120% 纯BCRM、反向丢弃率 ≤ 15%、胜率 ≥ 90%
3. 通过后 `enable_bdsm_value_scaling = True`

### 5.4 风险评估

| 风险           | 概率 | 影响        | 缓解措施                 |
| ------------ | -- | --------- | -------------------- |
| 动态评估期间基本面恶化  | 中  | 仓均成本偏高    | 每批检查 BDS             |
| 技术面指标滞后      | 中  | 加仓/止损时机偏移 | RSI+MA200+成交量多维确认    |
| 资金占用时间拉长     | 高  | 机会成本      | 子池预算上限 500U 硬约束      |
| 代理/网络中断      | 低  | 错过加仓      | FAIL-OPEN 不影响已有仓位    |
| "打完子弹"判断失误   | 中  | 底部下方再跌    | 趋势止损(MA200)兜底        |
| MA200 趋势止损滞后 | 中  | 止损偏晚      | 叠加 MA128 死叉+逻辑止损多层保护 |
| 价值发现止盈过晚     | 中  | 利润回吐      | P/F 高估区+趋势止盈双确认      |

### 5.5 改动影响面

| 文件                        | 改动类型          | 影响范围                          |
| ------------------------- | ------------- | ----------------------------- |
| `bdsm_snapshot_writer.py` | 新增字段+函数       | 快照 schema 扩展（向后兼容）            |
| `polling_trader.py` gap2  | 修改调用+新增方法     | BDSM 子池开仓逻辑（BCRM 不受影响）        |
| `polling_trader.py` gap3  | 新增趋势止损+价值发现止盈 | 仅 BDSM 标签仓位                   |
| `polling_trader.py` SL/TP | 条件分支          | 仅 BDSM 标签仓位（MA200参考价+价值发现TP）  |
| 新增 UT                     | TDD           | test\_bdsm\_value\_scaling.py |

### 5.6 验收标准（v1.4 · 实际结果已落地）

1. **TDD**：`test_bdsm_value_scaling.py`（31 条，其中 v1.4 新增 2 条微仓硬上限 RED→GREEN） + `test_bdsm_phase0_snapshot.py`（66 条，包含 FAIL-OPEN neutral / 快照字段 / Phase 0 回写）
   实际覆盖清单 = 以下全部 **已验证 GREEN ✓**：

   - 动态评估器（CVS=BDS×0.6+TS×0.4 / ratio 映射 CVS<0.3→0, 0.3~~0.6→0.3, 0.6~~0.8→0.5, ≥0.8→1.0）

   - 打完子弹（CVS≥0.8 剩余全投）

   - 已建仓位感知（accumulated 扣减 remaining，建满后 bdsm\_scaling\_completed 返回 0）

   - BDS 恶化时停止加仓（逻辑止损 + war\_state BLOCK 拦截）

   - §3.5 前置 9 条检查（5 条 P0-A2 实盘实现：CVS≥0.3 / BDS≥0 / war=ALLOW / VE非极端 / TS=none / 隔日 ≥1 日）

   - 趋势止损触发 v1.4 Fix-I（MA200破位3日/5日 + MA斜率 负，死叉需 3 条件 AND）

   - 价值发现止盈触发（P/F 高估>80→reduce30, >90→full\_exit, BDS<0→full\_exit）

   - **v1.4 新增**：bdsm\_budget\_per\_coin 硬上限 25U / 60U 覆盖 scaling\_plan 默认（含 None 不覆盖基准）

   - FAIL-OPEN：快照缺失 / 类型异常 → 回退 cap\_mult

   - 向后兼容：旧版无 cvs/scaling\_plan 字段时走 cap\_mult 旧逻辑

2. **回归**：实际执行（2026-09-04）= **97/97 UT GREEN 零回归**（test\_bdsm\_value\_scaling.py 31 + test\_bdsm\_phase0\_snapshot.py 66）

   ```
   cd 11-易经推理系统
   PYTHONPATH="$PWD:$PWD/scripts/memory_l4:$PWD/scripts/memory_l4/force_vector" \
     python3 -m pytest tests/test_bdsm_phase0_snapshot.py \
                     tests/test_bdsm_value_scaling.py \
           -q --tb=short --import-mode=importlib
   # 结果: 97 passed in 4.2s
   ```

3. **冒烟（Phase 0）**：daemon PID=24799 实际 18h40m 运行快照：

   - 出场巡检（`_bdsm_check_exit_actions`）**195 次周期触发**（≈每 tick 1 次）

   - 快照 FAIL-OPEN = 0/7 币；**7 币 CVS 全为真实值（CRCL 中性兜底属设计行为）**

   - 今日 7 币 §3.5 前置 0 通过 = 自然等待窗口，非异常

4. **实盘链路（v1.4 替代原 Shadow 7 日方案）**：

   - 状态 = **微仓实盘测试进行中**（`--bdsm-budget-per-coin 25` + 无 `--shadow-mode`）

   - BDSM 首笔信号实证（UNI 估值回落至 VE=none 场景）：**167U→25U CLI 覆盖 → batch=7.5U** 已通过最小 trader 构造校验 ✓

   - 启动参数 10/10 断言通过（微仓 25U ✓，影子模式移除 ✓，Phase1 3 开关 ✓，方案 C 5 开关 ✓）

   - 3 ERROR 级日志归因（非 BDSM：BCRM PUMP 离场 / XAU SKHYNIX K线偶发失败），BDSM 链路 0 ERROR

### 5.7 运行模式演进路径（v1.4 新增 · 冷启动影子→微仓实盘→标准实盘 · BDSM-SPEC-v1.4-003）

> 设计原则（认知经验 2340055「回测/实盘双模式差异抽象」）：
> 环境差异开关必须通过**单一显式变量**控制（CLI 参数或运行模式枚举），禁止在核心决策函数中写 `if shadow_mode` 硬分叉。
> 本 BDSM 用 `shadow_mode (True/False)` × `bdsm_budget_per_coin (None / 25U / 60U)` 2 个正交变量覆盖 3 种模式。

| 模式名称                                        | shadow\_mode | bdsm\_budget\_per\_coin             | 说明                                                                                                    | 进入前提                 | 退出条件                                                  |
| ------------------------------------------- | ------------ | ----------------------------------- | ----------------------------------------------------------------------------------------------------- | -------------------- | ----------------------------------------------------- |
| **Phase 0 影子冷启动**（原 v1.3 设计）                | True         | None                                | 不产生任何真实下单，仅写 ShadowLogger 12 字段结构化日志 + 战略缓存中性化。用于代码链路跑通 / 快照结构 / CVS ratio 回归。                        | daemon 首次上线前         | 7 日影子日志、快照真实值 7/7 币覆盖 → 转入下一模式                        |
| **Phase A 微仓实盘测试**（当前 v1.4 = 用户 2026-09 选择） | False        | **25U**（CLI 显式注入）                   | 真实 OKX 撮合 / 真实滑点 / 真实持仓标签。5 重前置检查（§3.5）+ FAIL-OPEN + 25U 三重兜底。最大敞口 3×25 = **75U** ≈ R5 预算 500U 的 15%。 | Phase 0 通过，用户跳过或完成   | 累计 10+ 笔完整 BDSM 交易（入+出闭环） + 胜率≥70% + 回撤 ≤ 原 BCRM 120% |
| **Phase B 稳健过渡**（可选）                        | False        | **60U**（建议）                         | 小帽松绑 2.4×。UNI 标准批次 50.1U → 60×0.3=18U，覆盖波动但仍低于标准预算。                                                   | Phase A 胜率稳定         | 观察 10+ 笔 / 胜率 ≥ 70%                                   |
| **Phase C 标准实盘**（BDSM 默认稳态）                 | False        | **None**（不注入，沿用 scaling\_plan 167U） | R5 铁律运行。标准批次：CVS=0.36 → 167×0.3 = **50.1U / 币**。最大敞口 3×167 = 500U。                                    | Phase A/B 达标，或用户显式决策 | 除非策略框架改版（v2.0+）                                       |

**启动命令对照**：

```bash
# —— Phase 0 影子冷启动（v1.3 原方案；当前已不再执行，保留作故障回退）——
python3 start_daemon.py # (内部 cmd 需含 --shadow-mode)

# —— Phase A 微仓实盘（v1.4 当前生产 · 2026-09-04 生效）——
# start_daemon.py L43 注入:
"--bdsm-budget-per-coin", "25"   # 单币25U硬上限
# 移除: "--shadow-mode"            # 允许真单

# —— Phase C 标准实盘（稳态）——
# 删除 start_daemon.py 中 "--bdsm-budget-per-coin", "25" 行即可（bdsm_budget_per_coin=None → 沿用快照 167U）
```

**冷启动 7 日影子期 被用户显式跳过原因（2026-09-04 决策记录）**：

1. 当前快照 7 币在 §3.5 前置检查下 0 通过 → 即使开启实盘也 0 动作 = 天然等待窗口 ≈ 0 成本影子期
2. 影子日志只记录 `_shadow` 字段，不含 OKX 真实撮合/滑点/部分成交回传信息，**小额真实下单反而反馈更完整**
3. 25U × 3 = 75U 最大敞口在 BDSM 预算 500U 的 15% 以内，**比模拟交易真实且损失可控**
4. 97/97 UT 已覆盖所有核心决策路径（CVS / ratio / 前置 9 条 / TS VE / FAIL-OPEN），**核心算法正确性不依赖实盘观察**
5. 一旦发生偏差，仍可一键热切换回 Phase 0：在 start\_daemon.py 加回 `--shadow-mode` 再重启 daemon

***

## 附录 A：参考来源

- 格雷厄姆《聪明的投资者》(1949)

- 巴菲特致股东信 (1957\~2024)

- Vanguard "Cost Averaging: Invest Now or Temporarily Hold Your Cash?" (2012)

- [DCAi - GitHub](https://github.com/cerebrux/DCAi)

- [dca-crypto-bot - GitHub](https://github.com/CodingCryptoTrading/dca-crypto-bot)

- [btc-enhanced-dca - GitHub](https://github.com/Eumenides-K/btc-enhanced-dca)

- [trading-bot - GitHub](https://github.com/EliasAbouKhater/trading-bot)

- [Mefai Autotrade - GitHub](https://github.com/mefai-dev/mefai-autotrade)

- [DCA Bot Configuration Guide](https://theledgermind.com/dca-bot-configuration-guide/)

***

## 附录 B：版本变更对照表

### B-1. 总体演进：v1.0 → v1.3 → v1.4

> **⚠ 参考说明**：v1.0 为已废弃的「固定百分比建仓 + 固定百分比 SL/TP」方案（保留作历史对比）；v1.3 为「动态评估器 + 价值驱动建仓」稳定基线；**v1.4 为当前实盘生效版本**（2026-09-04 冷启动评估后落地，3 条增量修订 BDSM-SPEC-v1.4-001/002/003）。

| 变更项                | v1.0（废弃）              | v1.3（基线）                                                                                                  | v1.4（当前实盘 · 2026-09-04 生效）                                                                                                                                         |
| ------------------ | --------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **建仓触发**           | 固定跌幅 10%/20%/30%      | 动态评估器 `CVS ≥ 0.3`                                                                                         | 与 v1.3 一致，补充 §3.5 前置检查 9 条（实际实盘 6 条可判定）在 scaling 入口拦截                                                                                                              |
| **加仓力度**           | 固定批次 30/30/25/15%     | `CVS ratio` (0.3/0.5/1.0)                                                                                 | 与 v1.3 一致，新增 **CLI 硬上限** `--bdsm-budget-per-coin` 对 remaining\_budget 做 `min(plan, CLI)` 覆盖；当前生产 25U → 批次从 50.1U/币 → 7.5U/币 锁仓 15%                                 |
| **技术面评估**          | 无                     | TS 评估器（RSI/MA200/成交量/ATR）                                                                                 | 与 v1.3 一致；键名规范澄清：`rsi_14 / ma200_deviation / atr_pct / ts_score`（旧别名 rsi / ma200\_dev\_pct / atr\_ratio 不生效，统一用 §5.3 Phase0 权威命名）                                  |
| **趋势止损**           | 固定百分比 SL(8\~15%)      | `MA128 死叉 → reduce30`；`MA200 破 3日/5日 + 斜率负 → reduce50 / full_exit`                                        | **Fix-I 收紧三件套（43%→0%假信号）**：`reduce30` 必须同时满足 `death_cross AND below_ma200_days≥2 AND ma200_slope_negative=True`；reduce50/full\_exit 仍需 `MA200 斜率负` 前提              |
| **止盈方式**           | BCRM 固定 TP 6% 出场      | 价值发现驱动（P/F 高估 80%→reduce30 / 90%→full\_exit / BDS<0→full\_exit）                                           | 与 v1.3 一致；键名规范澄清：`pf_percentile / pf_overvalued / pf_bubble`；`bds_collapse` 不再单独写键，读取顶层 `bds_score<0` 等价推导                                                         |
| **评估周期**           | 季度 (2季度)              | 按周 (2周)                                                                                                   | 与 v1.3 一致（加密 2 周 ≈ 传统 1 季度时间密度）                                                                                                                                    |
| **快照 JSON Schema** | 无（旧 BDSM 仅 cap\_mult） | v1.3 定义 skeleton 但嵌套键名语义化（`total_budget / batches / rsi / below_ma200_streak / bds_collapse`），与生产快照存在别名漂移 | **权威命名对齐（BDSM-SPEC-v1.4-002）**：4 嵌套对象统一采用生产快照实际键名（`target_notional_usdt / rsi_14 / ma200_deviation / below_ma200_days / pf_percentile` 等）；消费端 PollingTrader 仅承认新命名 |
| **冷启动模式**          | 无                     | Shadow 模式 7 日影子日志 + 0 真实下单                                                                                | **用户决策跳过（BDSM-SPEC-v1.4-003）** → **Phase A 微仓实盘测试**：`shadow_mode=False + bdsm_budget_per_coin=25U/币`，等 10+ 笔完整交易 + 胜率≥70% + 回撤达标 → 松绑到 60U → 移除 CLI 恢复 167U 标准     |
| **验收结果**           | 否决                    | 原 29 UT GREEN（shadow 验收）                                                                                  | **97/97 UT GREEN**（31+66 两文件）+ 18h40m daemon 实盘证据：启动参数 10/10 断言通过 / 出场巡检 195 次周期命中 / BDSM 链路 0 ERROR / 今日快照 7 币 FAIL-OPEN 已完全退出（CRCL 中性兜底属设计行为，非异常）                |

### B-2. v1.3 → v1.4 增量修订（3 条 · 每条单独追踪编号）

| 编号                     | 章节                          | 修订内容                                                                                                   | 风险                                                  | 触发原因                                                                                                      |
| ---------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **BDSM-SPEC-v1.4-001** | §3.3.1 趋势止损规则表              | `MA128死叉` 独立触发 reduce30 → 收紧为 `死叉 + below_ma200_days≥2 + MA斜率转负` 3条件 AND 触发 reduce30                   | 低（降低假减仓率 43%→0%，不影响已触发场景）                           | 2026-09-04 实盘 snapshot 核查 Check5 发现 3/7 币数值型死叉但 MA200 仍在上升期 / 价格未破 MA200                                  |
| **BDSM-SPEC-v1.4-002** | §5.3 Phase0 快照 JSON + 附录 B  | 4 嵌套对象键名从「语义化名」切换到生产快照实际生成键名；补充向后兼容说明与旧别名黑名单                                                           | 中（消费端代码不用改；本 spec 是文档侧对齐。UT 97 GREEN 已验证）           | 核查脚本 Check2 因 spec 示例中 rsi / ma200\_dev\_pct / total\_budget / below\_ma200\_streak 等旧键名产生「字段缺失」误报，实际键值等价 |
| **BDSM-SPEC-v1.4-003** | §3.2.4 微仓实盘预算 + §5.7 运行模式演进 | 新增 CLI `--bdsm-budget-per-coin` / 新增 4 阶段模式矩阵（Phase0 影子 → PhaseA 微仓25U → PhaseB 过渡60U → PhaseC 标准167U） | 低（FAIL-OPEN：解析异常/None → 不覆盖沿用 167U；R5 预算 500U 铁律未变） | 用户 2026-09-04 显式决策：跳过 7 日影子期，直接小额真实环境以获 OKX 真实撮合反馈（自然 0 信号 + 25U 硬上限制约下风险 ≤ 75U）                          |

### B-3. 实盘运行快照（2026-09-04 · v1.4 首次生产验证）

| 指标                | 值                                               | 说明                                                                              |
| ----------------- | ----------------------------------------------- | ------------------------------------------------------------------------------- |
| **daemon PID**    | 24799（运行 18h40m）                                | guardian PID 文件匹配 ✓，心跳阈值 900s ✓                                                 |
| **启动注入**          | `--bdsm-budget-per-coin 25` + 无 `--shadow-mode` | Phase A 微仓 ✓；Phase1/C方案 C 9 开关全注入 ✓                                             |
| **UT 回归**         | 97 passed in 4.2s                               | test\_bdsm\_value\_scaling 31 + test\_bdsm\_phase0\_snapshot 66 = 97 GREEN ✓    |
| **出场巡检命中**        | 195 次（≈每 300s tick 1 次）                         | 7 Check 的 Check6 周期巡检验证 ✓                                                       |
| **BDSM ERROR 日志** | 0 条                                             | 3 条 ERROR 级日志非 BDSM 归因（BCRM PUMP 离场 + XAU/SKHYNIX K 线偶发失败） ✓                    |
| **今日 §3.5 前置**    | 7/7 币被拦截                                        | 0 BDSM 动作 = 天然安全等待窗口，非异常                                                        |
| **最大潜在敞口**        | 3 × 25U = 75U                                   | BDSM 子池 500U 的 15%（未来 10 笔达标后提升至 180U → 500U）                                   |
| **首笔信号链路验证**      | 7.5U（UNI 估值回落场景）                                | CLI 25U × CVS=0.36 ratio=0.3 → 实测最小 trader 构造 `_apply_bdsm_scaling()` 返回 7.5U ✓ |

