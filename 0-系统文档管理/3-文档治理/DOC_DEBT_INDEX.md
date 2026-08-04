# 文档技术债清单 — DOC_DEBT_INDEX

> **版本**: v2.1 | **更新日期**: 2026-08-02
> **定位**: 文档类技术债的专项管理清单，从 [DEBT_INDEX.md](../../DEBT_INDEX.md) DOC 类债务抽离细化
> **关联**: [DEBT_INDEX.md](../../DEBT_INDEX.md)（代码债）· [DOC_QUALITY_AUDIT.md](./DOC_QUALITY_AUDIT.md) · [audits/](./audits/)（审计报告）

---

## 1. 文档债务清单

### 1.1 P1 高优先级

| ID | 子系统 | 债务项 | 说明 | 状态 | 关联 DEBT_INDEX |
|----|--------|--------|------|------|-----------------|
| — | — | — | P1 全部已关闭，详见 §2 | — | — |

### 1.2 P2 中优先级

| ID | 子系统 | 债务项 | 说明 | 状态 | 关联 DEBT_INDEX |
|----|--------|--------|------|------|-----------------|
| DD-008 | L3 辅助模块 | 5 个模块无完整文档 | 15/7 号已补 ENGINEERING_INDEX+TECHNICAL_DESIGN；剩余 15/7 API_SPEC+CHANGELOG、experiments README | 🟡 进行中 | — |
| DD-022 | 全项目 | 1440 断链需分流 | link_checker 全项目扫描出 1440/2373 断链，多为子系统文档引用代码/归档文件；需增代码白名单后重新基线 | 🔴 待办 | — |

### 1.3 P3 低优先级

| ID | 子系统 | 债务项 | 说明 | 状态 | 关联 DEBT_INDEX |
|----|--------|--------|------|------|-----------------|
| DD-024 | 0-系统文档管理 | 根 README/INDEX 并存 | L0 元层设计合理，建议 doc_lint 增 L0 豁免规则 | 🟡 豁免 | — |
| DD-006/007 | 多子系统 | 冗余历史文档 | 10 号根目录散落 .md 已清理，持续维护 | 🟡 持续 | — |

---

## 2. 已关闭债务

| ID | 子系统 | 债务项 | 关闭日期 | 关闭方式 |
|----|--------|--------|----------|----------|
| DD-001 | 10-经典指标系统 | 技术文档位置偏差 | 2026-07-31 | git mv 迁入 docs/TECHNICAL_DESIGN.md + 更新全项目引用 |
| DD-002 | 1-ARCHITECTURE | 架构总览过时 | 2026-07-31 | README 重写为 v3.0 导航入口，指向 SSoT |
| DD-003 | 1-ARCHITECTURE | 架构文档散落 | 2026-07-31 | SSoT v3.0 定位明确，旧文档标归档 |
| DD-004 | 16-调控系统 | TECHNICAL_DESIGN 范围错位 | 2026-07-31 | 重写 v2.0，19 文件全覆盖 |
| DD-005 | 13-通用风控模块 | ENGINEERING_INDEX 缺版本号 | 2026-07-31 | 补齐 v1.0 版本号头部 |
| DD-010 | 12-三屏趋势系统 | 双索引冲突 + trend-system 并行目录 | 2026-07-31 | S1-1 路径统一 + git rm 根目录重复 ENGINEERING_INDEX.md（docs/ 为唯一权威位置） |
| DD-011 | 16-调控系统 | ENGINEERING_INDEX 严重过时 | 2026-07-25 | S1-2 重建 v2.0 |
| DD-012 | 10-经典指标系统 | 索引断链 | 2026-07-25 | S1-3 修复引用 |
| DD-013 | 5 个子系统 | CHANGELOG 缺失 | 2026-07-25 | S2 补全 5 份 CHANGELOG.md |
| DD-014 | 5 个子系统 | API_SPEC 缺失 | 2026-07-25 | S2 补全 5 份 API_SPEC.md |
| DD-015 | 16-调控系统 | auto_exit_system 函数不存在 | 2026-07-25 | 修复为调用 a9_exit_decision_handler |
| DD-016 | 16-调控系统 | SKILL 名称不一致 | 2026-07-25 | 修正 3 处 -v2 后缀错误 |
| DD-017 | 4-MEMORY | 记忆系统接口契约文档缺口 | 2026-07-31 | 编写 MEMORY_INTERFACE_SPEC.md v1.0，统一 7+2 接口契约 + 质量分级耦合 + 被动更新机制 + 合规检查清单 |
| DD-018 | 4-MEMORY/9-工具与接口 | 认知系统无独立 TECHNICAL_DESIGN | 2026-07-31 | 编写 docs/TECHNICAL_DESIGN.md v1.0，覆盖四组件架构 + 闭环数据流 + 核心算法 + 已知问题诊断 |
| DD-019 | 全局 | 双 v3.0 架构文档权威冲突 | 2026-07-31 | 根 TECHNICAL_DESIGN.md 降级为 LEGACY 归档，SSoT 层级表消除冲突，ENGINEERING_INDEX 升级 v3.0 |
| DD-020 | 13-通用风控模块 | TECHNICAL_DESIGN 缺版本头 | 2026-07-31 | 补齐 v1.0 版本头（符合 DOC_STANDARD §4.1） |
| DD-021 | 全局 | 17 号导航信息失真 + 链接错误 | 2026-07-31 | INDEX/SYSTEM_MAP/ARCHITECTURE_MAP 刷新 17 号为已建立，修复 ARCHITECTURE_MAP 链接格式错误 + INDEX 不存在文件引用 |
| DD-006 | 10-经典指标系统 | 历史技术文档冗余 | 2026-07-31 | 技术文档.md（12414行）归档到 docs/archive/技术文档_历史.md（技术文档2.0.md 此前迁移时已删） |
| DD-007 | 多子系统 | 根目录散落 .md 文件 | 2026-07-31 | 10 号根目录 8 个散落 .md 迁入 docs/（5 个辅助文档）和 docs/archive/（3 个历史文档），根目录已无散落 .md |
| DD-008 | L3 辅助模块 | 5 个模块无完整文档 | 2026-07-31 | 创建 L3_MODULE_DOC_PLAN.md 规划分级策略；15-监控告警补建 ENGINEERING_INDEX + TECHNICAL_DESIGN；7-产物中台补建 TECHNICAL_DESIGN；3-EVOLUTION + 6-图结构各创建 README 标注实验状态 |
| DD-009 | 全局 | 1-ARCHITECTURE/工作索引 过时 | 2026-07-31 | 工作索引 README.md 标注 SKILL_INDEX 和 TOOL_MAPPING 为过时，指向 SSoT v3.0 节点体系 |
| DD-025 | 10-经典指标系统 | README 缺失（L2 强制文档） | 2026-08-02 | 新建 README v1.0，L2 覆盖率 97%→100%，消除 INDEX/SYSTEM_MAP 2 处断链 |
| DD-026 | 0-系统文档管理 | 4-工具与自动化未建设 | 2026-08-02 | 建成 doc_lint/doc_coverage/index_generator/link_checker 4 脚本 + README，全部验证通过 |
| DD-027 | 0-系统文档管理 | 审计机制未落地 | 2026-08-02 | 新建 AUDIT_REPORT_TEMPLATE + 首份 2026-08 月度审计报告 |
| DD-028 | 0-系统文档管理 | DOC_DEBT_INDEX 链接多一层 ../ | 2026-08-02 | `../../../` → `../../`，修 2 处断链 |
| DD-029 | 0-系统文档管理 | link_checker 误报内联代码 | 2026-08-02 | 增 INLINE_CODE_RE 剥离 `` `...` `` span |
| DD-023 | L3 辅助模块 | L3_MODULE_DOC_PLAN 现状过时 | 2026-08-02 | 现状表刷新：3/6 号 README 已存在 v0.2 |
| DD-008a | 15-监控告警系统 | 缺 ENGINEERING_INDEX+TECHNICAL_DESIGN | 2026-08-02 | 补建 2 文档，138 函数/38 配置项从代码提取 |
| DD-008b | 7-产物中台 | 缺 TECHNICAL_DESIGN | 2026-08-02 | 补建文档，58 接口，修正原文档 5 处与代码不一致 |

---

## 3. 统计概览

| 优先级 | 待修复 | 已关闭 | 合计 |
|--------|--------|--------|------|
| P1 | 0 | 8 | 8 |
| P2 | 2 | 9 | 11 |
| P3 | 2 | 10 | 12 |
| **合计** | **4** | **27** | **31** |

**文档债务率**: 4/31 = 13%（待修复占总债务的 13%，较上期 17% 下降）

> 注：DD-008 为父级跟踪项（进行中），其已完成的子项以 DD-008a/008b 计入已关闭；DD-024 为 L0 豁免项，DD-006/007 为持续维护项。

---

## 4. 偿还路线图

| 阶段 | 任务 | 关联 ID | 预计工时 |
|------|------|---------|----------|
| Phase 2 启动前 | 修复 10-经典指标技术文档位置 | DD-001 | ✅ 已完成 |
| Phase 2 启动前 | 修复 16-调控系统 TECHNICAL_DESIGN 范围 | DD-004 | ✅ 已完成 |
| Phase 2 启动前 | 编写记忆系统接口契约统一 SPEC | DD-017 | ✅ 已完成 |
| Phase 2 启动前 | 编写认知系统 TECHNICAL_DESIGN | DD-018 | ✅ 已完成 |
| Phase 2 中 | 重构 1-ARCHITECTURE/README | DD-002 | ✅ 已完成 |
| Phase 2 中 | 整合散落架构文档 | DD-003 | ✅ 已完成 |
| Phase 2 中 | 消除双 v3.0 架构权威冲突 | DD-019 | ✅ 已完成 |
| Phase 2 中 | 补齐 13 号 TECHNICAL_DESIGN 版本头 | DD-020 | ✅ 已完成 |
| Phase 2 中 | 刷新 17 号导航 + 修复链接错误 | DD-021 | ✅ 已完成 |
| Phase 2 中 | 清理 12 号根目录重复索引 | DD-010 | ✅ 已完成 |
| Phase 3 | L3 辅助模块文档规划 | DD-008 | 16h |
| 持续 | 清理冗余历史文档 | DD-006, DD-007 | 4h |

---

**文档版本**: v2.0
**最后更新**: 2026-07-31
