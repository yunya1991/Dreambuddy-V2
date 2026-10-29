# SPEC v1.0 — 统一语料处理器与两阶段领域训练

> 状态：已批准（2026-10-25，用户裁决）
> 关联：SPEC-意图扩展自动化演进-影子灰度小模型.md（E3 评测器训练）、SPEC-v0.5-continual-training.md（5 层训练循环）

## 1. 背景与目标

E3 评测器训练样本盘点修正后为 1177 条（≥500 门槛达标），但全系统存在 140 万+ 行数据文件与数百份系统文档。本 SPEC 定义**统一语料处理器（Unified Corpus Processor, UCP）**，将全系统异构数据处理为分层训练语料，支撑两阶段训练，使 RBT3 从『意图分类器』升级为『真正理解系统的领域模型』。

**目标**：
1. 领域适应预训练语料：5-10 万句（清洗后）
2. 意图分类对：1200 条（现有）→ 3000-5000 条（清洗扩展后）
3. 评测器监督数据：104 条 verdict（加权采样处理不平衡）
4. 对比学习对：1-2 万条（采样自 10 万行检索映射）

## 2. 数据价值分层（实测抽样结论）

| 价值层 | 数据源 | 规模 | 训练用途 |
|---|---|---|---|
| 高 | retrieval_memory_map 查询-文档对 | 10 万行 | 对比学习/语义检索（query→heading→source_file 三元组） |
| 高 | 训练检查点 semanticSamples + message-intent 对 | 906+167 条 | 意图分类监督数据 |
| 高 | 提案评审结论（verdict） | 104 条 | 评测器三分类监督数据 |
| 中 | trader_log 决策消息（中文 CBR/风控推理） | 30 万行 | 领域预训练语料（需模板去重） |
| 中 | alerts 告警消息、33 系统 training_cases、39 系统 semantic_events | 3 万行 | 领域预训练 + 事件理解 |
| 中 | 全系统 SPEC/README/文档 | 数百份 md | 领域适应预训练核心语料 |
| 低 | sim_trades_audit、shadow_rl_samples | 42 万行 | 不纳入（纯 API 记录/数值对，引入噪声） |

## 3. 统一处理器架构（四层）

```
┌─────────────────────────────────────────────┐
│ 1. 采集层  格式适配器：按 schema 自动识别数据类型  │
│    (message-intent 对 / query-doc 对 / 日志流 /  │
│     事件流 / md 文档按章节切分)                  │
├─────────────────────────────────────────────┤
│ 2. 清洗层  模板消息去重 / 密钥路径脱敏 /          │
│    最短长度过滤 / 坏行跳过                       │
├─────────────────────────────────────────────┤
│ 3. 转换层  按训练任务分桶：                      │
│    ① 分类对 (message→intent)                   │
│    ② 对比对 (query→document)                   │
│    ③ 预训练语料 (纯文本, MLM 任务)              │
├─────────────────────────────────────────────┤
│ 4. 训练层  两阶段训练（见 §4）                   │
└─────────────────────────────────────────────┘
```

### 3.1 采集层适配器

| 适配器 | 输入 | 识别特征 | 输出 |
|---|---|---|---|
| intent_pair | jsonl | 含 message + intent 字段 | 分类对 |
| query_doc | retrieval_memory_map.jsonl | memory_id + query + heading | 对比对 |
| log_stream | trader_*.jsonl / alerts.jsonl | ts + level + msg/message | 预训练语料（msg 字段） |
| event_stream | semantic_events / training_cases | term + raw / case_type | 预训练语料 |
| markdown_doc | SPEC/README/*.md | md 文件 | 章节切分预训练语料 |

### 3.2 清洗规则

1. **模板去重**：同一消息文本全库仅保留 1 条（trader_log 实测重复率 >80%）
2. **脱敏**：正则剔除 API key/token/绝对路径中的敏感段
3. **长度过滤**：预训练语料 ≥10 字符；分类对 message ≥4 字符
4. **坏行跳过**：JSON 解析失败静默跳过并计数

### 3.3 产出物（落盘 34 系统 corpus/ 目录）

```
corpus/
├── pretrain_corpus.jsonl      # 预训练语料（MLM）
├── intent_pairs.jsonl        # 意图分类对
├── query_doc_pairs.jsonl    # 对比学习对
├── evaluator_labels.jsonl    # 评测器 verdict 监督数据
└── corpus_stats.json         # 处理统计（各源输入/清洗/产出计数）
```

## 4. 两阶段训练策略

### 阶段一：领域适应预训练（MLM）
- 基座：RBT3（hfl/chinese-roberta-wwm-ext，已下载 models/rbt3_base）
- 语料：pretrain_corpus.jsonl（≤10 万句，CPU 约数小时）
- 目的：习得系统术语（PoE/ADR/FAIL-OPEN/L0-L1-L2/CBR/风控阈值等）

### 阶段二：任务微调
- ① 意图分类：intent_pairs.jsonl（加权采样）
- ② 评测器三分类：evaluator_labels.jsonl（verdict 102:1:1 极不平衡 → 类加权）
- ③ 可选：query-doc 对比学习

### 验收标准
- E3 基线：评测器与自动评审一致率 ≥90%（连续 3 轮，spec §E3）
- 领域预训练增益：阶段一后评测器一致率相对基线提升可测量
- 处理器可增量运行（复用 34 系统闭环模式）

## 5. 风险与约束

1. **硬件**：4 核 CPU 无 GPU——预训练语料 ≤10 万句；对比对采样 1-2 万
2. **噪声**：低价值层不纳入；模板日志去重后纳入
3. **不平衡**：verdict 类加权采样，防退化为全预测 reject
4. **时效**：处理器支持增量运行（--since 时间戳过滤）

## 6. 实施计划

| 步骤 | 内容 | 验收 |
|---|---|---|
| S1 | SPEC 文档落盘 | 本文档 |
| S2 | 统一处理器脚本 scripts/unified_corpus_processor.py | 五适配器 + 清洗 + 分桶落盘 |
| S3 | 处理器全量运行 | corpus_stats.json 产出 + 语料规模达标 |
| S4 | E3 基线训练（现有 1177 条） | 训练完成 + 评测指标落盘 |
| S5 | 阶段一领域预训练 | MLM loss 下降 + 检查点保存 |
| S6 | 阶段二任务微调 + 一致率对比 | 一致率报告（基线 vs 领域预训练） |

## 7. ADR 记录

- adr_20261025_ucp_spec：SPEC v1.0 批准（用户裁决：现有数据够用，统一处理器扩展语料规模与质量）
