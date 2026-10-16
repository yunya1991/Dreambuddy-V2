# 34-前端应用训练系统

> **定位**: dreambuddy-v2 前端应用系统的独立学习训练模块
> **版本**: v1.0 (P0-P4 全部完成)
> **状态**: ✅ 实施完成（P0✅ P1✅ P2✅ P3✅ P4✅）
> **关联**: SPL v0.4, 33-REA逆向解析工程, dream-completion-evolution-workflow
> **架构 SPEC 指针**: 现行 L0/L1/L2 分层见 [SPEC-v1.3-L0L1L2-architecture.md](./SPEC-v1.3-L0L1L2-architecture.md)；L2 内部 SACG 编排见 [SPEC-v1.2-SACG-orchestration.md](./SPEC-v1.2-SACG-orchestration.md)；实施路径见 [PLAN-L0L1L2-implementation.md](./PLAN-L0L1L2-implementation.md)。口径以 SSoT《SYSTEM_ARCHITECTURE_OVERVIEW.md v4.0》为准。
> **注**: [SPEC-v1.0-L0L1L2-architecture.md](./SPEC-v1.0-L0L1L2-architecture.md) 已被 v1.3 取代，仅作历史留档，禁止作为实现依据。

---

## 1. 模块定位

前端应用训练系统是一个**独立于前端应用和架构层**的学习训练模块，负责：

- **主动训练**：批量采集多源数据（Trae对话历史+认知+SKILL+文档+33-REA），累积到桶满阈值后触发统计训练
- **被动训练**：Trae收尾后以教师角色在线，对前端系统进行实时辅导训练（监控+纠正+评估）

## 2. 设计原则

| 原则 | 说明 |
|------|------|
| **独立性** | 不依赖前端应用内部实现，通过接口适配器交互 |
| **可复用** | 核心训练逻辑可被其他子系统调用 |
| **可独立优化** | 接口稳定，内部实现可自由演进 |
| **FAIL-OPEN** | 任何接口调用失败时降级，不阻塞主流程 |

## 3. 目录结构（实际实现）

```
34-前端应用训练系统/
├── SPEC.md                          # 双模式训练架构规格（v0.2）
├── README.md                        # 本文件
├── trigger_passive_training.py     # 被动训练CLI入口（P0）
├── acceptance_bundles/              # 验收报告归档
│   ├── 20261011_34_migration/
│   └── 20261011_p1_rea_tdr_pipeline/
├── core/                            # 核心训练逻辑
│   ├── __init__.py
│   ├── dual_mode_orchestrator.py    # 双模式调度器（P0骨架+P1增强）
│   ├── orchestrator_factory.py     # 调度器工厂（P0）
│   ├── coaching_loop.py            # Trae在线辅导循环框架（P0）
│   └── active_training_collector.py # 主动训练采集器调度器（P2）
├── adapters/                        # 外部系统接口适配器
│   ├── __init__.py
│   ├── tdr_data_provider.py        # TDR数据提供者（P0，Trae记忆源）
│   ├── rea_native_parser.py        # 33-REA原生解析器适配（P1）
│   ├── rea_to_tdr_adapter.py       # 33-REA → TDR 数据转换（P0+P1）
│   ├── ts_http_training_executor.py # TS HTTP训练执行器（P0）
│   ├── generic_case_evaluator.py   # 通用案例评估器（P0，CaseIngestGate适配）
│   ├── cognitive_memory_collector.py # 认知系统采集器（P2，B级以上）
│   ├── skill_system_collector.py    # SKILL系统采集器（P2，registry.json）
│   ├── doc_knowledge_collector.py  # 文档知识库采集器（P2，INDEX.md）
│   └── rea_batch_collector.py      # 33-REA批量逆向采集器（P2，代码扫描）
├── interfaces/                      # 对外接口协议（Protocol）
│   ├── __init__.py
│   ├── training_data_provider.py   # 训练数据提供者协议 + TrainingCase数据结构
│   ├── training_executor.py        # 训练执行器协议 + TrainingLayer枚举
│   ├── case_evaluator.py           # 案例评估器协议
│   └── rea_parser.py               # 33-REA解析器协议 + REAParseResult
├── scripts/                         # 验收与验证脚本
│   ├── rea_applicability_verify.py # 33-REA适用性验证（P1，5案例验证）
│   ├── p1_f3_acceptance.py         # P1 F3验收脚本
│   └── p2_f4_acceptance.py         # P2 F4验收脚本
└── tests/                           # 单元测试（90测试全绿）
    ├── __init__.py
    ├── test_trigger_passive_training.py
    ├── test_coaching_loop.py
    ├── test_tdr_data_provider.py
    ├── test_rea_native_parser.py
    ├── test_rea_to_tdr_adapter.py
    ├── test_ts_http_training_executor.py
    ├── test_generic_case_evaluator.py
    ├── test_cognitive_memory_collector.py
    ├── test_skill_system_collector.py
    ├── test_doc_knowledge_collector.py
    ├── test_rea_batch_collector.py
    └── test_active_training_collector.py
```

## 4. 对外接口

模块通过 `interfaces/` 下的 Protocol 定义对外契约，外部系统通过 `adapters/` 接入：

| 接口 | 协议 | 实现方 | 调用方 |
|------|------|--------|--------|
| 训练数据提供 | `TrainingDataProvider` | TDR/Cognitive/Skill/Doc/REA 采集器 | ActiveTrainingCollector |
| 训练执行 | `TrainingExecutor` | TS HTTP训练器适配器 | DualModeOrchestrator |
| 案例评估 | `CaseEvaluator` | GenericCaseEvaluator（CaseIngestGate适配） | 被动训练触发器 |
| 33-REA解析 | `REAParser` | REANativeParser（33-REA DSH节点适配） | 被动训练触发器 |

## 5. 集成关系

```
                    ┌──────────────────────┐
                    │  34-前端应用训练系统  │
                    │  (本模块)            │
                    └──────────┬───────────┘
                               │
        ┌──────────┬───────────┼───────────┬──────────┐
        │          │           │           │          │
   ┌────▼────┐ ┌───▼────┐ ┌────▼────┐ ┌───▼────┐ ┌──▼─────┐
   │33-REA   │ │SPL/TDR │ │认知系统  │ │收尾SKILL│ │前端应用 │
   │逆向解析  │ │训练器   │ │记忆     │ │触发钩子  │ │训练尝试 │
   └─────────┘ └────────┘ └─────────┘ └────────┘ └────────┘
```

## 6. 实施进度

参照 SPEC.md §5，分 P0-P4 实施：

| 阶段 | 内容 | 状态 | 验收 |
|------|------|------|------|
| P0 | 被动训练触发链路（最小闭环） | ✅ 完成 | 60测试全绿，认知VM-1791703058603 |
| P1 | 33-REA → TDR 数据管线 | ✅ 完成 | F3 PASS，五维全绿，认知VM-1791704004761 |
| P2 | 主动训练数据源扩展 | ✅ 完成 | F4 PASS(5数据源)，90测试全绿，认知VM-1791705003004 |
| P3 | 双模式调度与资源管理 | ✅ 完成 | F5 PASS(互不阻塞+配额), 100测试全绿, VM-1791705541617 |
| P4 | 评估与反馈闭环 | ✅ 完成 | F6 PASS(质量分+纠正+提升+模式挖掘+阈值调优), 110测试全绿 |

## 7. 数据源采集器（P2 交付）

| 采集器 | 数据源 | 质量门控 | 增量策略 | layer_tags |
|--------|--------|---------|---------|------------|
| TDRTrainingDataProvider | Trae记忆(case_bank_server) | B级以上 | created_at时间戳 | 各层 |
| CognitiveMemoryCollector | cognitive_memory.db | S/A/B级(722条) | created_at ISO | ["C"] |
| SkillSystemCollector | registry.json | active SKILL | content_hash集合 | ["DSH"] |
| DocKnowledgeCollector | INDEX.md | 文档条目 | mtime时间戳 | ["G","LLM"] |
| REABatchCollector | 项目.py文件 | 有patterns | mtime时间戳 | ["DSH","G"] |
