# 59-通用组件管理 — 模块索引

> **版本**: v0.9 | **更新日期**: 2026-11-20
> **定位**: 通用能力组件的统一管理与升级层：把可复用能力从业务模块中抽出来，统一登记、版本化、打包与分发
> **上级索引**: [0-系统文档管理/INDEX.md](../0-系统文档管理/INDEX.md)

---

## 1. 模块职责

| 职责 | 说明 |
|---|---|
| 组件登记 | 维护通用组件清单：名称、来源模块、版本、依赖、适用场景 |
| 版本与升级 | 组件版本语义、变更记录、废弃策略，避免各业务模块各自复制 |
| 打包与分发 | 将组件封装为可分发的 Skill / CLI / 包结构（含对外商品形态） |
| 边界治理 | 约束组件不得反向依赖交易域私有 schema、绝对路径与内部数据 |

**不负责**：具体业务逻辑实现、交易策略、数据采集。组件的实现仍在各自源模块，本模块只管「如何抽出、如何升级、如何分发」。

---

## 2. 文档清单

| 文档 | 版本 | 职责 | 状态 |
|---|---|---|---|
| [SPEC-通用组件管理-架构重构-v0.1.md](./SPEC-通用组件管理-架构重构-v0.1.md) | v0.2 | **模块级**：目录重构、契约层、共享内核、一份源码构建生成、独立性闸门、分阶段验收 | ✅ 已确认，P0–P1 完成 |
| [PLAN-20261120-SkillHub评测优化与沙箱测试-v0.1.md](./PLAN-20261120-SkillHub评测优化与沙箱测试-v0.1.md) | v0.1 | 三个已上线 Skill 的 TRACE 评测问题清单、优化动作（P0/P1）、`sandbox/` 本地测试环境方案（15 场景） | 🟡 待确认，未改代码 |
| [docs/ENGINEERING_INDEX.md](./docs/ENGINEERING_INDEX.md) | v1.4 | 认知管家工程索引：文件级清单、流程锚点、测试体系与 M1/M2/M2b/M3/契约治理验收证据 | ✅ 0.7.0 |
| [docs/TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) | v1.4 | 技术设计：分层架构、扫描/路由/准入/回滚/打包/分拣/评估/索引/技能检查算法、数据流、V9 异常、契约治理与 SPEC 偏差 | ✅ 0.7.0 |
| [docs/API_SPEC.md](./docs/API_SPEC.md) | v1.4 | CLI 契约：12 个命令 + 2 个独立脚本、JSON 字段、退出码、幂等与并发 | ✅ 0.7.0 |
| [docs/CHANGELOG.md](./docs/CHANGELOG.md) | v1.4 | 变更日志：M1 骨架 + M2 路由与回滚 + M2b 打包/分拣/评估 + M3 索引/技能检查 + 0.7.0 契约单一源 | ✅ 0.7.0 |
| [SPEC-认知管家-WorkBuddy技能封装-v0.5.md](./SPEC-认知管家-WorkBuddy技能封装-v0.5.md) | v0.5 | **当前版本（M0 已关闭）**：平台结构对齐、本地安装锁定、Office 简化、沙箱降级、访谈转 M1 | ✅ M0 关闭 |
| [SPEC-认知管家-WorkBuddy技能封装-v0.4.md](./SPEC-认知管家-WorkBuddy技能封装-v0.4.md) | v0.4 | 历史版本：confidence 联调 / 默认 plan / V13 校准 / 回滚清单（已被 v0.5 取代） | 🗄 归档 |
| [SPIKE-20261119-平台沙箱与技能结构.md](./SPIKE-20261119-平台沙箱与技能结构.md) | v1.0 | 沙箱与技能结构取证：本地安装可行、云端执行不可行；5 项强制修正 | ✅ 结论明确 |
| [PRETEST-20261119-三工作区定性前测.md](./PRETEST-20261119-三工作区定性前测.md) | v1.0 | 桌面前测：Dev 多归属 72% / Office 20%；Office 应简化模型；真实访谈待 M1 | 🟡 桌面完成 |
| [SPEC-认知管家-WorkBuddy技能封装-v0.3.md](./SPEC-认知管家-WorkBuddy技能封装-v0.3.md) | v0.3 | 历史版本：executions / apply_mode / 公式 / 指纹规范（已被 v0.5 取代） | 🗄 归档 |
| [SPEC-认知管家-WorkBuddy技能封装-v0.2.md](./SPEC-认知管家-WorkBuddy技能封装-v0.2.md) | v0.2 | 历史版本：主载体+从属引用、双版本、可复核验收（已被 v0.4 取代） | 🗄 归档 |
| [REVIEW-20261119-SPEC-认知管家-v0.1.md](./REVIEW-20261119-SPEC-认知管家-v0.1.md) | v1.0 | 一审：Major 8 / Minor 8，决议「修改后接受」；§5 路由与 §12 验收为阻断项 | ✅ 已出报告 |
| [REVIEW-20261119-SPEC-认知管家-v0.2-复审.md](./REVIEW-20261119-SPEC-认知管家-v0.2-复审.md) | v1.0 | 二审：上轮关闭 5 / 部分 2 / 未关闭 1；新增 Major 6 / Minor 15，P0 为 R1 自动写入无回滚、R2 runs 循环依赖、R3 confidence 无算法 | ✅ 已出报告 |
| [REVIEW-20261119-SPEC-认知管家-v0.3-三审.md](./REVIEW-20261119-SPEC-认知管家-v0.3-三审.md) | v1.0 | 三审：R1–R6 全关闭、N1–N15 全处理；新增 Major 3（confidence 联调 / 默认 apply 与 V12 冲突 / 缺校准验收）、Minor 10；距 M0 关闭仅差 3 项 | ✅ 已出报告 |
| [contracts/](./contracts/) | v1.0 | **契约层（唯一源）**：组件元数据与输出外壳 schema、九项指标口径、数据源授权台账、全局红线、禁用引用黑名单 | ✅ P1 完成 |
| [tools/](./tools/) | v1.0 | **闸门与构建**：`check_boundaries.py`（G1–G7）、`gen_index.py`（INDEX 生成）、`build_product.py`（分发构建） | ✅ P1 完成 |

---

## 3. 组件登记

> 后续新增通用组件时在此登记，一行一个组件，禁止只建目录不登记。

| 组件 | 源模块 | 分发形态 | 版本 | 状态 |
|---|---|---|---|---|
| 认知管家 CogSteward | 本模块（规则提炼自 35 / 4-MEMORY / 41 / 0-系统文档管理） | WorkBuddy Skill（本地安装） | v0.7.0 | 🟢 `init/scan/doctor/route/pack/triage/mark-done/rollback/config/index/map/skill lint/selfcheck` 与 `eval_golden`、`release_check` 已实现；九项指标由 `references/metrics-contract.json` 单一源驱动，85 项自检通过（2 项跳过）；真实黄金集待人工标注 |
| 认知管家 Pro `cogsteward-pro` | 本模块 `skills/cogsteward-pro` | SkillPay 订阅制商品（¥2.99/月） | v1.1.1 | 🟡 契约驱动 + `coverage` 透明；v1 销售中，`P0806000213876724` |
| 认知管家 Pro 按次版 `cogsteward-pro-pay` | 本模块 `skills/cogsteward-pro-pay` | SkillHub Pay Skill（¥0.99/次） | v1.1.1 | 🟡 口径对齐免费版 0.7.0（九项 + 契约），评测整改完成待发版 |
| 市场数据服务 `market-data-hub` | 本模块 `skills/market-data-hub` | SkillPay 订阅制商品（¥19.9/月，试用 5 次） | v1.0.1 | 🟡 审核中 `P0806000213882316`（旧 P0806000213878528 已归档）；cloud 通道不支持 context |
| 事件上下文服务 `event-context` | 本模块 `skills/event-context` | SkillPay 订阅制商品（¥19.9/月，试用 5 次） | v1.0.0 | 🟡 审核中 `P0806000213878529` |
| 市场事实日报 `market-facts-daily` | 本模块 `skills/market-facts-daily` | SkillPay 买断制商品（¥0.99） | v1.0.2 | 🟢 v2 销售中；v3（补免责声明）审核中 |
| 数据服务专业版 `market-data-pro` | 本模块 `skills/market-data-pro` | SkillHub Pay Skill（¥2.99/次） | v1.0.3 | 🟢 已发布（评测 4.4）；1.0.3 评测整改完成待发版 |
| 事件上下文专业版 `event-context-pro` | 本模块 `skills/event-context-pro` | SkillHub Pay Skill（¥2.99/次） | v1.0.1 | 🟢 已发布（评测 4.5）；1.0.1 评测整改完成待发版 |

> 本表将在 SPEC-架构重构 P5 阶段由 `component.yaml` + `tools/gen_index.py` 生成，届时不再手工维护。平台工具与内部服务见 §3.2，不占组件登记位（DC-2）。

---

## 3.1 完整 Skill 清单

> 目录即登记单位。新增/删除 Skill 必须同步本表，否则视为未登记。

| 目录 | name | displayName | 版本 | 分发形态 | 对外标识 |
|---|---|---|---|---|---|
| `cognition-manager/` | `cognition-manager` | 认知管家 | 0.7.0 | WorkBuddy Skill（本地安装） | SkillHub 免费 Skill `cogsteward` |
| `cogsteward-pro/` | `cogsteward-pro` | 认知管家 Pro | 1.1.1 | SkillPay 订阅制 ¥2.99/月 | `P0806000213876724` |
| `skills/cogsteward-pro-pay/` | `cogsteward-pro` | 认知管家 Pro（按次付费） | 1.1.1 | SkillHub Pay Skill ¥0.99/次 | 待发版（评测整改完成） |
| `skills/market-data-pro/` | `market-data-pro` | 数据服务专业版（按次付费） | 1.0.3 | SkillHub Pay Skill ¥2.99/次 | 已发布，待发 1.0.3 |
| `skills/event-context-pro/` | `event-context-pro` | 事件上下文专业版（按次付费） | 1.0.1 | SkillHub Pay Skill ¥2.99/次 | 已发布，待发 1.0.1 |
| `skills/market-data-hub/` | `market-data-hub` | 数据服务（宏观·披露·链上·上下文） | 1.0.1 | SkillPay 订阅制 | `P0806000213882316` |
| `skills/event-context/` | `event-context` | 事件上下文（官方源·五层装配） | 1.0.0 | SkillPay 订阅制 | `P0806000213878529` |
| `skills/market-facts-daily/` | `market-facts-daily` | 市场事实日报 | 1.0.2 | SkillPay 买断制 | `P0806000213874311` |
| `skills/skillpay-workflow/` | `skillpay-workflow` | SkillPay 工作流 | 1.1.0 | 平台工具（内部，不对外分发） | — |
| `skills/skillhub-publisher/` | `skillhub-publisher` | SkillHub 发布交互 | 1.1.0 | 平台工具（内部，不对外分发） | — |
| `skills/skill-ops/` | `skill-ops` | 技能运营台 | 1.1.0 | 平台工具（内部，不对外分发） | — |

**发版检查单**：任何 Skill 发新版本，按 `skills/skillpay-workflow/SKILL.md` §8.2 执行，重点核对 §8.3 的四个坑（版本说明非空 / 商品名改回中文 / 取消黑客松报名 / 版本页快照超时换新标签页）。

---

## 3.2 平台工程（非组件，不占 §3 登记位）

> 服务于本模块自身的发布、计费与运维，无外部分发形态；不计入组件依赖图、不参与 golden 输出校验（决策 DC-2，见 [SPEC-通用组件管理-架构重构-v0.1.md §11](./SPEC-通用组件管理-架构重构-v0.1.md)）。

| 单元 | 现状路径 | 目标路径（P2） | 版本 | 职责 |
|---|---|---|---|---|
| SkillHub 体检收费后端 `skillhub-audit-api` | `services/skillhub-audit-api/` | `platform/services/skillhub-audit-api/` | v1.2.0 | 402 付费后端：契约驱动九项体检，已部署 49.233.123.96 |
| 巡检 `patrol` | `ops/patrol/` | `platform/ops/patrol/` | — | 定时巡检与事故记录 |
| 沙箱测试 `sandbox` | `sandbox/` | `platform/sandbox/` | v0.1 | 复刻 402 付费协议的本地回归：16 场景、mock 服务、fixtures、基线报告（不改 Skill） |
| 发布交互 `skillhub-publisher` | `skills/skillhub-publisher/` | `platform/tools-skills/skillhub-publisher/` | v1.1.0 | SkillHub 免费/付费发布协议 |
| SkillPay 工作流 `skillpay-workflow` | `skills/skillpay-workflow/` | `platform/tools-skills/skillpay-workflow/` | v1.1.0 | 支付宝 / SkillHub / 402 三链路脚本入口 |
| 技能运营台 `skill-ops` | `skills/skill-ops/` | `platform/tools-skills/skill-ops/` | v1.1.0 | 每日运营闭环与竞品基线 |

---

## 4. 维护规则

1. 新增组件 → 先在 §3 登记，再建目录与 SPEC
2. 组件升级 → 更新版本号 + CHANGELOG + 本表状态
3. 组件对外分发 → 必须通过「不依赖内部私有路径/数据」检查
4. 本模块 INDEX 变更 → 同步更新 [0-系统文档管理/INDEX.md](../0-系统文档管理/INDEX.md)
5. 任何 Skill 发新版本 → 按 `skills/skillpay-workflow/SKILL.md` §8 检查单执行，并在 §3.1 更新版本号
6. 内部工具与服务 → 登记 §3.2 平台工程，不进入组件依赖图与 golden 校验
7. 任何组件发版前 → 必须跑 `python3 tools/check_boundaries.py`（G1–G7）与 `python3 tools/gen_index.py --check`，全绿才允许打包
