# WORKFLOWS & CONSTRAINTS：工作流与约束层

---

## 一、工作流定义

### 1. 交易决策工作流 (trading-decision/)
```
A0_contradiction/    ← 矛盾分析流程
A1_research/         ← 调研流程
A2_first-principles/ ← 第一性原理流程
A3_simulation/       ← 推演流程
A4_validation/       ← 验证流程
A5_execution/        ← 执行流程
A6_intelligence/     ← 情报流程
A7_audit/            ← 审计流程
A8_theory-practice/  ← 知行检验流程
A9_exit/             ← 离场流程
orchestrator/        ← 编排器
protocol/            ← 通信协议
transports/          ← 传输层
```

### 2. 记忆层工作流 (memory/)
```
memory_engine/       ← L4记忆引擎(核心)
L1_realtime/         ← 实时记忆
L2_shortterm/        ← 短期记忆
L3_longterm/         ← 长期记忆
L4_archive/          ← 档案记忆
distill/             ← 蒸馏流程
index/               ← 索引维护
review/              ← 审查流程
statistics/          ← 统计分析
```

### 3. 知识工作流 (knowledge/)
```
distill/             ← 知识蒸馏
evolution/           ← 知识进化
retrieval/           ← 知识检索
storage/             ← 知识存储
```

### 4. 进化工作流 (evolution/)
```
audit/               ← 进化审计
feedback/            ← 反馈回路
rollback/            ← 回滚管理
sandbox/             ← 沙箱测试
```

### 5. 治理工作流 (governance/)
```
cost-control/        ← 成本控制
gate-audit/          ← 门禁审计
market-research/     ← 市场研究
performance-review/  ← 绩效审查
```

---

## 二、约束层

### 1. 宪法 (constitution/)
系统最高指导哲学。见 00-CORE-宪法与治理.md

### 2. 系统索引 (system-index/)
- `engineering-architecture.md` — 基线架构文档
- QMM量化内核约束(可插拔，固定输出契约)

### 3. workflow-spec（21份规范文档）
| 领域 | 文档 |
|:---|:---|
| 进化P0 | decision-gate, rollback-pointer, scope-freeze, contracts, acceptance-checklist, acceptance-report-0511, acceptance-report-0512 |
| 进化P1 | stage-policy, acceptance-report, policy-template-versioning, regression-matrix-report |
| 进化P2 | approval-gate, ops-automation |
| L4记忆 | 架构与工作流设计 |
| 交易 | trading, governance, communication-contract, protocol-v2, skill-inventory-checklist, a0-a9-checklist, a0-a9-tooling-audit, a0-a9-system-level-checklist |
| 知识 | knowledge |

### 4. QMM量化内核 (qmm/)
QMM-v5愿景、Version-Triple规范、Phase 1-4执行计划、架构定义

### 5. FAQ
OKX_FAQ.md — OKX相关常见问题（踩坑经验）
