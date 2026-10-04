# 交易榜单推荐系统 — 完整产品规格说明书 (Spec)

> **版本**: v1.0 | **日期**: 2026-09-28 | **作者**: 渠道运营部 × 系统架构组
> **北极星指标**: 月活跃交易用户数 (MATU) +40%
> **对标**: Bloomberg Galaxy Crypto Index / CryptoScores 多因子模型 / Freqtrade 信号引擎

---

## 一、概述与背景

### 1.1 产品定位

"今日十大交易机会"榜单推荐系统 —— 基于系统现有交易能力，每日精选 10 个最优交易标的，配以完整决策卡，实现"推送→分析→决策→执行→复盘"的工作流闭环。

### 1.2 为什么是现在

调研显示（270 份有效样本）：
- 内容满意度 84.8%、转化率 80.0% 看似健康，但 **12.2% 弃单用户（33 人）** 是竞品可抢夺的存量资产
- 弃单主因前三：决策障碍 27.1%、时效延迟 21.2%、认知门槛 15.3%
- 加密货币占 89.3% 绝对基本盘，但内容颗粒度不足是核心瓶颈
- 彭博终端案例证明：工作流嵌入 + 网络效应需 6-12 个月先发期

### 1.3 核心原则

遵循运营方案三大原则：**链路清晰 · 数据监控 · 领导能认**

---

## 二、调研结论

### 2.1 系统现有能力（可复用）

| 模块 | 路径 | 职责 | 复用方式 |
|------|------|------|----------|
| 币种基本面评分 | `11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_ranker.py` | 综合评分 + S/A/B/C 等级映射 | 作为评分层核心，扩展多因子权重 |
| Web3 市场数据源 | `9-基本面分析/ops/nanoclaw/core_task1/flow/scripts/flow_collector.py` | Binance Web3 trending/top search/smart money inflow | 作为数据采集层，获取热门/流入榜 |
| Top10 排序处理 | `11-易经推理系统/data_server_fixed.py` | 按 `metrics.rank` 升序整理 Top10 流入 | 作为排序层，扩展为多维度排序 |
| 基本面简报输出 | `9-基本面分析/backend/src/ml_trade_service.py` | 调用 Web3 排名 API（limit:10），整合 trending/inflow | 作为输出链路，扩展决策卡渲染 |
| 定时调度 | `deploy/hermes/cron/jobs.json` | `evo-health-daily`/`dze-audit-daily` 等每日任务 | 作为每日榜单生成触发入口 |

### 2.2 产物中台能力（7-产物中台）

产物中台是 DreamBuddy-V2 的**产物管理与投递中台**，技术架构详见 [TECHNICAL_DESIGN.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/docs/TECHNICAL_DESIGN.md)。交易榜单推荐的数据运营看板应接入此中台。

**已实现能力（✅ 可复用）**：

| 模块 | 路径 | 职责 | 复用方式 |
|------|------|------|----------|
| Next.js 工程 | `7-产物中台/系统研究索引体系/` (dev 端口 3456) | 可运行实现工程，含 app/lib/components/prisma | 作为交易榜单后端工程宿主 |
| UIMapShell 壳层 | `app/ui-map/UIMapShell.tsx` | 纯渲染，消费 view-model，不访问数据源 | 作为领导层看板渲染壳层 |
| ui-map 装配入口 | `app/ui-map/page.tsx` | 服务端装配，调用 adapter 组装 view-model | 装配交易榜单 adapter |
| 推荐引擎 API | `app/api/recommendation-engine/` | trigger / current-strategy / library / backtests | 复用为榜单推荐 API 架构 |
| 实时事件总线 | `lib/realtime-hub.ts` + `lib/realtime-sse.ts` | EventEmitter + SSE 流（/api/realtime/stream） | 榜单更新实时推送 |
| 后台管理 API | `app/api/admin/*` | 策略/订单/用户/积分/任务/渠道管理 | 榜单管理后台 |
| 进度更新脚本 | `progress_auto_update.py` | Git 状态 + 测试 + 监控页生成 + HTTP 自愈 | 扩展为榜单监控页 |
| Prisma SQLite | `prisma/` | 业务数据持久化（策略/订单/用户等） | Top10 结果持久化 |
| 产物数据源 | `lib/content.server.ts` + `ContentRepository` | 单一真相源 + mtime 双级缓存 | 榜单产物索引 |

**规划中 adapter（⚠️ 需新建）**：

| Adapter | 数据源状态 | 说明 |
|---------|-----------|------|
| `buildOperationsUIMapOverride` | `realtime-hub.ts` 已就位 | 运营链路 adapter — **交易榜单看板的最佳接入点** |
| `buildStrategyUIMapOverride` | `strategy-standard-objects.ts` 已就位 | 策略主线 adapter |
| `buildUserContextUIMapOverride` | `user-context-standard-objects.ts` 已就位 | 用户上下文 adapter |

**前端 Dashboard (3.1-FRONTEND/) 能力**：

| 页面 | 路径 | 职责 |
|------|------|------|
| Dashboard 主入口 | `/dashboard` | 8 个快速入口卡片（含"产物中台"入口） |
| AI Skill 交易 | `/dashboard/trade` | 聊天面板 + 链追踪 + 余额/持仓/信号 |
| 产物中台 | `/dashboard/reports` | 交易报告 / 数据产物 / 图表归档 |
| 组件库 | `V3Card` / `V3Badge` / `ChatPanel` / `ChainTracker` | 可复用榜单卡片组件 |

### 2.3 缺失需新建能力

| 缺失能力 | 说明 | 优先级 |
|----------|------|--------|
| 榜单编排服务 | 整合评分+排序+数据源+推送的独立编排层 | P0 |
| 决策卡生成器 | 7 模块决策卡（入场/止损止盈/事件日历/可视化/风险分级/历史类比/逻辑推演） | P0 |
| 推送通知引擎 | 邮件/站内信/首页 Banner/App Push 多渠道分发 | P0 |
| 前端榜单页面 | 固定专题页（T+0 可更新），绕开行情插发 T+1 限制 | P0 |
| 结果持久化 | 每日 Top10 结果、推荐理由、时间戳存储与版本管理 | P1 |
| 一键入场 | 从推送跳转交易页预填参数（6 步→2 步） | P1 |
| 弃单召回 | 对"点击未下单"用户定向 Push + 限时决策辅助 | P1 |
| 裂变体系 | 双向邀请激励 + 进度可视化 | P2 |

### 2.3 传统金融方法论对标（Bloomberg Galaxy Crypto Index）

彭博终端 Top50 加密资产筛选方法论，核心可迁移要素：

| 方法论要素 | Bloomberg 做法 | 迁移设计 |
|------------|---------------|----------|
| **准入审核** | DAR Exchange Vetting：AML/KYC 合规、反操纵检测、最低日交易额 $2M | 币种准入：流动性阈值 + 交易所合规审核 |
| **多元化约束** | 单一成分 ≤35%、≥1% 市值占比 | 榜单约束：单一币种权重上限 + 品类配比 6+2+2 |
| **再平衡频率** | 月度重平衡 + 3 个月纳入缓冲 | 每日更新榜单 + 周度评分重平衡 |
| **定价机制** | TWAP（30 分钟窗口，4pm ET 收盘） | 入场区间：TWAP + 实时刷新 |
| **四原则** | Data Integrity / Diversification / Representative / Continuity | 数据完整性 / 品类多元 / 市场代表性 / 连续性 |
| **成分筛选** | Top 25 by mcap → 取 12 大（35%/1% cap/floor） | Top 50 候选池 → 取 10 大（按综合评分排序） |

### 2.4 GitHub/开源项目对标

**CryptoScores 多因子相关性研究**（Top 300 币种，2026.02 数据集）：
- 最优三因子组合：GitHub followers + last_commit + DefiLlama revenue30d/mcap → **Pearson +0.599**（30 日收益相关性）
- GitHub 开发活跃度信号最强（Pearson +0.28），DefiLlama 财务指标次之（+0.23），Twitter 社区信号较弱（+0.14）
- Top-to-bottom 四分位差 +23.4pp，显著优于市场中位 +1.0%

**Freqtrade（48K⭐）信号引擎**：
- 7 层信号体系：STRONG_BUY → STRONG_SELL
- 29+ 技术指标（RSI/MACD/BB/OBV/ICHIMOKU/EMA/SMA/MFI/KDJ/SAR 等）
- 置信度 + 归一化评分双维度
- 背离检测（看涨/看跌/隐藏背离）+ 布林带挤压 + 成交量确认

**Hummingbot（18K⭐）**：做市 + 套利框架，可参考其多交易所数据聚合架构。

---

## 三、产品设计

### 3.1 榜单结构

**每日 10 条交易机会，6+2+2 品类配比**：

| 品类 | 配比 | 占比（调研） | 内容侧重 |
|------|------|-------------|----------|
| 加密货币 (BTC/ETH/SOL 等) | 6 条 | 89.3% | 链上数据 + 技术分析 + 事件驱动（ETF/监管） |
| 大宗商品 (原油/黄金等) | 2 条 | 25.9% | 宏观经济 + 地缘政治 + 供需数据 |
| 美股/指数永续 | 2 条 | 28.1%+23.0% | 财报季时间线 + 技术面突破 + 指数 ETF 策略 |

### 3.2 候选池与筛选漏斗

```
全市场币种池（500+）
    │
    ▼ 准入审核（流动性 + 合规 + 非证券 + USD 交易）
候选池 Top 50（按市值 + 日交易额）
    │
    ▼ 多因子评分（技术面 + 基本面 + 链上 + 情绪 + 事件）
评分排序 Top 20
    │
    ▼ 品类配比约束（6 加密 + 2 大宗 + 2 美股）+ 多元化约束
每日 Top 10 榜单
    │
    ▼ 决策卡渲染 + 多渠道分发
用户终端
```

### 3.3 决策卡 7 模块（对标运营方案 P0）

| 模块 | 现状 | 升级后 | 用户需求 |
|------|------|--------|----------|
| 入场策略 | 仅给方向和目标价 | 具体入场区间 + 分批建仓节奏 + 加减仓触发条件 | 37.8% |
| 止损止盈 | 静态止损位 | 动态止损止盈调整 + ATR 波动率自适应 | 39.6% |
| 事件日历 | 无 | 事件驱动时间线（CPI/财报/FOMC）+ 影响预判 | 31.5% |
| 可视化 | 纯文字 | 技术分析图表 + 关键价位标注 | 29.3% |
| 风险分级 | 无 | 新手/进阶/高手三级标注 + 仓位建议 | 28.9% |
| 历史类比 | 无 | 类比历史相似行情 + 走势对照图 | 26.3% |
| 逻辑推演 | 无 | 多空逻辑 + 数据支撑 + 置信度 | 新增 |

---

## 四、评分模型

### 4.1 多因子复合评分体系

借鉴 CryptoScores 三因子模型 + Bloomberg 准入审核 + Freqtrade 7 层信号，设计五维评分：

| 维度 | 权重 | 子因子 | 数据源 |
|------|------|--------|--------|
| **技术面** | 30% | RSI/MACD/BB/ICHIMOKU/EMA 趋势信号 + 背离检测 + 布林带挤压 | K线数据 (CCXT/交易所API) |
| **基本面** | 25% | GitHub 开发活跃度(followers/commits) + DefiLlama 费用/收入/TVL 比率 | GitHub API + DefiLlama API |
| **链上/资金面** | 20% | Smart Money inflow + 资金净流入 + 大户持仓变化 | Binance Web3 Market Rank API |
| **情绪面** | 15% | Twitter 粉丝增长 + 社区活跃度 + 搜索热度 | Twitter/Social API |
| **事件驱动** | 10% | CPI/FOMC/财报/监管事件 + 影响预判 | 事件日历 API |

### 4.2 评分计算

```
综合评分 = Σ(维度权重 × 维度归一化得分)
置信度 = 各子因子一致性比例（方向一致数/总数）
```

**7 层信号体系**（借鉴 Freqtrade）：
| 信号 | 归一化评分 | 置信度 | 含义 |
|------|-----------|--------|------|
| STRONG_BUY | ≥ 0.5 | ≥ 0.7 | 高置信看多 |
| BUY | ≥ 0.35 | ≥ 0.5 | 中置信看多 |
| WEAK_BUY | ≥ 0.2 | - | 低置信看多 |
| NEUTRAL | (-0.2, 0.2) | - | 方向不明 |
| WEAK_SELL | ≤ -0.2 | - | 低置信看空 |
| SELL | ≤ -0.35 | ≥ 0.5 | 中置信看空 |
| STRONG_SELL | ≤ -0.5 | ≥ 0.7 | 高置信看空 |

### 4.3 准入审核（对标 Bloomberg DAR Vetting）

币种准入需满足：
1. **流动性**：30 日中位日交易额 ≥ $2M（对标 Bloomberg）
2. **合规**：交易所具备 AML/KYC 合规政策
3. **非证券**：未被 SEC 认定为证券
4. **USD 交易对**：至少 2 个合规定价源
5. **自由浮动**：非锚定型代币（排除稳定币/包装代币）
6. **连续性**：连续 3 期满足准入条件（3 个月缓冲期）

### 4.4 多元化约束（对标 Bloomberg 35%/1% Cap）

- 单一币种评分权重 ≤ 35%（防止单一币种主导榜单）
- 单一币种评分权重 ≥ 1%（保证最低代表性）
- 品类配比硬约束：6 加密 + 2 大宗 + 2 美股/指数

---

## 五、技术架构

### 5.1 五层架构

```
┌─────────────────────────────────────────────────────┐
│  展示层 (Presentation)                                │
│  首页 Banner · 站内信 · 邮件 · App Push · 专题页      │
│  ← 复用: 3-FRONTEND/3.1-FRONTEND 前端框架             │
├─────────────────────────────────────────────────────┤
│  决策卡生成层 (Decision Card)                         │
│  入场策略 · 止损止盈 · 事件日历 · 可视化              │
│  风险分级 · 历史类比 · 逻辑推演                       │
├─────────────────────────────────────────────────────┤
│  评分排序层 (Scoring & Ranking)                      │
│  多因子评分 → 准入审核 → 多元化约束 → Top10          │
│  ← 复用: coin_fundamental_ranker.py (扩展)           │
│  ← 复用: data_server_fixed.py (排序)                 │
├─────────────────────────────────────────────────────┤
│  数据采集层 (Data Collection)                         │
│  行情 · 链上 · 基本面 · 情绪 · 事件                  │
│  ← 复用: flow_collector.py (Binance Web3)            │
│  ← 复用: 18-数据获取中心 / 19-数据访问层              │
├─────────────────────────────────────────────────────┤
│  调度层 (Scheduling)                                 │
│  每日定时触发 + 重大行情插发                          │
│  ← 复用: deploy/hermes/cron/jobs.json               │
└─────────────────────────────────────────────────────┘
```

### 5.2 数据流

```
1. 调度触发（每日 08:00 北京时间）
   ↓
2. 数据采集
   ├─ 行情: CCXT/交易所 API → K线 + 实时价格
   ├─ 链上: Binance Web3 Market Rank → inflow/trending
   ├─ 基本面: GitHub API + DefiLlama API → 开发活跃度 + 财务
   ├─ 情绪: Twitter/Social API → 粉丝/活跃度
   └─ 事件: 事件日历 API → CPI/FOMC/财报
   ↓
3. 评分计算
   ├─ 准入审核 → 候选池 Top 50
   ├─ 五维评分 → 归一化
   ├─ 多元化约束 → 品类配比
   └─ 排序 → Top 10
   ↓
4. 决策卡生成
   ├─ 入场策略: 基于评分 + ATR 计算入场区间
   ├─ 止损止盈: 动态 ATR 自适应
   ├─ 事件日历: 关联事件 + 影响预判
   ├─ 可视化: 生成技术图表 + 关键价位
   ├─ 风险分级: 新手/进阶/高手 + 仓位建议
   ├─ 历史类比: 相似行情检索 + 走势对照
   └─ 逻辑推演: 多空逻辑 + 数据支撑 + 置信度
   ↓
5. 多渠道分发
   ├─ 固定专题页（T+0 更新）
   ├─ 站内信（每日定时）
   ├─ 邮件（格式化模板）
   ├─ App Push（入场时机触发/重大行情）
   └─ 首页 Banner（固定 C 位）
   ↓
6. 监控与反馈
   ├─ 推送到达率 / 退订率
   ├─ 点击率 / 转化率 / 弃单率
   └─ 用户评分（1-5 星）
```

### 5.3 技术约束与绕行方案

运营方案指出：**行情插发链接配置为 T+1，但专题页内容可实时更新**。

绕行方案：
- 推送链接指向 **固定专题页**（T+0 可更新），而非每日新建链接
- 重大行情时仅更新专题页内容 + 触发 Push 通知
- 静默时段：23:00-07:00 不发送 Push 和短信

---

## 六、数据源矩阵

| 数据类型 | 来源 | 获取方式 | 频率 | 复用模块 |
|----------|------|----------|------|----------|
| K线/行情 | 交易所 API | CCXT / 直连 | 实时 | 18-数据获取中心 |
| Smart Money Inflow | Binance Web3 | `flow_collector.py` | 每小时 | 9-基本面分析 |
| Trending/Top Search | Binance Web3 | `flow_collector.py` | 每小时 | 9-基本面分析 |
| 开发活跃度 | GitHub API | followers/commits/stars | 每日 | 新建 |
| 协议财务 | DefiLlama API | fees/revenue/TVL | 每日 | 新建 |
| 社区情绪 | Twitter API | 粉丝增长/活跃度 | 每日 | 新建 |
| 事件日历 | 经济日历 API | CPI/FOMC/财报 | 每日 | 新建 |
| 历史行情 | 内部数据库 | K线回溯 | 按需 | 4-MEMORY |

---

## 七、转化漏斗修复（对标亚马逊四重优化）

| 断点 | 弃单主因 | 修复策略 | 经典对标 |
|------|----------|----------|----------|
| 决策障碍 | 逻辑细节不足 27.1% | 每条机会附决策卡：逻辑推演 + 入场区间 + 止损止盈 + 仓位 | 亚马逊"商品详情页" |
| 时效延迟 | 入场时机已过 21.2% | 入场区间实时更新 + 临近入场 Push + 固定专题页 T+0 | 亚马逊"限时秒杀" |
| 认知门槛 | 品种不熟悉 15.3% | 风险三级标注 + 品种知识卡片 + 新手低风险专区 | 亚马逊"商品对比表" |
| 风控缺位 | 缺仓位建议 15.3% | 仓位计算器 + 风险敞口提示 | 彭博"风险终端" |

**一键入场**（最高优先级）：将六步流程压缩为两步
- 推送 → 跳转交易页预填参数 → 确认下单

---

## 八、用户分层运营（RFM 模型）

| 层级 | RFM 特征 | 占比 | 运营目标 | 核心策略 |
|------|----------|------|----------|----------|
| 核心交易者 | R近/F高/M高 | ~15% | 提升客单价 | VIP 通道 + 加减仓提醒 + 大户策略包 |
| 活跃参与者 | R近/F中/M中 | ~35% | 提升频率 | 阶梯任务 + 连续参与奖励 + 品类拓展 |
| 观望流失者 | R远/F低/M低 | ~35% | 唤醒回流 | 弃单召回 + 新手降维 + 限时激励 |
| 沉睡用户 | R极远/F极低 | ~15% | 重新激活 | 重大行情插发 + 回归礼包 + 社交邀请 |

---

## 九、渠道与频率策略

| 渠道 | 占比 | 定位 | 分发策略 |
|------|------|------|----------|
| 首页 Banner | 36.3% | 主力曝光 | 每日同步，固定 C 位 |
| 站内信 | 35.2% | 主力分发 | 每日定时，重大行情加发 |
| 邮件 | 33.7% | 主力分发 | 每日定时，格式化模板 |
| App Push | 18.9% | 即时提醒 | 入场时机触发/重大行情速报 |
| Telegram/微信群 | 18.1% | 社区裂变 | 裂变入口 + KOL 互动 |
| 霸屏弹窗 | 15.6% | 突发行情 | 极端波动/黑天鹅 |
| 短信 | 13.3% | 兜底召回 | 沉睡用户唤醒 |

**频率**：每日一发为基准 + 插发机制（BTC 日波动 >5% / FOMC / CPI 超预期 / 黑天鹅）

---

## 十、监控体系

### 10.1 三层看板

| 看板 | 受众 | 内容 | 频率 |
|------|------|------|------|
| 领导层 | 决策层 | 8 项核心指标总览 | 每日自动更新 |
| 运营层 | 运营负责人 | 漏斗与分项追踪 | 每日 |
| 执行层 | 开发/数据 | 实时日志与告警 | 实时 |

### 10.2 核心指标与预警

| 指标 | 数据来源 | 预警阈值 | 告警级别 |
|------|----------|----------|----------|
| 内容满意度 | 评分组件 | 周均 <80% | 黄色 |
| 交易转化率 | 交易+推送系统 | 日 <75% | 红色 |
| 弃单率 | 推送+交易系统 | 日 >15% | 红色 |
| NPS | 问卷系统 | 月度 <65% | 黄色 |
| K 因子 | 邀请+注册系统 | 连续 2 周 <0.5 | 黄色 |
| 推送到达率 | 推送日志 | 日 <90% | 黄色 |
| 退订率 | 推送+设置 | 周均 >3% | 红色 |
| MATU | 交易系统 | 环比 <-5% | 红色 |

### 10.3 A/B 测试框架

| 测试项 | 对照组 | 实验组 | 主指标 | 样本 | 周期 |
|--------|--------|--------|--------|------|------|
| 内容格式 | 纯文字 | 决策卡 | 转化率 | 各 1000 | 2 周 |
| 推送频率 | 每日 1 次 | 1 次+插发 | 退订率+转化率 | 各 1500 | 3 周 |
| 裂变激励 | 无奖励 | 双方 7 天 VIP | K 因子 | 各 500 | 4 周 |
| 一键入场 | 6 步 | 2 步 | 转化率+弃单率 | 各 800 | 2 周 |

---

## 十一、实施路线图

### Phase 1：基础建设期（2026 Q4，10-12 月）— P0

| 动作项 | 人力 | 周期 | 复用模块 | 预期 |
|--------|------|------|----------|------|
| 榜单编排服务 | 1 后端 | 2 周 | cron/jobs.json + ml_trade_service | 每日自动生成 Top10 |
| 决策卡 7 模块 | 2 分析师+1 前端 | 4 周 | coin_fundamental_ranker (扩展) | 满意度 +5pp |
| 固定专题页 | 1 前端 | 2 周 | 3-FRONTEND 框架 | 时效流失 -50% |
| 一键入场 | 1 后端+1 前端 | 2 周 | 22-执行引擎中心 | 转化率 +3pp |
| 数据监控看板 | 1 数据+1 前端 | 2 周 | 15-监控告警系统 | 决策周期 -70% |

**Gate 1**（10 月第 1 周）：启动审批 — 资源确认 + 技术可行性（专题页 T+0 验证）
**Gate 2**（12 月第 2 周）：效果验证 — 满意度 ≥88%、转化率 ≥82%、弃单挽回 ≥30%（达成 ≥2 项）

### Phase 2：增长引擎期（2027 Q1，1-3 月）— P1

| 动作项 | 人力 | 周期 | 预期 |
|--------|------|------|------|
| 双向邀请裂变 | 1 后端+1 运营 | 3 周 | K 因子 ≥1.2，月新增 +15% |
| 铜银金钻会员体系 | 1 产品+1 后端 | 4 周 | 月活留存 +10pp |
| 交易达人排行榜 | 1 产品+BD | 4 周 | 社交货币攀比 |
| KOL 跟单视角试运营 | 1 产品+BD | 8 周 | 内容差异化 |

**Gate 3**（4 月第 1 周）：增长验证 — NPS ≥76%、K 因子 ≥1.0、MATU 环比 +15%

### Phase 3：生态闭环期（2027 Q2，4-6 月）— P2

| 动作项 | 人力 | 周期 | 预期 |
|--------|------|------|------|
| 用户社区/通讯 | 2 后端+1 前端 | 12 周 | 网络效应锁定 |
| KOL 签约入驻 | BD 团队 | 8 周 | 内容生态 |
| 工作流闭环 | 全栈 | 8 周 | 推送→分析→执行→复盘 |
| 跨品类外汇试点 | 1 后端 | 4 周 | 品类拓展 |

**终期目标**：NPS 80%+，MATU +40%，K >1.2

---

## 十二、风险与应对

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|----------|
| 内容质量下降 | 满意度下滑 | 中 | 审核 SOP + 分析师绩效挂钩 + 实时监控 |
| 推送频率过高 | 退订疲劳 | 中 | 频率偏好设置 + 静默时段 + A/B 测试 |
| 裂变质量低 | 拉新不活跃 | 中 | 奖励门槛设为"注册+参与 1 次" |
| 技术 T+1 限制 | 插发滞后 | 高 | 固定专题页链接 + Push 实时触发 |
| 合规风险 | KOL/社区言论 | 中 | Phase 3 前合规审查 + 免责声明 + 内容审核 |
| 竞品跟随 | 差异化减弱 | 中 | 彭博模式锁定：工作流闭环 + 社区网络效应 |

---

## 十三、产物中台集成方案

### 13.1 集成策略：混合方案（推荐）

采用"数据生产集中 + 双端展示"混合方案，遵循产物中台 `TECHNICAL_DESIGN.md` 的架构原则：

```
┌──────────────────────────────────────────────────────────┐
│  数据生产层（产物中台 系统研究索引体系）                    │
│  cron 每日触发 → flow_collector + coin_fundamental_ranker │
│  → 评分排序 → Top10 结果 → Prisma SQLite 持久化           │
│  → realtime-hub 发布榜单更新事件                          │
├──────────────────────────────────────────────────────────┤
│  API 层（产物中台 app/api/）                               │
│  /api/trading-ranking/today      → 每日 Top10 + 决策卡    │
│  /api/trading-ranking/history    → 历史榜单               │
│  /api/trading-ranking/monitor    → 监控指标               │
│  /api/realtime/stream?channel=ranking → SSE 实时推送      │
├──────────────────────────────────────────────────────────┤
│  展示层 A：领导层看板（产物中台 ui-map）                   │
│  buildOperationsUIMapOverride adapter                     │
│  → UIMapShell 卡片：榜单总览 + 核心指标 + 活跃环          │
├──────────────────────────────────────────────────────────┤
│  展示层 B：用户决策页（3.1-FRONTEND dashboard）            │
│  /dashboard/ranking → Top10 列表 + 决策卡 7 模块          │
│  复用 V3Card/V3Badge 组件 + 新建 RankingCard/DecisionCard │
└──────────────────────────────────────────────────────────┘
```

**方案优势**：
- 遵循产物中台"单一真相源 + 壳层与数据分离"原则
- 数据生产集中（产物中台），不重复建设
- 领导层看板在 ui-map（聚合总览），用户决策页在 dashboard（交互详情）
- 复用现有推荐引擎 API 架构 + Prisma 持久化 + 实时事件总线

### 13.2 产物中台 adapter 扩展（遵循 TECHNICAL_DESIGN.md §9.1）

新增"交易榜单"模块到 ui-map，按标准扩展流程：

1. **adapter 层** — `lib/ui-map-real-data.ts` 新增：
   ```typescript
   export function buildTradingRankingUIMapOverride(): UIMapTradingRankingOverride | null {
     try {
       const ranking = getTodayRanking();  // 调用 /api/trading-ranking/today 或 Prisma 直读
       if (!ranking || ranking.length === 0) return null;
       return {
         description: `今日 Top10 交易机会：${ranking.length} 条精选...`,
         bullets: [
           `加密 ${ranking.filter(r => r.category === 'crypto').length} 条`,
           `大宗 ${ranking.filter(r => r.category === 'commodity').length} 条`,
           `美股/指数 ${ranking.filter(r => r.category === 'index').length} 条`,
           `平均置信度 ${(ranking.reduce((s, r) => s + r.confidence, 0) / ranking.length * 100).toFixed(0)}%`,
         ],
         topItem: ranking[0],  // 榜首摘要
       };
     } catch { return null; }  // 异常降级
   }
   ```

2. **view-model 层** — `app/ui-map/ui-map-shell-view-model.ts` 扩展 `UIMapShellOverrides`：
   ```typescript
   interface UIMapShellOverrides {
     systemResearch?: UIMapSystemResearchOverride | null;
     tradingRanking?: UIMapTradingRankingOverride | null;  // 新增
     // ... 其他规划中 adapter
   }
   ```

3. **fixture 降级** — `ui-map-scenarios.ts` 补充榜单 fixture

4. **装配入口** — `app/ui-map/page.tsx` 调用 `buildTradingRankingUIMapOverride` 并传入 view-model

5. **壳层渲染** — `UIMapShell.tsx` / `UIMapModuleCard.tsx` 新增榜单卡片

6. **测试** — `ui-map-real-data.test.ts` 补充 adapter 注入与降级测试

### 13.3 新增 API 路由（遵循 TECHNICAL_DESIGN.md §9.4）

在 `7-产物中台/系统研究索引体系/app/api/trading-ranking/` 新建：

| 路由 | 方法 | 说明 | 数据源 |
|------|------|------|--------|
| `today/route.ts` | GET | 每日 Top10 + 决策卡 7 模块 | Prisma 直读 + 评分服务 |
| `history/route.ts` | GET | 历史榜单（分页，支持 date/category 参数） | Prisma 查询 |
| `monitor/route.ts` | GET | 监控指标（转化率/弃单率/到达率/满意度） | Prisma 聚合 |
| `trigger/route.ts` | POST | 手动触发生成（spawn python 脚本，5 分钟超时） | subprocess |

所有路由：`export const dynamic = "force-dynamic"` + 统一 `try/catch` 容错 + `{ success, error }` 结构。

### 13.4 数据持久化（Prisma Schema 扩展）

在 `7-产物中台/系统研究索引体系/prisma/schema.prisma` 新增模型：

```prisma
model TradingRanking {
  id          String   @id @default(cuid())
  date        DateTime @unique          // 榜单日期
  rank        Int                       // 排名 1-10
  symbol      String                    // 币种代码
  category    String                    // crypto/commodity/index
  score       Float                     // 综合评分
  signal      String                    // STRONG_BUY..STRONG_SELL
  confidence  Float                     // 置信度 0-1
  decisionCard Json                     // 决策卡 7 模块 JSON
  createdAt   DateTime @default(now())

  @@index([date])
  @@index([category])
}

model RankingMonitor {
  id            String   @id @default(cuid())
  date          DateTime @unique
  satisfaction  Float?    // 内容满意度
  conversionRate Float?   // 交易转化率
  abandonRate   Float?    // 弃单率
  pushReachRate Float?    // 推送到达率
  unsubscribeRate Float? // 退订率
  matu          Int?      // 月活跃交易用户数
  kFactor       Float?    // 裂变系数
  createdAt     DateTime @default(now())
}
```

### 13.5 实时推送（复用 realtime-hub）

榜单生成后通过 `realtime-hub` 发布事件：

```typescript
// 榜单生成服务
import { getRealtimeHub } from '@/lib/realtime-hub';

const hub = getRealtimeHub();
hub.publish('trading-ranking', {
  type: 'ranking.updated',
  date: new Date().toISOString(),
  topItem: ranking[0],
  totalItems: ranking.length,
});
```

前端通过 SSE 订阅：`/api/realtime/stream?channel=trading-ranking`

### 13.6 前端 Dashboard 新增页面（3.1-FRONTEND）

1. **主入口新增卡片** — `src/app/dashboard/page.tsx` quickLinks 新增：
   ```typescript
   { label: '交易榜单', href: '/dashboard/ranking', desc: '今日 Top10 交易机会 + 决策卡', color: 'border-rose-500/20 hover:border-rose-500/40' },
   ```

2. **榜单详情页** — `src/app/dashboard/ranking/page.tsx`：
   - Top10 列表（复用 V3Card）
   - 决策卡 7 模块（新建 DecisionCard 组件）
   - 品类筛选（加密/大宗/美股）
   - 一键入场按钮

3. **新建组件**：
   - `RankingCard.tsx` — 榜单卡片（排名 + 币种 + 信号 + 置信度）
   - `DecisionCard.tsx` — 决策卡 7 模块渲染
   - `RankingMonitor.tsx` — 监控指标看板（领导层数据）

### 13.7 监控页扩展（复用 progress_auto_update.py）

扩展 `progress_auto_update.py` 新增榜单监控：
- 在 `render_html()` 新增榜单监控区块（Top10 生成状态 + 核心指标）
- 在 `detect_task_completion()` 新增 `task_ranking`：榜单生成是否成功
- 监控页端口 62932，领导可随时查看

---

## 十四、参考来源

1. **运营方案**：《今日十大交易机会》运营方案 v1.0，渠道运营部，2026-09-28
2. **Bloomberg Galaxy Crypto Index**：Top 50 资产筛选方法论，DAR Exchange Vetting，35%/1% 多元化约束，月度再平衡，TWAP 定价
3. **CryptoScores 研究**：Top 300 币种三因子相关性分析（GitHub + DefiLlama + Twitter），最优组合 Pearson +0.599，2026.03
4. **Freqtrade**：开源加密交易机器人（48K⭐），7 层信号体系 + 29+ 技术指标
5. **Hummingbot**：开源做市/套利框架（18K⭐），多交易所数据聚合
6. **亚马逊**：转化漏斗四重优化（看了还看/一键下单/Prime 锁定/弃购挽回）
7. **Dropbox**：双向奖励裂变（双方各得 500MB，15 个月 3900% 增长）
8. **拼多多**：社交货币裂变（砍一刀机制）
9. **Costco**：精选 SKU + 会员锁定品类策略
10. **星巴克**：星享俱乐部四层会员体系（Green→Gold→Reserve）
11. **产物中台技术设计**：[TECHNICAL_DESIGN.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-产物中台/docs/TECHNICAL_DESIGN.md) v1.0，2026-08-02 — UIMapShell 壳层 + adapter 扩展机制 + 推荐引擎 API + 实时事件总线 + Prisma 持久化
12. **前端 Dashboard**：[3.1-FRONTEND/src/app/dashboard/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/dashboard/page.tsx) — Next.js + V3Card/V3Badge 组件库 + 8 入口卡片 + 交易页面
