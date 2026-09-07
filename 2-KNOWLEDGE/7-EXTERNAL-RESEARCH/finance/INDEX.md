# finance — 传统金融调研

> 传统量化金融方法、风控模型、市场结构、交易心理的调研归档。

## 子类

| 子目录 | 说明 | 典型主题 |
|--------|------|---------|
| [quant-methods/](./quant-methods/) | 量化方法 | Kalman Filter、PCA共振、IC/MI信息系数、WalkForward |
| [risk-models/](./risk-models/) | 风控模型 | VaR、Kelly公式、动态仓位、组合熔断 |
| [market-structure/](./market-structure/) | 市场结构 | 订单簿、流动性、CME缺口、减半周期 |
| [trading-psychology/](./trading-psychology/) | 交易心理 | 恐贪指数、情绪周期、行为金融学 |

## 已归档调研

### risk-models（风控模型）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [中信建投知识库管理体系调研](./risk-models/中信建投知识库管理体系调研.md) | 2026-08 | 传统券商知识库治理框架、版本控制、权限体系的调研与对照分析 |

### market-structure（市场结构）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [订单簿流动性与减半周期调研](./market-structure/2026-09-01-订单簿流动性与减半周期调研.md) | 2026-09-01 | BTC四次减半四相位时钟（当前danger期≤30%仓）；订单簿D1×D2×D3三维流动性分数模型（V15选币分层LARGE/MID）；CME缺口12年样本规律；周末UTC-低流动性陷阱时间表；V4+马丁+Screen直接消费 |

### trading-psychology（交易心理）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [恐贪指数与行为金融8大偏误情绪校准调研](./trading-psychology/2026-09-01-恐贪指数与行为金融8大偏误情绪校准调研.md) | 2026-09-01 | CNN vs Crypto FGI 双恐贪指数7维对照；卡尼曼8大偏误×DreamBuddy 4阶段防偏门 48格参数表；τ=24h exp衰减情绪与FGI冲突消解规则；恐惧0-25×五计总分3档×仓位cap 12格系数矩阵；9文件14处真实代码坐标；4条P1迭代建议（fgi_score注入/周末z-score/BCRM2一致性校验/新闻语料去重） |

### quant-methods（量化方法）
| 文件 | 调研日期 | 摘要 |
|------|----------|------|
| [Kalman滤波量化实战调研](./quant-methods/2026-09-01-kalman滤波量化实战调研.md) | 2026-09-01 | pykalman+numpy双实现FAIL-OPEN；Q/R随波动率+价差动态调参；MSE降29.9%；6处真实代码坐标；3处反模式提醒 |

---

_最后更新：2026-09-01（W3 批量填充后）_
