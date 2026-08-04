# MU-TRD-CORE — 交易记忆单元核心

> 单元: MU-TRD | 容量: ≤ 2,000 字符 | 上次压缩: 2026-07-27 | 当前占用: ~35%
> 记忆类型: Procedural (程序记忆) + Semantic (语义记忆)

## 交易记忆接口规范（S级 — 程序记忆）

- 统一接口7标准：search/add/update/get/stats/distill_candidates/healthcheck
- 适配器模式：不修改现有L4代码，在其上封装统一接口
- 接口语义隔离：filters字段由各应用记忆自行定义，总记忆不规定具体字段
- 记忆ID规范：AM-TRD-{TYPE}-{RAW_ID}，时间戳必须用微秒级避免冲突

## L4 核心设计（A级 — 语义记忆）

- 三类记忆：case（交易案例）/ review（复盘）/ distill（蒸馏）
- CBR检索：按inst_id/regime/decision等交易字段过滤
- 蒸馏机制：从review中提取模式，生成通用规则
- 健康指标：pipeline_connected、schema_compliance、last_update

## 交易经验 Top 3（A级 — 情景→语义）

1. L4记忆ID必须用微秒级时间戳，避免同秒添加覆盖
2. 记忆search中score=0且有query时应过滤，避免返回无关结果
3. All搜索同score时需类型轮转，否则单一类型占满top_k

## 当前状态

- L4统一接口封装已完成（AM-TRD-001）
- 数据规模：5,018条（457 case + 4,485 review + 76 distill）
- 健康状态：healthy（schema_compliance 93.65%）
