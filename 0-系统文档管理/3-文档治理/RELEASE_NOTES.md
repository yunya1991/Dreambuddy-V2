# 文档体系版本日志 — RELEASE_NOTES

> **版本**: v1.3 | **更新日期**: 2026-08-02
> **定位**: 记录 0-系统文档管理 体系本身的版本变更
> **关联**: [INDEX.md](../INDEX.md) · [DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md)

---

## [v1.3] - 2026-08-02

### 新增

- **变更内容**: 文档管理自动化工具建成 + L3 缺失文档补齐 + 审计机制落地
- **影响范围**: 0-系统文档管理/4-工具与自动化、3-文档治理、L3 辅助模块、10-经典指标系统
- **验证方式**: 4 工具实跑验证 + link_checker 元层 0 断链 + doc_coverage L2 100%

#### 4-工具与自动化建成（P2→已完成）
- [doc_lint.py](../4-工具与自动化/doc_lint.py) — 文档命名/格式/版本头/README-INDEX 冲突检查
- [doc_coverage.py](../4-工具与自动化/doc_coverage.py) — L2/L3 文档覆盖率统计
- [index_generator.py](../4-工具与自动化/index_generator.py) — 目录树自动生成
- [link_checker.py](../4-工具与自动化/link_checker.py) — 跨文档链接校验（含内联代码剥离）
- [4-工具与自动化/README.md](../4-工具与自动化/README.md) 升级为已建设，含 CI 集成示例

#### L3 缺失文档补齐（DD-008 部分关闭）
- [15-监控告警系统/docs/ENGINEERING_INDEX.md](../../15-监控告警系统/docs/ENGINEERING_INDEX.md) v1.0 — 138 函数/38 配置项从代码提取
- [15-监控告警系统/docs/TECHNICAL_DESIGN.md](../../15-监控告警系统/docs/TECHNICAL_DESIGN.md) v1.0 — 6 层架构 + 5 段核心算法伪代码
- [7-产物中台/docs/TECHNICAL_DESIGN.md](../../7-产物中台/docs/TECHNICAL_DESIGN.md) v1.0 — 12 章节/58 接口，修正原文档 5 处与代码不一致
- [3-EVOLUTION/README.md](../../3-EVOLUTION/README.md) v0.1→v0.2 — 补设计概述（9 阶段流水线+三桥接）
- [6-图结构上下文压缩/README.md](../../6-图结构上下文压缩/README.md) v0.1→v0.2 — 补设计概述（双维度编排 5 理念）
- [10-经典指标系统/README.md](../../10-经典指标系统/README.md) v1.0 — 补建缺失 README，L2 覆盖率 97%→100%

#### 审计机制落地
- [AUDIT_REPORT_TEMPLATE.md](./AUDIT_REPORT_TEMPLATE.md) v1.0 — 月度审计报告标准模板
- [audits/2026-08_月度审计报告.md](./audits/2026-08_月度审计报告.md) — 首份基线审计报告

### 修改

- **变更内容**: 元层断链修复 + 文档债刷新
- [DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md) 链接 `../../../` → `../../`（修 2 处断链）
- [INDEX.md](../INDEX.md) 4-工具与自动化 状态刷新、L3 模块状态刷新
- [L3_MODULE_DOC_PLAN.md](./L3_MODULE_DOC_PLAN.md) 现状表刷新（3/6 号 README 已存在）

### 新增文档债务

| ID | 优先级 | 说明 |
|----|--------|------|
| DD-022 | P2 | 全项目 1440 断链需分流排查 + link_checker 增代码白名单 |
| DD-023 | P3 | L3_MODULE_DOC_PLAN 现状过时（已本期修复） |
| DD-024 | P3 | 0-系统文档管理根 README/INDEX 并存（L0 豁免，建议 doc_lint 加豁免规则） |

---

## [v1.2] - 2026-07-31

### 修改

- **变更内容**: P0/P1 文档债批量修复，消除双 v3.0 架构冲突，刷新 17 号导航信息
- **影响范围**: 根目录核心文档 + 0-系统文档管理 全量
- **验证方式**: 链接有效性抽查 + 版本一致性检查

#### P0 权威冲突修复
- 根 [TECHNICAL_DESIGN.md](../../TECHNICAL_DESIGN.md) 降级为 LEGACY 归档，重定向到 SSoT v3.0
- 根 [ENGINEERING_INDEX.md](../../ENGINEERING_INDEX.md) 升级到 v3.0，SSoT 层级表消除双 v3.0 冲突

#### P1 导航信息刷新
- [INDEX.md](../INDEX.md) 17 号从"待建立"改为已建立（v1.0），L2 覆盖率 86%→100%
- [SYSTEM_MAP.md](../2-文档地图/SYSTEM_MAP.md) 新增 17 号子系统条目，6→7 子系统
- [ARCHITECTURE_MAP.md](../2-文档地图/ARCHITECTURE_MAP.md) 修复链接格式错误，17 号标为已建立
- [INDEX.md](../INDEX.md) 修复不存在的 MEMORY_SYSTEM_ARCHITECTURE.md 引用
- 16 号 TECHNICAL_DESIGN 评级从 C（范围错位）改为 A（DD-004 已修复 v2.0）
- [DOC_QUALITY_AUDIT.md](./DOC_QUALITY_AUDIT.md) 升级到 v1.1，质量状态表纳入 17 号，修正 16 号评级

#### 文档债关闭
- DD-002/003（架构文档过时/散落）— 已关闭
- DD-004（16 号 TECHNICAL_DESIGN 范围错位）— 已关闭
- DD-005（13 号 ENGINEERING_INDEX 缺版本号）— 已关闭
- DD-017（记忆系统接口契约 SPEC）— 已关闭
- DD-018（认知系统 TECHNICAL_DESIGN）— 已关闭

---

## [v1.1] - 2026-07-31

### 新增

- **变更内容**: 记忆系统与认知系统文档补齐
- **影响范围**: 4-MEMORY 子系统

#### 新增文档
- [4-MEMORY/6-应用记忆索引/MEMORY_INTERFACE_SPEC.md](../../4-MEMORY/6-应用记忆索引/MEMORY_INTERFACE_SPEC.md) — 记忆系统接口契约统一 SPEC（关闭 DD-017）
- [4-MEMORY/9-工具与接口/docs/TECHNICAL_DESIGN.md](../../4-MEMORY/9-工具与接口/docs/TECHNICAL_DESIGN.md) — 认知系统技术设计（关闭 DD-018）

### 修改
- [DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md) 升级到 v1.2，文档债务率 35%→24%

---

## [v1.0] - 2026-07-25

### 新增

- **变更内容**: 0-系统文档管理 元层建立
- **影响范围**: 全项目文档体系
- **验证方式**: 检查 0-系统文档管理/ 目录结构完整性
- **回滚策略**: 删除 0-系统文档管理/ 目录，恢复 PROJECT_DOC_STANDARD.md 原位

#### P0 骨架
- 建立 [0-系统文档管理/README.md](../README.md) 总入口
- 建立 [0-系统文档管理/INDEX.md](../INDEX.md) 全项目文档索引（L0/L1/L2/L3 分层 + 主题索引 + 覆盖率统计）

#### P1 规范体系
- 迁移 PROJECT_DOC_STANDARD.md v1.1 → [1-规范体系/DOC_STANDARD.md](../1-规范体系/DOC_STANDARD.md) v2.0
- 新增 [1-规范体系/DOC_CLASSIFICATION.md](../1-规范体系/DOC_CLASSIFICATION.md) 文档分类体系（L0-L3 分级 + 7 类角色 + 命名规范）
- 新增 5 份文档模板：
  - [TEMPLATES/README_TEMPLATE.md](../1-规范体系/TEMPLATES/README_TEMPLATE.md)
  - [TEMPLATES/ENGINEERING_INDEX_TEMPLATE.md](../1-规范体系/TEMPLATES/ENGINEERING_INDEX_TEMPLATE.md)
  - [TEMPLATES/TECHNICAL_DESIGN_TEMPLATE.md](../1-规范体系/TEMPLATES/TECHNICAL_DESIGN_TEMPLATE.md)
  - [TEMPLATES/API_SPEC_TEMPLATE.md](../1-规范体系/TEMPLATES/API_SPEC_TEMPLATE.md)
  - [TEMPLATES/CHANGELOG_TEMPLATE.md](../1-规范体系/TEMPLATES/CHANGELOG_TEMPLATE.md)

#### P2 文档地图
- 新增 [2-文档地图/SYSTEM_MAP.md](../2-文档地图/SYSTEM_MAP.md) 全系统文档地图（1 元层 + 7 顶层 + 6 子系统 + 6 辅助）
- 新增 [2-文档地图/TOPIC_MAP.md](../2-文档地图/TOPIC_MAP.md) 主题索引（10 个主题跨系统导航）
- 新增 [2-文档地图/ARCHITECTURE_MAP.md](../2-文档地图/ARCHITECTURE_MAP.md) 架构文档地图（当前实际架构 + 债务）

#### P3 文档治理
- 新增 [3-文档治理/DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md) 文档技术债清单（9 项待修复 + 6 项已关闭）
- 新增 [3-文档治理/DOC_LIFECYCLE.md](./DOC_LIFECYCLE.md) 文档生命周期管理（5 阶段 + 状态定义 + 审计流程）
- 新增 [3-文档治理/DOC_QUALITY_AUDIT.md](./DOC_QUALITY_AUDIT.md) 文档质量审计标准（5 维度 + 评分标准 + 检查项）

### 修改

- **变更内容**: PROJECT_DOC_STANDARD.md 改为重定向到 0-系统文档管理/1-规范体系/DOC_STANDARD.md
- **影响范围**: 根目录 PROJECT_DOC_STANDARD.md
- **验证方式**: 访问根目录 PROJECT_DOC_STANDARD.md 应看到重定向提示
- **回滚策略**: 恢复 PROJECT_DOC_STANDARD.md 原内容

### 关联变更

#### P4 衔接（根目录与元层对齐）
- **README.md** 瘦身为极简入口（257 行 → 80 行），文档导航统一指向 0-系统文档管理
- **PROJECT_DOC_STANDARD.md** 替换为重定向锚点，指向 0-系统文档管理/1-规范体系/DOC_STANDARD.md
- **DEBT_INDEX.md** 升级到 v2.3，新增与 0-系统文档管理/DOC_DEBT_INDEX.md 的双向引用，补充 S4 步骤记录
- **ENGINEERING_INDEX.md**（根）SSoT 层级表新增 0-系统文档管理 与 DOC_STANDARD.md 条目
- **0-系统文档管理/README.md** 修正 SSoT 引用，从 PROJECT_DOC_STANDARD.md 改为 DOC_STANDARD.md

---

## 版本策略

- **主版本号**（X.0）：重大结构变更（如新增子目录、改变分级体系）
- **次版本号**（X.X）：内容增补或修订（如新增模板、更新地图）
- **修订号**（X.X.X）：小幅修正（如修复链接、错别字）

---

**文档版本**: v1.2
**最后更新**: 2026-07-31
