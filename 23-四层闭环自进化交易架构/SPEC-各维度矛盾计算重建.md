# SPEC · 各维度矛盾计算重建（真实市场维度）
> **版本**: v0.4 | **日期**: 2026-11-14 | **状态**: 八维多信号合成架构已落地并云端验证
> **v0.4 变更**: 维度从 4 维扩展至 8 维（D1/D2/D3/D4/C6/C7/C8/NEWS），每维从单信号升级为多信号等权/加权合成；充分利用 19 域 mm_metrics 与 40 域 cross_asset_matrix 及云端 FRED 宏观序列。所有维度 FAIL-OPEN 降级，已云端部署验证。
> **v0.3 变更**: 实测确认 18 采集中心已有 macro 484 条（CPI/PPI/FEDFUNDS/T10Y2M/WALCL/FOMC）与 finance 4164 条（BTC/VIX/SPY/GLD）——D1 数据已采集，问题为 18→19 同步链路未打通；T2a 改为同步为主、新采集为辅
> **模块**: 23-四层闭环自进化交易架构 / `dreambuddy_evolution`，数据依赖 19-数据访问层（DAL）+ 18-数据获取中心（DAC）
> **关联**: [SPEC评审报告_各维度矛盾计算重建_v0.1.md](./docs/SPEC评审报告_各维度矛盾计算重建_v0.1.md)（v0.1 评审：不通过，本版修复全部问题）、《三维度矛盾论理论框架》§4/§6/§7
> **定位**: 根本性修复——将矛盾维度从『路径来源映射』重建为『真实市场矛盾维度』，使主矛盾识别反映真实市场结构（加息预期承压、小币资金外流 vs BTC 相对强势）。
> **来源**: 2026-10-15 13:26 用户裁定 + v0.1 评审实测证据（数据可得性假设被推翻）。

---

## 0 · 根因分析（已确认，v0.1 保留）

当前 `PrimaryContradictionIdentifier` 的『维度』实为路径来源映射（bdsm→C1、l2_gene→C8 等），识别器内部无任何 CPI/加息/资金流计算，维度力量完全由做多偏向的技术路径推导，导致系统永远输出『一致做多、无矛盾』，与市场实况（加息预期承压、小币外流 vs BTC 强势）背离。下游全部算法（弹性约束/交叉验证/W6）建立在失真输入之上。

## 1 · 数据现状实测（v0.3 更新：18 采集中心已有数据待同步）

**19 DAL（dreambuddy_core.db）实测（2026-10-15 13:40）**：

| 表 | 行数 | 最新 | 状态 |
|----|------|------|------|
| mm_funding_rate / mm_open_interest / mm_liquidation / mm_long_short_ratio / mm_taker_volume | **均 0** | 无 | 待同步/采集 |
| mm_fear_greed | 9 | 2026-10-13 | 不足以算 z-score |
| surprise/calendar/event 表 | **不存在** | — | D1 依赖，需建表 |

**18 DAC（data_center.db）实测（2026-10-15 14:15，共 31422 条记录）**：

| 类别 | 记录数 | 关键内容 | 对应维度 |
|------|--------|----------|----------|
| macro | 484 | CPIAUCSL 44 条（最新 2026-10-15）、PPIACO 45、FEDFUNDS 45、T10Y2M 44、WALCL 194、fomc_decision 3、cpi/nfp/fedwatch 各 2 | **D1 已基本齐备** |
| finance | 4164 | BTC-USD 1349、^VIX 931、SPY 928、GLD 928 | D1 辅助（VIX 风险偏好） |
| chain | 23074 | 链上数据 | D2 潜在来源 |
| news | 3655 | 新闻 | D4 潜在来源 |

**关键结论（用户 14:13 提示验证成立）**：
1. **D1 宏观维度数据已采集**（CPI/PPI/利率/收益率曲线/FOMC 决议均在 18 库中），问题仅为 **18→19 同步链路未打通**，无需从零采集
2. **D2 资金流维度的衍生品数据**（资金费率/持仓量/清算/多空比）在 18 库中未见对应记录，仍需新采集（OKX 等交易所接口）
3. surprise 值（actual−forecast）在 18 中有 cpi/nfp/fedwatch 记录但量少（各 2 条），历史深度不足，需经经济日历采集器补采回填

## 2 · 维度体系设计（v2.0，含评审修订）

| 维度 | 数据源 | 力量计算 | z-score 窗口（M1 修订） | 数据不足降级（C1 修订） |
|------|--------|----------|--------------------------|--------------------------|
| **D1 宏观利率** | CPI surprise（actual−forecast，经济日历采集器）+ 美联储事件 | CPI 超预期→加息预期→风险资产空头力量 | 24 个月滚动；窗口样本 <8 次发布 → 用 percentile 排名 | 无 surprise 数据 → neutral/0，不参与裁决 |
| **D2 资金流** | 资金费率/持仓量/清算/多空比/主动成交量 | 小币外流空头力量 + BTC 相对强势分化 | 30 天滚动；样本 <30 → percentile 排名 | 表空 → neutral/0 |
| **D3 技术** | 现有路径发现 | 现有共振检测（保留） | — | 现有逻辑 |
| **D4 市场情绪** | 恐惧贪婪/清算强度 | 极端情绪反转力量 | 90 天滚动；样本 <30 → percentile | 样本 <10 → neutral/0 |

**BTC 相对强度基准（M3 修订）**：小币集合 = 交易池加密资产减 BTC（UNI/PUMP/HYPE/ETH/SOL/OKB/BNB/LINK），基准 = 小币等权日收益率均值，BTC 相对强度 = BTC 日收益 − 基准。

**维度编号映射（m1 修订）**：D1↔C4(宏观)、D2↔C5(资金流)、D3↔{C2,C3,C8}(技术)、D4↔C1(情绪)；v2 切换时下游引用（G_dim/A_dim、W6 weight_factors 键）经映射表转换，旧编号保留兼容。

**日志格式（m3 修订）**：每周期一条 INFO：
```
[DimensionForce] D1=short:0.62 D2=divergent:0.45 D3=long:0.30 D4=neutral:0.10
```

## 3 · 实施步骤（v0.2 修订）

| 步骤 | 内容 | 验证方式 |
|------|------|----------|
| T1 | 确认 18 DAC 采集器 → 19 DAL 表的写入链路（采集器存在但入库未打通） | 链路代码走查 + 单次采集试运行 |
| T2a | **同步为主**：打通 18→19 同步链路，将 18 库 macro 类（CPI/PPI/FEDFUNDS/T10Y2M/WALCL/fomc_decision，484 条）与 finance 类（BTC/VIX/SPY/GLD，4164 条）同步入 19 对应表；surprise 建表并迁移 cesi_history 文件数据 + 18 库 cpi/nfp/fedwatch 记录 | 同步后 19 表行数与 18 源对齐 |
| T2b | **新采集为辅**：D2 衍生品数据（资金费率/持仓量/清算/多空比）18 库未见，需经 OKX 等交易所接口新采集，回填 ≥90 天；恐惧贪婪补采至 ≥90 天 | 采集后行数与时间范围达标 |
| T3 | 新建 `core/dimension_force_evaluator.py`：四维力量计算（只读 DAL，含降级链） | 单元测试 + **对拍当前市场：D1 应空头、D2 应分化（T3 通过条件，m2 修订）** |
| T4 | 识别器接入：`identify()` 前置维度评估，影子期新旧双写 | 日志 [DimensionForce] 输出 |
| T5 | 主矛盾裁决切换维度间对立度（开关 `enable_dimension_force_v2`，默认 False） | 当前市场应输出 D1 空头主导或 D1/D3 对立，strength 非零 |
| T6 | 端到端验证 + 历史回放证伪实验（评审 §4） | 回放 24 个月 surprise 序列，D1 空头命中率 ≥50% |

**影子期放量条件（M2 修订）**：`7 天连续非空输出` + `至少 1 次宏观数据更新事件` 双条件；D1 单独以历史回放验证（T6）替代实时等待。

## 4 · 可证伪性验收标准（评审 §4 采纳）

| 假设 | 证伪实验 | 通过条件 |
|------|----------|----------|
| D1 方向正确 | 回放 24 个月 surprise，统计 surprise>0 后 48h 风险资产收益 | 空头方向命中率 ≥50%，否则 D1 计算方向反转 |
| D2 捕捉外流 | 对拍已知外流时段（2026-10 小币大跌期） | D2 空头且强度 >0.5 |
| 整体重建有效 | 当前市场主矛盾输出 | D1 空头主导或 D1/D3 对立，若仍一致做多则重建失败 |

## 5 · 风险与回滚
- 影子期新旧并行双写，不影响交易决策；回滚 = 开关置 False，无状态残留。
- T2 回填为独立数据工程，失败不阻塞 T3 开发（评估器带降级链可先行）。

## 6 · 评审问题闭环状态
| 评审项 | 状态 | 本版位置 |
|--------|------|----------|
| C1 数据可得性 | ✅ 已修复 | §1 实测 + §2 降级链 + T2a/T2b 拆分 |
| M1 z-score 窗口 | ✅ 已修复 | §2 每维度窗口 + percentile 降级 |
| M2 影子期双条件 | ✅ 已修复 | §3 放量条件 + D1 历史回放 |
| M3 BTC 基准 | ✅ 已修复 | §2 小币集合明确定义 |
| m1 编号映射 | ✅ 已修复 | §2 映射表 |
| m2 T3 验收 | ✅ 已修复 | §3 对拍通过条件 |
| m3 日志格式 | ✅ 已修复 | §2 [DimensionForce] 格式 |

---

## 7 · v0.4 八维多信号合成架构（2026-11-14 落地）

维度从原 4 维（D1-D4）扩展至 8 维（D1/D2/D3/D4/C6/C7/C8/NEWS），每维从单信号升级为多信号加权合成，单一信号缺失/陈旧时自动降权重归一（FAIL-OPEN）。

### 7.1 维度信号矩阵

| 维度 | 信号源（mm_metrics sub_category） | 合成方式 | 方向约定 |
|------|-----------------------------------|----------|----------|
| **D1 宏观利率** | CPI surprise `cpi.surprise`(0.5) + fedwatch 加息概率 `fedwatch.hike_prob`(0.2) + WALCL 联储表30d动量 `WALCL.value`(0.2) + PPIACO 通胀z `PPIACO.value`(0.1) | 加权平均 | raw>0 空头（鹰/通胀/缩表） |
| **D2 资金流** | 多空比 `long_short_ratio` + 资金费率 `funding_rate`(OKX `okx_derivatives` fallback) + OKX 主动买卖比 `okx_derivatives.taker_buy_sell_ratio` + 持仓量 `open_interest` + 清算 `liquidation` | 加权（ls 0.30/fr 0.20/taker 0.15/oi 0.20/liq 0.15） | 拥挤→空头 |
| **D3 技术** | 调用方传入（路径共振） | — | — |
| **D4 市场情绪** | 恐惧贪婪 `crypto_fear_greed.value`（<25 多/>75 空）+ 期权 PCR `options.put_call_ratio` + `fear_greed_enhanced.capital_flow` | 极端区用恐惧贪婪；中性区 PCR+capital_flow 等权 | raw>0 空头 |
| **C6 估值** | BTC 市值 z `bitcoin.market_cap_usd`(0.6) + ETF 净流入 `etf_flow.latest_total_flow_btc`(0.4，取最近非零值规避周末) | 加权平均 | 高估/流出→空头 |
| **C7 广度** | 稳定币流通量7d变化 `stablecoin_hist_usdt/usdc` + 交易所BTC余额30d变化 `exchanges_whales.ex_bal_BTC_chg30d_pct` + LTH供给z `utxo_age_distribution.long_term_holder_supply_pct` | 三信号等权 | 囤积→多头 |
| **C8 宏观交叉** | 40域 `cross_asset_matrix.json` 动量×相关性(0.6) + FRED宏观z `DGS10`/`DTWEXBGS`/`SP500`(0.4) | 加权；fallback `VIXCLS` z-score | raw<0 空头 |
| **NEWS 信息面** | 快讯频率 `newsflash` z-score | z-score | 高波动→事件驱动 |

### 7.2 数据源与新鲜度（云端实测 2026-11-14）

| 数据源 | 记录数 | 新鲜度 | 用途 |
|--------|--------|--------|------|
| `DGS10` (10Y收益率) | 16357 | 1h | C8 FRED |
| `DTWEXBGS` (美元指数) | 5386 | 1h | C8 FRED |
| `SP500` | 2672 | 1h | C8 FRED |
| `VIXCLS` | 9471 | 1h | C8 fallback（替代仅 8 条的 `^VIX`） |
| `WALCL` (联储表) | 1601 | 1h | D1 流动性 |
| `PPIACO` (PPI) | 1612 | 1h | D1 通胀 |
| `etf_flow` | 1974 | 2h | C6 需求 |
| `long_short_ratio` | 4208 | 0h | D2 |
| `okx_derivatives` | 1490 | 0h | D2 funding/taker |
| `options` (PCR) | 2209 | 0h | D4 |
| `fear_greed_enhanced` | 3492 | 1h | D4 capital_flow |
| `utxo_age_distribution` | 1344 | 2h | C7 LTH |
| `exchanges_whales` | 3713 | 2h | C7 交易所余额 |
| 40域 `cross_asset_matrix.json` | — | generated_at 校验 | C8 主信号 |

### 7.3 sign 约定与降级

- **raw 符号**: raw > 0 → 空头力量; raw < 0 → 多头力量。
- **降级链**: 单信号缺失/陈旧(>7d) → 跳过该信号，其余信号权重重归一；全部缺失 → `neutral` 且 `degraded` 标注原因。
- **阈值**: `|raw| > 0.1~0.15` 才输出 long/short，否则 neutral（避免噪声信号参与裁决）。

## 8 · 部署与验证状态

- **实现文件**: `dreambuddy_evolution/core/dimension_force_evaluator.py`
- **云端 commit**: `5261078e49`（main 分支）
- **服务**: `yijing-polling-trader` 已重启生效
- **云端实测输出** (2026-11-14):
  ```
  D1=short:0.23 D2=short:0.41 D3=neutral:0.00 D4=neutral:0.05
  C6=long:0.63  C7=long:0.15  C8=short:0.24   NEWS=short:0.67
  ```
- **C8 FRED 组件实测**: DGS10 z=0.577(空头) + DTWEXBGS z=0.529(空头) + SP500 z=0.403(多头)，与 40 域矩阵 0.6/0.4 合成。

## 9 · 后续可增强方向

| 数据源 | 记录数 | 建议纳入维度 | 说明 |
|--------|--------|--------------|------|
| `DCOILWTICO` (原油) | 9696, 1h | C8 | 通胀/风险偏好补充 |
| `NASDAQCOM` | 14217, 1h | C8 | 成长股风险偏好 |
| `M2NS` (M2) | 976, 1h | D1 | 货币供应流动性 |
| `social_volume` | 2313, 0h | NEWS/C7 | 社交声量 |
| `tether_current.change_7d_pct` | 7305, 0h | C6/C7 | 稳定币变化（预计算， fresher） |

