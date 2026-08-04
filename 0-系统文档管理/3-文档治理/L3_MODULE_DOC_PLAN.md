# L3 辅助模块文档规划 — L3_MODULE_DOC_PLAN

> **版本**: v1.1 | **更新日期**: 2026-08-02
> **定位**: L3 辅助模块的文档现状评估与建设规划
> **关联**: [DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md) DD-008 · [DOC_STANDARD.md](../1-规范体系/DOC_STANDARD.md)

---

## 1. 现状评估（2026-08-02 刷新）

| 模块 | 目录 | 现有文档 | 文档状态 | 模块状态 | 优先级 |
|------|------|----------|----------|----------|--------|
| 3-EVOLUTION | `3-EVOLUTION/` | README.md v0.2（含设计概述） | 🟡 README 已建 | 🧪 实验状态，未集成 | P3-低 |
| 6-图结构上下文压缩 | `6-图结构上下文压缩/` | README.md v0.2 + SPEC/TECHNICAL-DOC/IMPLEMENTATION/THEORY | 🟡 README+4 非标准文档 | 🧪 实验状态 | P3-低 |
| 7-产物中台 | `7-产物中台/` | docs/ENGINEERING_INDEX.md, docs/FAQ.md, docs/TECHNICAL_DESIGN.md v1.0 | 🟡 部分（TD 已补） | ✅ 运行中 | P2-中 |
| 15-监控告警系统 | `15-监控告警系统/` | README.md + docs/ENGINEERING_INDEX.md v1.0 + docs/TECHNICAL_DESIGN.md v1.0 | 🟡 部分（IDX+TD 已补） | ✅ 运行中 | P2-中 |
| experiments | `experiments/` | INDEX.md | 🟡 仅索引 | 🧪 实验状态 | P3-低 |
| 1-ARCHITECTURE/dreamos | `1-ARCHITECTURE/dreamos/` | docs/ENGINEERING_INDEX.md, docs/TECHNICAL_DESIGN.md | 🟡 部分 | ✅ 运行中 | P3-低 |

> **本期进展（2026-08-02）**：3-EVOLUTION/6-图结构 README 由 v0.1 增强至 v0.2（补设计概述）；15-监控告警补建 ENGINEERING_INDEX+TECHNICAL_DESIGN；7-产物中台补建 TECHNICAL_DESIGN（修正原文档 5 处与代码不一致）。剩余：15/7 号 API_SPEC+CHANGELOG、experiments README。

---

## 2. 建设策略

### 2.1 分级原则

L3 辅助模块不需要强制遵循 L2 子系统的 5 文档标准。根据模块状态采取分级策略：

| 模块状态 | 文档要求 | 理由 |
|----------|----------|------|
| ✅ 运行中 | README + ENGINEERING_INDEX + TECHNICAL_DESIGN（3 文档起） | 运行中系统需可维护 |
| 🧪 实验状态 | README + SPEC（2 文档起） | 实验项目只需说明设计和用法 |
| 📦 归档 | README 标注归档 | 仅需说明归档原因 |

### 2.2 建设计划

#### P2-中（运行中模块，优先补齐）

**15-监控告警系统**：
- 现状：仅 README.md
- 计划：补建 docs/ENGINEERING_INDEX.md（文件级索引）+ docs/TECHNICAL_DESIGN.md（核心架构：UnifiedMonitor + MonitorAdapter + 飞书告警 + 调度器）
- 依据：系统已运行，monitor_core.py + feishu_alert.py + scheduler.py 需要文档支撑维护

**7-产物中台**：
- 现状：docs/ENGINEERING_INDEX.md + FAQ.md（部分完整）
- 计划：补建 docs/TECHNICAL_DESIGN.md（产物管理 + 投递中台架构）
- 依据：已有索引，需补技术设计

#### P3-低（实验模块，按需补齐）

**3-EVOLUTION**：
- 现状：无文档，纯 TypeScript 实验代码
- 计划：创建 README.md 标注实验状态 + 设计概述
- 依据：未集成到主线，暂不需要完整文档

**6-图结构上下文压缩**：
- 现状：有 4 个非标准 .md（SPEC/TECHNICAL-DOC/IMPLEMENTATION/THEORY-AND-PRACTICE）
- 计划：将现有文档归入 docs/ 目录，创建 README.md 作为入口
- 依据：已有文档基础，需规范化目录结构

**experiments**：
- 现状：仅 INDEX.md
- 计划：保持现状（实验目录，INDEX.md 足够）
- 依据：实验性质，无需完整文档

---

## 3. 执行路线图

| 阶段 | 任务 | 预计工时 | 前置条件 |
|------|------|----------|----------|
| Phase 3-1 | 15-监控告警补建 ENGINEERING_INDEX + TECHNICAL_DESIGN | 4h | 无 |
| Phase 3-2 | 7-产物中台补建 TECHNICAL_DESIGN | 3h | 无 |
| Phase 3-3 | 6-图结构文档规范化（归入 docs/ + README） | 2h | 无 |
| Phase 3-4 | 3-EVOLUTION 创建 README（标注实验状态） | 1h | 无 |
| 持续 | experiments 保持现状 | 0h | - |

**总计**：约 10h（原估 16h，分级后优化）

---

## 4. 验收标准

- 运行中模块（15/7）：README + ENGINEERING_INDEX + TECHNICAL_DESIGN 3 文档齐全
- 实验模块（3/6/experiments）：README 或 SPEC 存在，标注模块状态
- 所有文档符合 DOC_STANDARD 版本头要求

---

**文档版本**: v1.0
**最后更新**: 2026-07-31
