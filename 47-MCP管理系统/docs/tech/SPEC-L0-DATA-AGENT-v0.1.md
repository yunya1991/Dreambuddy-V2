# SPEC-L0-DATA-AGENT — 数据域 agent L0 底层能力管理协议

> **版本**: v0.1 ｜ **创建日期**: 2026-11-05 ｜ **状态**: 🟡 草案（调研结论已核实，P0 可开工）
> **定位**: 数据 agent 作为 L0 底层能力纳入 47-MCP 统一契约管理 — 每个子 agent 一个独立子协议文件，含数据源、采集频率、指标口径、质量分级与训练机制
> **上游**: [SPEC-L0-DOMAIN-AGENTS-v0.2](./SPEC-L0-DOMAIN-AGENTS-v0.2.md)（域内 agent 蓝图）· [SPEC-L0-AGENT-TRAIN-BASE-v0.1](./SPEC-L0-AGENT-TRAIN-BASE-v0.1.md)（训练基座 TB1-TB5）· [SPEC-L0-MCP-PACKAGING-v0.3](./SPEC-L0-MCP-PACKAGING-v0.3.md)（壳契约）
> **实现载体**: 壳 = `mcp_shells/l0_data/`（已落地，四工具）· 采集 = `18-数据获取中心/data_center/`（调度器 + 采集器）· 存储 = `19-数据访问层/data/dreambuddy_core.db`（mm_metrics 表）
> **约束**: 单人维护、FAIL-OPEN、壳与 agent 分离（壳零感知 agent 实现）、写治理红线不突破、不引入神经网络权重微调

---

## 1. 背景与问题

### 1.1 触发事件（2026-11-05 基本面数据展示异常排查）

主前端 3.1 基本面快照（`3.1-FRONTEND/scripts/fundamental_snapshot.py`）出现数据展示异常，排查结论：

| 模块 | 状态 | 根因 |
|---|---|---|
| macro | partial | DAL 已有 CPI/PPI/FEDFUNDS/WALCL 等真实数据，聚合脚本只取 5 项，其余硬编码 null（**数据在库、被脚本丢弃**） |
| onchain | good | 真实数据 |
| sentiment / valuation | derived | 聚合脚本内用 VIX/SP500 公式临时派生，非真实数据 |
| flow / breadth / capital_flow | empty | **数据已采集入库**（稳定币、ETF+机构、衍生品、多空比、净流入等），但 DAL 查询命令未暴露，聚合脚本硬编码空 |

### 1.2 核心结论

1. **采集不缺**：18-数据获取中心调度器已稳定运行 20+ 采集任务（FRED 宏观 13 系列、yfinance 行情、ccxt/defillama/etherscan 链上、panewslab 八大板块、theblockbeats 脉动/多空比/净流入、stablecoin_transparency USDT/USDC 供应量、odaily/theblockbeats 快讯等），数据经 18→19 回填链路写入 `mm_metrics` 表。
2. **缺的是暴露与契约**：DAL `data.dal_query` 仅暴露 chain/market/macro/metric 四类命令；资金流、市场宽度、主力资金、情绪等数据在库中无标准查询面。
3. **缺的是协议管理**：各数据域的指标口径、采集频率、质量分级、派生逻辑散落在采集器代码与聚合脚本中，无单一事实源。

## 2. 命题：数据能力作为 L0 底层能力统一管理

**所有数据统一提供给 DAL 调用层，其他模块只调用 DAL** — 本 SPEC 将该原则落地为：

- **采集层**（18）只负责抓取与落库，不直接对上层暴露；
- **访问层**（19 DAL）是唯一数据出口，所有查询命令在此登记；
- **协议层**（47）管理每个数据子 agent 的契约（指标口径/频率/质量分级），作为 SSoT；
- **消费层**（3.1 前端聚合脚本等）只做数据组装与展示，不内置派生公式、不硬编码占位值。

## 3. 子 agent 划分与独立子协议文件

每个子 agent 一个独立子协议文件（`docs/tech/data-agents/` 目录），统一模板：数据源清单、采集频率、指标口径（sub_category/metric_name 命名规范）、质量分级（good/partial/derived/empty）、派生逻辑归属、训练挂钩。

| 子 agent | 子协议文件 | 数据源（现状） | 频率 | 质量目标 |
|---|---|---|---|---|
| macro | `DA-MACRO-v0.1.md` | FRED 13 系列 + yfinance 8 标的 | 15min-1h | good |
| chain | `DA-CHAIN-v0.1.md` | ccxt/defillama/etherscan/mempool | 5min | good |
| flow | `DA-FLOW-v0.1.md` | panewslab ETF+机构板块、stablecoin_transparency、theblockbeats 净流入 | 30min-4h | good（当前 empty） |
| breadth | `DA-BREADTH-v0.1.md` | panewslab 市场总览/周期判断、theblockbeats 脉动指数 | 30min-4h | good（当前 empty） |
| capital_flow | `DA-CAPITAL-FLOW-v0.1.md` | theblockbeats 衍生品信号/多空比、panewslab 交易所/链上资金板块 | 30min-4h | good（当前 empty） |
| sentiment | `DA-SENTIMENT-v0.1.md` | fear_greed_collector（已有采集器）、VIX 派生（过渡） | 30min | good（当前 derived） |

**派生逻辑归属**：sentiment/valuation 等派生计算统一下沉到 DAL 侧（19）维护，聚合脚本不再内置公式，避免口径漂移。

## 4. DAL 查询面扩展

`data.dal_query` 新增命令（在 19-数据访问层实现，47 登记契约）：

| 命令 | 返回 | 数据来源（mm_metrics sub_category） |
|---|---|---|
| `flow` | etf_total_flow、stablecoin_dominance_usdt、net_flow 等 | panewslab/stablecoin/theblockbeats 板块 |
| `breadth` | btc_dominance、breadth_confirmation、global_change_24h 等 | panewslab 市场总览 |
| `capital_flow` | long_short_ratio、衍生品信号、交易所净流入等 | theblockbeats/panewslab |
| `sentiment` | crypto_fear_greed（真实源） | fear_greed 采集器 |

原则：**先契约后扩面** — 每个新命令先在本 SPEC §3 子协议文件登记指标口径，再实现。

## 5. 训练机制（复用训练基座 TB1-TB5）

数据 agent 接入 SPEC-L0-AGENT-TRAIN-BASE，奖励维度在 AlphaPareto 六维基础上增加数据域专属分量：

| 维度 | 说明 |
|---|---|
| 采集成功率 | collector fetch 成功次数 / 调度次数（Beta verify） |
| 数据新鲜度 | now − max(timestamp)，按子协议频率阈值分级 |
| 覆盖率 | 子协议登记指标中非 null 占比 |
| PSI 漂移 | 分布稳定性监控（TB1） |

训练算法约束与全域一致：贝叶斯 verify + GRPO 轻量 RL（冻结 LLM 权重）+ Thompson Sampling regime gate，不引入神经网络权重微调。

## 6. 实施路线（P0-P3）

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0** | 修复基本面聚合脚本：macro 模块填入 DAL 已返回的 CPI/PPI/FEDFUNDS/WALCL 等，替换 null 占位 | 前端 macro 模块无 null 硬编码指标 |
| **P1** | DAL 暴露 flow/breadth/capital_flow/sentiment 查询命令 | 命令返回真实库内数据，非空 |
| **P2** | 六个子协议文件落地 `docs/tech/data-agents/`，登记指标口径 | 47 README 文档清单更新，link_checker 通过 |
| **P3** | 数据 agent 训练接入（采集成功率/新鲜度/覆盖率奖励维度） | ✅ 已落地：`19-数据访问层/scripts/data_agent_reward.py`（四维奖励 + TB3 七维映射 + FAIL-OPEN），生产库验证通过；TB5 PolicySelectLoop 消费接入待后续影子期 |

## 7. 边界与红线

- 实盘交易链路（11/yijing/v15/止损）不暴露 MCP（与全域一致）；
- `data_store_write` 保持 Mandate 写门控（L0_DATA_WRITE_ENABLED=1）；
- 采集器新增/下线必须同步更新对应子协议文件，未登记不得上线（先契约后扩面）；
- 本 SPEC 为纯文档统筹层，不含壳代码实现（壳在 `mcp_shells/l0_data/`，采集在 18，存储在 19）。

## 8. 维护

- 子协议文件变更时更新本 SPEC 版本号与变更记录；
- 由 `0-系统文档管理/4-工具与自动化/doc_coverage.py` + `link_checker` 校验断链。

### 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-05 | 初版：基于基本面数据展示异常排查结论 + 18/19/47 现状调研，确立数据 agent L0 底层能力管理协议框架 |
| v0.1（P0-P3 落地回填） | 2026-11-05 | P0：macro null 指标修复；P1：DAL 新增 flow/breadth/capital_flow/sentiment 四命令 + 前端聚合脚本接入（六模块 good）；P2：六子协议文件落地 data-agents/；P3：数据域四维奖励模块落地（采集成功率/新鲜度/覆盖率/PSI 稳定性，权重常量 0.35/0.30/0.25/0.10，TB3 七维映射） |
