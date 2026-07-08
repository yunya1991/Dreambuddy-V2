# 工程索引 · 技术目录

> **本文档是 Dream-MultiSkill 系统所有核心文件和模块的技术索引**
> 
> **维护规则**: 新增/删除/移动文件后，必须同步更新本文档
> 
> **宪法依据**: 宪法§0.1 核心文件定位 — 工程索引用于快速定位相关文件和入口

---

## 文档信息

| 项目 | 内容 |
|------|------|
| 文件位置 | `~/.workbuddy/skills/dream-governance-manager/governance_docs/engineering_index.md` |
| 版本 | v1.0 |
| 创建日期 | 2026-05-01 |
| 最后更新 | 2026-05-01 |
| 维护者 | 治理管理部（COO） |

---

## 一、宪法与治理文件

| 文件路径 | 模块/功能 | 说明 | 最后更新 |
|----------|------------|------|----------|
| `~/.workbuddy/skills/dream-constitution/SKILL.md` | 宪法（完整版） | 系统最高指导文件，唯物主义版 | 2026-04-26 |
| `~/.workbuddy/skills/dream-governance-manager/governance_docs/constitution.md` | 宪法索引 | 宪法章节索引（本文档） | 2026-05-01 |
| `~/.workbuddy/skills/dream-governance-manager/governance_docs/workflows_and_standards.md` | 工作流程与规范 | 操作标准、流程规范 | 2026-05-01 |
| `~/.workbuddy/skills/dream-governance-manager/governance_docs/faq.md` | 治理 FAQ | 治理专属常见问题 | 2026-05-01 |
| `~/.workbuddy/skills/dream-governance-manager/governance_docs/org_structure.md` | 公司组织与架构 | 部门职责、组织架构 | 2026-05-01 |
| `~/.workbuddy/skills/dream-governance-manager/SKILL.md` | 治理管理部 SKILL | 72h 健康检查、违规检测 | 2026-04-29 |
| `~/.workbuddy/skills/hermes-skill-governance/SKILL.md` | Hermes 技能治理 | 平台层技能治理门 | - |

---

## 二、交易主链路（A1-A5）

| 文件路径 | 模块/功能 | 说明 | 版本 |
|----------|------------|------|-------|
| `~/.workbuddy/skills/dream-intelligence-monitor/SKILL.md` | A6 情报监控部 | 永不间断的市场雷达，触发 A1-A5 | v4.9 |
| `~/.workbuddy/skills/dream-strategy-research/SKILL.md` | A1 深度调研 | 战略制定前的侦察兵 | - |
| `~/.workbuddy/skills/dream-first-principles/SKILL.md` | A2 第一性原理分析 | 战略制定的哲学根基 | - |
| `~/.workbuddy/skills/dream-contradiction-theory/SKILL.md` | A0 矛盾分析理论 | A1/A2/A3 统一矛盾操作系统 | - |
| `~/.workbuddy/skills/dream-strategy-designer/SKILL.md` | A3 战略制定 | 交易决策的最高指引 | v2.3 |
| `~/.workbuddy/skills/dream-tactical-validator/SKILL.md` | A4 战术验证 | 多情景验证方案设计师 | v7.0 |
| `~/.workbuddy/skills/dream-tactical-executor/SKILL.md` | A5 战术执行 | 综合判断决策执行 | v3.5 |
| `~/.workbuddy/skills/dream-pretrade-gatekeeper/SKILL.md` | 交易前门禁 | 统一执行交易前门禁 | - |
| `~/.workbuddy/skills/dream-execution-cost-model/SKILL.md` | 执行成本模型 | 下单前评估手续费/滑点 | - |
| `~/.workbuddy/skills/dream-risk-position-sizing/SKILL.md` | 风险仓位管理 | 基于风险预算的仓位映射 | - |

---

## 三、顾问与评审系统

| 文件路径 | 模块/功能 | 说明 | 备注 |
|----------|------------|------|------|
| `~/.workbuddy/skills/A7-practice-theory/SKILL.md` | A7 实践论 | 基于《实践论》的交易实践指导 | 内嵌 SKILL |
| `~/.workbuddy/skills/A8-theory-practice-verification/SKILL.md` | A8 理论实践验证 | 理论与实践结合验证、自我批评 | 内嵌 SKILL |
| `~/.workbuddy/skills/master-seminar/SKILL.md` | 大师研讨 | 让蒸馏交易大师分阵营辩论 | - |
| `~/.workbuddy/skills/dream-output-quality-gate/SKILL.md` | 输出质量门 | AI 输出质检、PATCH/REWRITE | - |

> **注**: 顾问已内嵌各 SKILL 直接调用（2026-04-26 废弃顾问邮箱），不在治理文档中单独归类。

---

## 四、记忆与学习系统

| 文件路径 | 模块/功能 | 说明 | 关键函数/类 |
|----------|------------|------|----------------|
| `~/.workbuddy/skills/memory-manager/SKILL.md` | 记忆管理 | 压缩检测、自动快照、语义搜索 | - |
| `~/.workbuddy/skills/memory-distiller/SKILL.md` | 记忆蒸馏 | 定期审查 MEMORY.md，防止膨胀 | - |
| `~/.workbuddy/skills/memory-session-index/SKILL.md` | 会话索引 | episodes/dream_* 可检索索引 | - |
| `~/.workbuddy/skills/memory-budget-policy/SKILL.md` | 记忆预算 | 多层记忆配额、晋升/降级规则 | - |
| `~/.workbuddy/skills/memory-context-fencing/SKILL.md` | 上下文围栏 | 外部信息围栏注入、防污染 | - |
| `~/.workbuddy/skills/learning-episode-writer/SKILL.md` | Episode 写入 | 决策与结果固化 | - |
| `~/.workbuddy/skills/learning-lesson-distiller/SKILL.md` | 经验蒸馏 | episodes → lessons（规则/禁令） | - |
| `~/.workbuddy/skills/learning-proposal-generator/SKILL.md` | 提案生成 | lessons → 可治理变更提案 | - |
| `~/.workbuddy/skills/learning-recall-pack/SKILL.md` | 经验召回 | 从 lessons 召回相关经验 | - |
| `~/.workbuddy/skills/ontology/SKILL.md` | 本体知识图谱 | 结构化记忆、可组合技能 | - |

---

## 五、知识与档案系统

| 文件路径 | 模块/功能 | 说明 | 数据路径 |
|----------|------------|------|----------|
| `~/.workbuddy/skills/dream-knowledge/SKILL.md` | 知识库 | 策略动态知识库、评分入库 | - |
| `~/.workbuddy/skills/dream-archive-center/SKILL.md` | 档案中心 | 外部历史经验库、联网搜索 | - |
| `~/.workbuddy/skills/dream-data-analysis/SKILL.md` | 数据分析 | 趋势/阻力/归因图、校准建议 | - |
| `~/.workbuddy/skills/dream-posttrade-mrm-audit/SKILL.md` | 盘后审计 | 固化交易输入快照、episode 生成 | - |
| `.workbuddy/faq/OKX_FAQ.md` | 主 FAQ | OKX 相关踩坑经验、工程索引 | 宪法§11.4 |
| `~/.workbuddy/skills/dream-governance-manager/governance_docs/faq.md` | 治理 FAQ | 治理专属 FAQ | 本文档 §三 |

---

## 六、基础设施与运维

| 文件路径 | 模块/功能 | 说明 | 触发频率 |
|----------|------------|------|----------|
| `~/.workbuddy/skills/boss-secretary/SKILL.md` | 秘书部 | 信息收集、分级路由、汇总报告 | 每 2h |
| `~/.workbuddy/skills/auto-repair/SKILL.md` | 自动修复部 | 系统健康自动修复、提案落地 | 每 8h |
| `~/.workbuddy/skills/dream-task-creator/SKILL.md` | 任务创建 | 自动化任务创建、TOML 写入 | 按需 |
| `~/.workbuddy/skills/dream-operation-director/SKILL.md` | 运营总监 | 跨部门协调、流程优化 | 按需 |
| `~/.workbuddy/skills/dream-performance-review/SKILL.md` | 绩效考核部 | 定期评估、PIP、GitHub 监控 | 定期 |
| `~/.workbuddy/skills/dream-hr-recruitment/SKILL.md` | HR/招聘部 | 技能市场搜索、候选人评估 | 按需 |
| `~/.workbuddy/skills/dream-cost-control/SKILL.md` | CFO 成本控制 | 交易成本分析、ROI 评估 | 定期 |
| `~/.workbuddy/skills/resource-efficiency-analyst/SKILL.md` | 资源效率分析 | 系统资源使用优化 | 定期 |

---

## 七、交易大师蒸馏系统

| 文件路径 | 模块/功能 | 说明 | 状态 |
|----------|------------|------|------|
| `~/.workbuddy/skills/master-distillation-orchestrator/SKILL.md` | 蒸馏编排 | 调度交易大师蒸馏全流程 | - |
| `~/.workbuddy/skills/master-factory-orchestrator/SKILL.md` | 大师工厂编排 | 1-3 位大师统一蒸馏流水线 | - |
| `~/.workbuddy/skills/master-template-registry/SKILL.md` | 大师模板注册 | 管理大师模板输入 | - |
| `~/.workbuddy/skills/neuro-cognitive-modeler/SKILL.md` | 神经认知建模 | 大师方法 → 左脑/右脑/元认知 | - |
| `~/.workbuddy/skills/market-practice-simulator/SKILL.md` | 市场实践模拟 | 大师理论 → 市场情景推演 | - |
| `~/.workbuddy/skills/master-state-machine-governor/SKILL.md` | 状态机管理 | 多大师 5 态状态机迁移 | - |
| `~/.workbuddy/skills/master-regime-fit-scorer/SKILL.md` | Regime 适配评分 | 计算 regime_fit_score | - |
| `~/.workbuddy/skills/master-switch-policy-engine/SKILL.md` | 切换策略引擎 | 多大师切换方案生成 | - |
| `~/.workbuddy/skills/master-freeze-controller/SKILL.md` | 冻结控制器 | 大师冻结/解冻流程 | - |
| `~/.workbuddy/skills/distillation-quality-gate/SKILL.md` | 蒸馏质量门 | 审核蒸馏产物、风险边界 | - |

---

## 八、Other Skills（支持功能）

| 文件路径 | 模块/功能 | 说明 | 使用场景 |
|----------|------------|------|----------|
| `~/.workbuddy/skills/tavily/SKILL.md` | Tavily 搜索 | AI 优化网页搜索 | 调研、情报收集 |
| `~/.workbuddy/skills/agent-reach/SKILL.md` | Agent Reach | 16 平台内容搜索 | 多平台情报 |
| `~/.workbuddy/skills/api-gateway/SKILL.md` | API 网关 | 100+ API 托管 OAuth | 外部服务集成 |
| `~/.workbuddy/skills/stock-analysis/SKILL.md` | 股票分析 | Yahoo Finance 数据、评分 | 股票/加密货币分析 |
| `~/.workbuddy/skills/macro-monitor/SKILL.md` | 宏观监控 | 每日宏观数据监控推送 | 定时任务 |
| `~/.workbuddy/skills/odaily/SKILL.md` | Odaily 加密市场 | 加密资讯结构化拆解 | 加密市场分析 |
| `~/.workbuddy/skills/dream-oneirology/SKILL.md` | 做梦部 | 潜意识分析、反直觉观点 | 每日 17:00 |
| `~/.workbuddy/skills/self-improving-agent/SKILL.md` | 自我改进代理 | 自我反思、自我批评 | 错误处理 |
| `~/.workbuddy/skills/skill-creator/SKILL.md` | 技能创建器 | 创建/更新 SKILL 指南 | 新技能开发 |

---

## 九、配置文件索引

| 文件路径 | 用途 | 格式 | 说明 |
|----------|------|------|------|
| `~/.workbuddy/mcp.json` | MCP 服务器配置 | JSON | MCP 服务器连接配置 |
| `~/.workbuddy/skills/dream-exit-skill-v2/config/*.yaml` | Exit Skill 配置 | YAML | 交易退出策略配置 |
| `~/.workbuddy/automations/*.toml` | 自动化任务配置 | TOML | 定时任务配置（如 exit-skill-v2-0） |
| `.workbuddy/memory/MEMORY.md` | 长期记忆 | Markdown | 跨会话核心事实、偏好、教训 |
| `.workbuddy/memory/YYYY-MM-DD.md` | 每日记忆 | Markdown | 当日工作记录 |

---

## 十、动态更新机制

### 10.1 更新触发条件

| 触发条件 | 更新内容 | 执行者 |
|----------|----------|--------|
| 新增 SKILL 文件 | 在对应章节添加条目 | 治理管理部 |
| 删除 SKILL 文件 | 在对应章节移除条目 | 治理管理部 |
| 文件移动/重命名 | 更新文件路径 | 治理管理部 |
| 版本更新（SKILL） | 更新版本号、最后更新日期 | 治理管理部 |
| 用户/老板要求 | 按指令更新 | 治理管理部 |

### 10.2 更新检查清单

```
文件更新后检查清单：
□ 在对应章节添加了新条目？
□ 文件路径正确（绝对路径）？
□ 版本号/最后更新日期已更新？
□ 表格格式正确（Markdown 表格）？
□ 章节索引（本章节目录）已更新？
```

### 10.3 更新记录

| 版本 | 日期 | 更新内容 | 更新人 |
|------|------|----------|--------|
| v1.0 | 2026-05-01 | 初始创建，9 类文件索引 | 治理管理部 |

---

> **最后更新**: 2026-05-01
> **维护者**: 治理管理部（COO）
> **宪法依据**: 宪法§0.1 核心文件定位 — 工程索引用于快速定位相关文件和入口
> **下次审查**: 2026-05-08（每周审查）
