# 35-广义认知系统协作模块

> **定位**: 跨系统协作的**纯文档统筹层** — 收纳广义认知系统协作的 SPEC 蓝图、协作接口契约、协同设计文档。
> 不含代码实现（代码实现层留在各子系统内），只做协作设计的 SSoT（Single Source of Truth）。

## 为什么需要这个模块

**痛点**: 跨系统协作的统筹 SPEC 散落在项目根目录，既未纳入 `0-系统文档管理` 的索引体系，也没有归属模块。随着协作链路增多（认知系统 ↔ 33-REA ↔ SKILL管理 ↔ 知识库 ↔ 文档管理），散落文档会导致：
- 协作接口约定无统一归属，各子系统各自理解导致认知漂移
- SPEC 修订后引用方难定位（17 处代码注释引用 SPEC 名但无路径）
- 新协作者无法快速找到"跨系统怎么协作"的权威文档

**本模块的职责**: 把散落的协作统筹 SPEC 收敛 + 新建协作接口契约，作为跨系统协作设计的单一事实源。

## 核心原则

- **纯文档统筹**: 只管 SPEC/设计文档/接口契约，不移动代码实现层
- **SSoT 不重叠**: `0-系统文档管理` 管文档元层（规范/地图/治理），`1-ARCHITECTURE` 管架构事实源，本模块管**协作设计**
- **实现层不动**: `4-MEMORY/9-工具与接口/` 的代码（cognitive_loop_entry.py / evidence_ledger.py 等）保留原位，避免破坏 import 路径
- **契约驱动**: 协作接口先在本模块定义契约，各子系统按契约实现

## 文档清单

| 文档 | 职责 | 状态 |
|---|---|---|
| [SPEC-CognitiveSystem-Evolution.md](./SPEC-CognitiveSystem-Evolution.md) | 大认知系统进化蓝图：四层架构(L1基础→L4元认知) + 五系统接线 + PoE/因果/预测编码升级路线 | v0.2 评审后修改 |
| [SPEC-Unified-PoE-Framework.md](./SPEC-Unified-PoE-Framework.md) | 统一 PoE 框架：双模式(重型/轻量) + 有界信任传递 + 6 失效条件 + Evidence Index | v2.0 用户确认 |
| [INDEX.md](./INDEX.md) | 模块内文档索引 + 与各子系统协作关系图 | v1.0 |
| [COLLABORATION-CONTRACT.md](./COLLABORATION-CONTRACT.md) | 跨系统协作接口契约：record_hook/verify_hook/Evidence Ledger/PoE 信任链路 | v1.0 |

## 与各子系统的关系

```
35-广义认知系统协作模块（本模块 — 协作设计 SSoT）
    │
    │ 定义协作契约
    ├──→ 4-MEMORY（认知系统实现层：cognitive_loop_entry.py / evidence_ledger.py）
    ├──→ 33-REA逆向解析工程（重型 PoE + Evidence-First 逆向分析）
    ├──→ 2-KNOWLEDGE（知识库 RAG + memory_bridge）
    ├──→ 0-系统文档管理（文档元层：规范/地图/治理）
    └──→ 3-EVOLUTION（自进化系统）
```

**边界约定**:
- 本模块**只写协作设计**（SPEC + 契约），不写代码实现
- 各子系统的**内部设计**由各子系统自己的 TECHNICAL_DESIGN.md 管
- 本模块的**协作接口契约**是跨系统调用的权威定义，各子系统实现必须遵循

## 快速导航

- 想了解大认知系统怎么进化 → [SPEC-CognitiveSystem-Evolution.md](./SPEC-CognitiveSystem-Evolution.md) §2 四层架构
- 想了解 PoE 双模式和信任传递 → [SPEC-Unified-PoE-Framework.md](./SPEC-Unified-PoE-Framework.md) §2
- 想了解跨系统接口怎么调 → [COLLABORATION-CONTRACT.md](./COLLABORATION-CONTRACT.md)
- 想看文档索引 → [INDEX.md](./INDEX.md)

## 维护

- 新增协作 SPEC / 契约修订时更新 [INDEX.md](./INDEX.md)
- 代码实现层变更后，同步检查本模块契约是否需要更新
- 由 `0-系统文档管理/4-工具与自动化/doc_coverage.py` + `link_checker` 校验断链
