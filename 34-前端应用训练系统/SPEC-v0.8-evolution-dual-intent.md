# SPEC v0.8 — 自进化系统双链路意图训练（contradiction_insight / path_insight）

> 版本: v0.8 | 日期: 2026-10-15 | 状态: 评估完成，SPEC 已形成
> 前置: SPEC-v0.7-data-query-intent（第一层 data_query / 第二层 data_insight）

## 1. 背景与能力分层

前端数据能力分三层递进：

| 层级 | 意图 | 能力 | 数据来源 |
|---|---|---|---|
| 第一层 | data_query | 静态查询：某数据当前值 | 18-数据获取中心 |
| 第二层 | data_insight | 单一数据变化的金融含义 | 9-基本面分析 |
| **第三层（本 SPEC）** | contradiction_insight / path_insight | **多数据动态交汇的金融含义** | **23-自进化系统** |

9-基本面反映单一数据变化的金融含义；23-自进化系统中的矛盾系统 + 矛盾 Transformer 则在单一数据之上，进一步实现**多数据动态交汇**的金融含义——这是第三层能力。

## 2. 评估结论（基于代码与数据事实）

### 2.1 两条链路在 23 系统中真实独立存在

- **链路 A：矛盾系统**（contradiction_identifier.py）——C1-C8 多维矛盾识别（C1 资金面/C2 情绪面/C3 技术面/C4 宏观/C6 时序/C7 隐性/C8 等），输出各维度矛盾方向与强度；
- **链路 B：矛盾 Transformer**（cross_attention.py + hjb_solver.py）——QKV 注意力定位主要矛盾、多头注意力并行评估多矛盾维度、最小阻力路径求解最优交易路径。

### 2.2 数据输出形态已验证可用

- evolution_pipeline.log：`[Contradiction] dim=C8 dir=long strength=0.000`（矛盾维度日志，21:25 仍在实时产出）、`[PathLayer] 路径发现覆盖 d*: neutral→long`（路径决策日志）；
- evolution_snapshots.json：147 个币种的快照，含 dimension_predictions（C2/C3/C6/C8 各维度预测）、action、level0_dstar、cbr_sim 等。

### 2.3 双链路分别意图训练、最后交汇的设计成立

两链路认知模式不同（矛盾识别 vs 路径求解），问法语义可区分，适合独立意图类型分别训练；交汇点在 S 层最终意图分类——两条链路各自训练自己的意图，最终在 S 层统一分类输出，与系统自身『只在最后交汇』的架构一致。

## 3. 意图定义

### 3.1 链路 A：contradiction_insight（矛盾分析意图）

- **能力**: 用户询问多数据之间的矛盾/一致关系时，识别为矛盾分析意图，返回 C1-C8 维度矛盾方向与强度解读。
- **典型问法**: 『现在资金面和技术面矛盾吗』『各维度矛盾情况怎么样』『当前主要矛盾是什么』『宏观和情绪面一致吗』

### 3.2 链路 B：path_insight（最小阻力路径意图）

- **能力**: 用户询问多数据交汇后的最优方向/路径时，识别为路径意图，返回矛盾 Transformer 的维度预测交汇结果与路径决策。
- **典型问法**: 『多维度综合看BTC该往哪走』『最小阻力路径是什么方向』『各维度交汇后结论是什么』『综合判断现在该多还是空』

## 4. 采集器设计（两个，分别对应两条链路）

### 4.1 contradiction_collector（链路 A）

- **数据来源**: evolution_pipeline.log 的 `[Contradiction] dim=... dir=... strength=...` 行 + `[T5-DimForce]` 维度力评估行；
- **样本生成**: 从日志提取各维度矛盾方向/强度 → 结合问法模板生成 (message, intent_type='contradiction_insight') 训练案例；
- **样本字段**: layer_tags=['S']，metadata 含 dim/dir/strength。

### 4.2 evolution_path_collector（链路 B）

- **数据来源**: evolution_snapshots.json 的 dimension_predictions（多维度预测交汇）+ action/level0_dstar（路径决策）+ `[PathLayer]` 日志行；
- **样本生成**: 从快照提取币种的多维预测交汇与最终动作 → 结合问法模板生成 (message, intent_type='path_insight') 训练案例；
- **样本字段**: layer_tags=['S']，metadata 含 symbol/dimension_predictions/action。

### 4.3 共同约束

- 实现 TrainingDataProvider 协议，与其他采集器同构；
- FAIL-OPEN：日志/快照缺失或解析失败返回空列表；
- 增量采集：按文件修改时间过滤，避免重复样本。

## 5. 接入与交汇点

1. 两个采集器注册到 run_continual_training.py 采集器列表（v0.7 后为 23 个数据源）；
2. 分别训练 contradiction_insight 与 path_insight 两个独立意图类型——**双链路分别意图训练**；
3. **交汇**: S 层意图模型统一分类输出（predictIntent），两链路意图在最终分类时交汇，与 23 系统自身架构一致；
4. 执行闭环（后续版本）: contradiction_insight → 查矛盾维度日志/快照返回矛盾解读；path_insight → 查快照返回多维交汇与路径决策。

## 6. 验收标准

1. 持续训练运行后，S 层意图模型出现 contradiction_insight 和 path_insight 意图类型；
2. 两个采集器各产出 ≥ 10 条样本/次；
3. 喂入 S 层全部成功（失败 0）；
4. 既有验收不回退（v0.5 P3 + v0.7 两意图权重不下降）。

## 7. 边界与非目标

- 本 SPEC 覆盖采集器与意图训练；执行闭环（识别后查 23 系统数据返回解读）为后续版本；
- 不修改 23 系统自身代码，只读取其日志与快照输出；
- 不修改 S 层训练循环核心逻辑。
