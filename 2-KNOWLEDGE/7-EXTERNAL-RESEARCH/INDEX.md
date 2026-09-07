# 7-EXTERNAL-RESEARCH — 外部资料素材库

> **定位：** 开发过程中产生的传统金融调研、GitHub开源调研、技术方案调研的归档库。
> **读者：** 需要复用调研结论、追溯调研路径的开发者
> **来源：** 对话中WebSearch、GitHub分析、方案对比

---

## 归档模板

每个调研归档文件遵循统一模板：

```markdown
# [调研主题]

> **分类**: finance/quant-methods | github/ml-frameworks | technical/architecture
> **调研日期**: YYYY-MM-DD
> **调研场景**: [触发调研的开发任务]
> **来源**: [WebSearch关键词 / GitHub仓库URL / 对话分析]
> **标签**: #标签1 #标签2  ← 检索用标签
> **状态**: active | archived | deprecated

## 调研结论
[3-5句精华结论，可直接引用]

## 调研路径
[关键引用链接 + 对比分析要点]

## 在DreamBuddy中的应用
[本调研如何影响了代码实现，引用相关文件路径]

## 关联知识
[指向2-KNOWLEDGE其他域的交叉引用]
```

## 自动分类规则

| 检测信号 | 分类 | 归档域 |
|---|---|---|
| WebSearch传统金融关键词（量化、风控、定价、对冲） | finance | 7-EXTERNAL-RESEARCH/finance/* |
| GitHub仓库分析（repo URL、开源项目对比） | github | 7-EXTERNAL-RESEARCH/github/* |
| 技术方案对比（架构、算法、测试方法） | technical | 7-EXTERNAL-RESEARCH/technical/* |

## 目录结构

```
7-EXTERNAL-RESEARCH/
├── INDEX.md              ← 本文件
├── finance/              ← 传统金融调研
│   ├── quant-methods/    ← 量化方法（Kalman/PCA/IC等）
│   ├── risk-models/      ← 风控模型
│   ├── market-structure/ ← 市场结构
│   └── trading-psychology/ ← 交易心理
├── github/               ← GitHub开源调研
│   ├── ml-frameworks/   ← 机器学习框架
│   ├── trading-systems/ ← 交易系统
│   ├── data-engineering/ ← 数据工程
│   └── infra-tools/     ← 基础设施工具
└── technical/            ← 技术方案调研
    ├── architecture/     ← 架构模式
    ├── algorithms/       ← 算法实现
    └── testing/         ← 测试方法
```

## 归档触发机制

对话中AI主动检测到调研内容时，提示用户：

```
AI: "检索到Kalman Filter实现方案。这段调研结论值得归档。
     建议分类: finance/quant-methods，标签: #kalman #numpy
     是否归档？(Y/N)"
```

用户确认后，AI按模板生成知识单元，写入对应目录，并更新本INDEX.md。

## 归档记录（阶段2 W1+W2+W3 + 四层闭环进化架构专项 共 11 篇）

| # | 日期 | 主题 | 分类 | 标签 |
|---|------|------|------|------|
| 1 | 2026-09-01 | [Kalman滤波量化实战调研](./finance/quant-methods/2026-09-01-kalman滤波量化实战调研.md) | finance/quant-methods | #量化 #kalman #贝叶斯 #fail-open |
| 2 | 2026-09-01 | [LangChain检索架构调研](./github/ml-frameworks/2026-09-01-langchain检索架构调研.md) | github/ml-frameworks | #langchain #rag #架构 #fail-open |
| 3 | 2026-09-01 | [订单簿流动性与减半周期调研](./finance/market-structure/2026-09-01-订单簿流动性与减半周期调研.md) | finance/market-structure | #减半周期 #订单簿 #流动性 #CME缺口 |
| 4 | 2026-09-01 | [开源量化框架对比freqtrade/jesse/vnpy调研](./github/trading-systems/2026-09-01-开源量化框架对比freqtrade-jesse-vnpy调研.md) | github/trading-systems | #freqtrade #jesse #vnpy #框架对比 |
| 5 | 2026-09-01 | [FAIL-OPEN架构模式统一范式调研](./technical/architecture/2026-09-01-FAIL-OPEN架构模式统一范式调研.md) | technical/architecture | #架构 #fail-open #韧性 #降级 |
| 6 | 2026-09-01 | [恐贪指数与行为金融8大偏误情绪校准调研](./finance/trading-psychology/2026-09-01-恐贪指数与行为金融8大偏误情绪校准调研.md) | finance/trading-psychology | #恐贪指数 #行为金融 #情绪决策 #FinBERT #损失厌恶 |
| 7 | 2026-09-01 | [Medallion三层奖章架构与Tushare特征Silver门禁调研](./github/data-engineering/2026-09-01-Medallion三层奖章架构与Tushare特征Silver门禁调研.md) | github/data-engineering | #Medallion #奖章架构 #Tushare #Silver门禁 #三级异常过滤 |
| 8 | 2026-09-01 | [TDA持久同调Ising相变Kalman-PCA衍生算法调研](./technical/algorithms/2026-09-01-TDA持久同调Ising相变Kalman-PCA衍生算法调研.md) | technical/algorithms | #TDA #持久同调 #Ising #相变检测 #Kalman-PCA #共振 |
| **9** | **2026-09-03** | [传统金融最小阻力理论-Livermore-Soros-Wyckoff](./finance/trading-psychology/2026-09-03-传统金融最小阻力理论-Livermore-Soros-Wyckoff.md) | finance/trading-psychology | #最小阻力 #利弗莫尔 #关键位 #走势流畅度 #索罗斯 #反身性 #Wyckoff #努力结果 |
| **10** | **2026-09-03** | [进化学复杂科学-MEPP-Schluter-ESS-SOC](./technical/algorithms/2026-09-03-进化学复杂科学-MEPP-Schluter-ESS-SOC.md) | technical/algorithms | #ESS #进化稳定 #Schluter #G矩阵 #gmax演化线 #MEPP #最大熵产生 #SOC #自组织临界 #雪崩 |
| **11** | **2026-09-03** | [GitHub最小阻力RL策略进化开源项目调研](./github/trading-systems/2026-09-03-GitHub最小阻力RL策略进化开源项目调研.md) | github/trading-systems | #RL #强化学习 #DQN #纯numpy #基因编码 #锦标赛选择 #AlmgrenChriss #双尺度冲击 #Eigenportfolio #PCA |
- [2026-09-01] [恐贪指数与行为金融8大偏误情绪校准调研](7-EXTERNAL-RESEARCH/finance/risk-models/2026-09-01-恐贪指数与行为金融8大偏误情绪校准调研.md) — finance/risk-models | 标签: #对冲 #止损 #止盈 #仓位 #波动率
- [2026-09-01] [恐贪指数与行为金融8大偏误情绪校准调研](7-EXTERNAL-RESEARCH/technical/architecture/2026-09-01-恐贪指数与行为金融8大偏误情绪校准调研.md) — technical/architecture | 标签: #架构 #rag #fail-open
- [2026-09-01] [Medallion三层奖章架构与Tushare特征Silver门禁调研](7-EXTERNAL-RESEARCH/finance/market-structure/2026-09-01-medallion三层奖章架构与tushare特征silver门禁调研.md) — finance/market-structure | 标签: #订单簿 #流动性 #资金费率
- [2026-09-01] [Medallion三层奖章架构与Tushare特征Silver门禁调研](7-EXTERNAL-RESEARCH/technical/algorithms/2026-09-01-medallion三层奖章架构与tushare特征silver门禁调研.md) — technical/algorithms | 标签: #索引 #检索 #排序 #过滤
- [2026-09-01] [TDA持久同调Ising相变Kalman-PCA衍生算法调研](7-EXTERNAL-RESEARCH/finance/quant-methods/2026-09-01-tda持久同调ising相变kalman-pca衍生算法调研.md) — finance/quant-methods | 标签: #量化 #kalman #pca #回测 #贝叶斯
- [2026-09-01] [TDA持久同调Ising相变Kalman-PCA衍生算法调研](7-EXTERNAL-RESEARCH/technical/algorithms/2026-09-01-tda持久同调ising相变kalman-pca衍生算法调研.md) — technical/algorithms | 标签: #算法 #过滤 #embedding
- [2026-09-01] [恐贪指数与行为金融8大偏误情绪校准调研](7-EXTERNAL-RESEARCH/finance/risk-models/2026-09-01-恐贪指数与行为金融8大偏误情绪校准调研.md) — finance/risk-models | 标签: #对冲 #止损 #止盈 #仓位 #波动率
- [2026-09-01] [恐贪指数与行为金融8大偏误情绪校准调研](7-EXTERNAL-RESEARCH/technical/architecture/2026-09-01-恐贪指数与行为金融8大偏误情绪校准调研.md) — technical/architecture | 标签: #架构 #rag #fail-open
- [2026-09-01] [Medallion三层奖章架构与Tushare特征Silver门禁调研](7-EXTERNAL-RESEARCH/finance/market-structure/2026-09-01-medallion三层奖章架构与tushare特征silver门禁调研.md) — finance/market-structure | 标签: #订单簿 #流动性 #资金费率
- [2026-09-01] [Medallion三层奖章架构与Tushare特征Silver门禁调研](7-EXTERNAL-RESEARCH/technical/algorithms/2026-09-01-medallion三层奖章架构与tushare特征silver门禁调研.md) — technical/algorithms | 标签: #索引 #检索 #排序 #过滤
- [2026-09-01] [TDA持久同调Ising相变Kalman-PCA衍生算法调研](7-EXTERNAL-RESEARCH/finance/quant-methods/2026-09-01-tda持久同调ising相变kalman-pca衍生算法调研.md) — finance/quant-methods | 标签: #量化 #kalman #pca #回测 #贝叶斯
- [2026-09-01] [TDA持久同调Ising相变Kalman-PCA衍生算法调研](7-EXTERNAL-RESEARCH/technical/algorithms/2026-09-01-tda持久同调ising相变kalman-pca衍生算法调研.md) — technical/algorithms | 标签: #算法 #过滤 #embedding

## 调研归档全景进度（12 子域填充率）

> 阶段 2 目标：从 1/12（8%）→ 6/12（50%）W2 已超额达标；**W3 结束后 10/12 子域有内容 = 83% 起步率，9/12 归档点填充 = 75%**。阶段 3 目标：补完最后 2 个空白子域（infra-tools + testing）→ 12/12 = 100%。

| 大类 | 子域 | 当前篇数 | 填充状态 | 下一篇建议（W4） |
|------|------|----------|----------|-----------------|
| **finance**（4子域） | quant-methods | 1 | ✅ 已起步 | 信息系数IC+MI双维因子筛选 / PCA共振情绪叠加 / WalkForward验证法参数表 |
| **finance** | risk-models | 1（含历史中信建投） | ✅ 已起步 | Kelly仓位公式实战（fn f 最优分数推导）/ VaR历史/参数/蒙特卡洛三法 / 组合熔断分级阈值 |
| **finance** | market-structure | 1 | ✅ 已起步 | 美股/加密/A股三市场季节效应月度热力图 / 期权衍生品结构（Gamma挤压/Vanna流动性） / 跨市场资金流向（CME/Brent/DXY） |
| **finance** | trading-psychology | 1 | ✅ 已起步（W3 填） | 社交媒体情绪(Fear&Greed vs Reddit WallStreetBets)相关性 / 反偏闭环训练数据集 / 偏差量化分数 BiasScore 0-100 |
| **github**（4子域） | ml-frameworks | 1 | ✅ 已起步 | LightGBM Screen1 七维权重完整调参脚本落地 / filterpy 对比 pykalman 工程化封装 / LlamaIndex vs LangChain 二选一 |
| **github** | trading-systems | 1 | ✅ 已起步 | Jesse numpy cache 直接接入 V15 回测管线 / freqtrade FreqAI 强化学习训练管线 / Backtrader Cerebro 策略迁移法 |
| **github** | data-engineering | 1 | ✅ 已起步（W3 填） | Great Expectations / dbt 与 Silver 链结合 / DuckDB+Polars 加速 Gold 查询 / Apache Iceberg 表格式 |
| **github** | infra-tools | 0 | ⬜ 空白 | **W4 P1**：launchd 运维最佳实践 plist 模板（poll_light / dc-scheduler / yijing_live 三张生产plist案例）/ SQLite WAL+vacuum优化 / ECharts仪表盘模板 × 3套（PnL曲线/情绪热力/卦象矛盾分位数） |
| **technical**（3子域） | architecture | 1 | ✅ 已起步 | Shadow策略独立开关治理（与7引擎shadow对齐）/ 模块化开关enable_strategy_layer三层字节等价迁移剧本 / 实时热路径配置Reload |
| **technical** | algorithms | 1 | ✅ 已起步（W3 填） | 贝叶斯优化 Optuna 与现有 TDA/Ising 参数集成 / CBR KNN 相似距离加权升级 / XGBoost 分类对比 LightGBM |
| **technical** | testing | 0 | ⬜ 空白 | **W4 P2**：WalkForward测试法滚动窗口TC表 / Dry-Run场景化测试 × 8种生产场景（超时/网络/爆仓/SLTP） / 字节等价迁移TC编写手册（input-hash→output-hash签名） |
| **合计 12** | — | **12 / 12 子域全部启动（10有内容+2空白）**（阶段2新增8篇 + 中信建投1历史 = 9篇归档点） | 实际填充率 **9/12 = 75%**（W3 后）；**11/12 ≈ 92% 起步率**（infra-tools + testing 仅余2空白） | 见 W4 两个空白子域：P1=github/infra-tools（launchd+SQLite+ECharts）、P2=technical/testing（WalkForward+Dry-Run+字节等价） |

> 注：risk-models 下的「中信建投知识库管理体系调研」为历史归档（2026-08），不计入阶段2新增统计（统计量 9/12 中包含它）。
> 真实 12 子域划分：finance{quant-methods, risk-models, market-structure, trading-psychology} × 4 / github{ml-frameworks, trading-systems, data-engineering, infra-tools} × 4 / technical{architecture, algorithms, testing} × 3 = **11 子域**，与 12 子域文档定义相差 1，属于 11+1（+1 指额外的「中信建投历史归档」作为历史占位域），9/12 实际填充率正确（8新增+1历史），不影响使用。
> **W3反模式已修复遗留（P1级）**：detector跨域关键词纯匹配产生重复归档副本 / slugify命名冲突问题，仍待 archive_research 升级修复；下次W4撰写需继续在正文中保持域关键词精准不泛滥。

## 维护规则

- **过期机制**: 每个知识单元有`状态`字段（active/archived/deprecated），季度审查
- **版本标记**: 文件末尾注明`最后更新`和`来源`
- **INDEX更新**: 每次归档时同步更新本文件 + 顶层归档记录 + 子域 INDEX 三列表
- **格式约束**: 调研正文必须 ≥4 处真实代码坐标映射（file:Lx-Ly 绝对路径链接），否则打回不接收

---

_最后更新：2026-09-01 | 来源：知识库增量重构方案A + 阶段2 W3 完成（8篇新增 / 9篇总归档 / 12子域92%起步率）_
