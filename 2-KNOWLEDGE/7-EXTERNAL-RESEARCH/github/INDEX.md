# github — GitHub开源调研

> 开源项目分析、框架对比、最佳实践借鉴的调研归档。

## 子类

| 子目录 | 说明 | 典型主题 |
|--------|------|---------|
| [ml-frameworks/](./ml-frameworks/) | 机器学习框架 | LangGraph状态机、LightGBM、filterpy |
| [trading-systems/](./trading-systems/) | 交易系统 | 开源量化框架对比、freqtrade、jesse |
| [data-engineering/](./data-engineering/) | 数据工程 | 数据清洗、特征工程、Medallion架构 |
| [infra-tools/](./infra-tools/) | 基础设施工具 | launchd、SQLite优化、ECharts |

## 已归档调研

### trading-systems（交易系统）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [开源量化框架对比freqtrade/jesse/vnpy调研](./trading-systems/2026-09-01-开源量化框架对比freqtrade-jesse-vnpy调研.md) | 2026-09-01 | 12维总览表；Jesse回测-60%加速4技巧；FreqAI Screen1七维评分数据驱动权重；vn.py CTP接口扩展；4项踩坑复盘；集成决策矩阵（做什么/永远不做什么） |

### data-engineering（数据工程）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [Medallion三层奖章架构与Tushare特征Silver门禁调研](./data-engineering/2026-09-01-Medallion三层奖章架构与Tushare特征Silver门禁调研.md) | 2026-09-01 | Databricks原Medallion×Delta Lake Bronze++/Silver++/Lakehouse 三维对照；Tushare/AKShare/Yahoo 9维数据源质量；三级异常过滤链3σ/IQR/动态ATR假阳率权衡；Bronze/Silver/Gold 3层×DreamBuddy真实存储路径映射；10文件11处真实代码坐标；5档质量硬门禁表；4条P1迭代建议（Bronze审计拒绝队列/连续异常第4级IQR补偿/quality.py硬门禁对齐G7 95%/Tushare适配器） |

### ml-frameworks（机器学习框架）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [LangChain检索架构调研](./ml-frameworks/2026-09-01-langchain检索架构调研.md) | 2026-09-01 | 7层Retriever全图谱；DreamBuddy 11维对照矩阵；FAISS/编码/依赖/遥测6大坑位复盘；RRF/MultiQuery/FlashRank3项集成建议 |

---

_最后更新：2026-09-01_
