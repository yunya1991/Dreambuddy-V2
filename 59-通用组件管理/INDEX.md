# 59-通用组件管理 — 模块索引

> **版本**: v1.0 | **更新日期**: 2026-11-20
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

**目录结构**（v1.0 起，P4 完成）：`contracts/`（唯一契约层）、`kernel/`（共享内核，构建期注入）、`components/`（一目录一商品族）、`products/`（分发表，驱动 `build_product.py`）、`platform/`（内部工程）、`tools/`（闸门与构建）、`docs/`（模块级文档）、`assets/`、`dist/`（构建产物）。

---

## 2. 文档清单

| 文档 | 版本 | 职责 | 状态 |
|---|---|---|---|
| [docs/SPEC-通用组件管理-架构重构-v0.1.md](./docs/SPEC-通用组件管理-架构重构-v0.1.md) | v0.6 | **模块级**：目录重构、契约层、共享内核、一份源码构建生成、独立性闸门、分阶段验收 | ✅ P0–P5 完成 |
| [docs/PLAN-20261120-SkillHub评测优化与沙箱测试-v0.1.md](./docs/PLAN-20261120-SkillHub评测优化与沙箱测试-v0.1.md) | v0.1 | 三个已上线 Skill 的 TRACE 评测问题清单、优化动作（P0/P1）、`platform/sandbox/` 本地测试环境方案（16 场景） | 🟡 待确认，未改代码 |
| [components/cogsteward/docs/ENGINEERING_INDEX.md](./components/cogsteward/docs/ENGINEERING_INDEX.md) | v1.4 | 认知管家工程索引：文件级清单、流程锚点、测试体系与 M1/M2/M2b/M3/契约治理验收证据 | ✅ 0.7.0 |
| [components/cogsteward/docs/TECHNICAL_DESIGN.md](./components/cogsteward/docs/TECHNICAL_DESIGN.md) | v1.4 | 技术设计：分层架构、扫描/路由/准入/回滚/打包/分拣/评估/索引/技能检查算法、数据流、V9 异常、契约治理与 SPEC 偏差 | ✅ 0.7.0 |
| [components/cogsteward/docs/API_SPEC.md](./components/cogsteward/docs/API_SPEC.md) | v1.4 | CLI 契约：12 个命令 + 2 个独立脚本、JSON 字段、退出码、幂等与并发 | ✅ 0.7.0 |
| [components/cogsteward/docs/CHANGELOG.md](./components/cogsteward/docs/CHANGELOG.md) | v1.4 | 变更日志：M1 骨架 + M2 路由与回滚 + M2b 打包/分拣/评估 + M3 索引/技能检查 + 0.7.0 契约单一源 | ✅ 0.7.0 |
| [components/cogsteward/docs/CHANGELOG-skill.md](./components/cogsteward/docs/CHANGELOG-skill.md) | — | 技能包内维护的 0.5.x–0.6.x 变更记录（与 docs/CHANGELOG 互补，未合并） | 🗄 归档 |
| [components/cogsteward/specs/SPEC-认知管家-WorkBuddy技能封装-v0.5.md](./components/cogsteward/specs/SPEC-认知管家-WorkBuddy技能封装-v0.5.md) | v0.5 | **当前版本（M0 已关闭）**：平台结构对齐、本地安装锁定、Office 简化、沙箱降级、访谈转 M1 | ✅ M0 关闭 |
| [components/cogsteward/specs/SPEC-认知管家-WorkBuddy技能封装-v0.4.md](./components/cogsteward/specs/SPEC-认知管家-WorkBuddy技能封装-v0.4.md) | v0.4 | 历史版本：confidence 联调 / 默认 plan / V13 校准 / 回滚清单（已被 v0.5 取代） | 🗄 归档 |
| [components/cogsteward/specs/SPIKE-20261119-平台沙箱与技能结构.md](./components/cogsteward/specs/SPIKE-20261119-平台沙箱与技能结构.md) | v1.0 | 沙箱与技能结构取证：本地安装可行、云端执行不可行；5 项强制修正 | ✅ 结论明确 |
| [components/cogsteward/specs/PRETEST-20261119-三工作区定性前测.md](./components/cogsteward/specs/PRETEST-20261119-三工作区定性前测.md) | v1.0 | 桌面前测：Dev 多归属 72% / Office 20%；Office 应简化模型；真实访谈待 M1 | 🟡 桌面完成 |
| [components/cogsteward/specs/SPEC-认知管家-WorkBuddy技能封装-v0.3.md](./components/cogsteward/specs/SPEC-认知管家-WorkBuddy技能封装-v0.3.md) | v0.3 | 历史版本：executions / apply_mode / 公式 / 指纹规范（已被 v0.5 取代） | 🗄 归档 |
| [components/cogsteward/specs/SPEC-认知管家-WorkBuddy技能封装-v0.2.md](./components/cogsteward/specs/SPEC-认知管家-WorkBuddy技能封装-v0.2.md) | v0.2 | 历史版本：主载体+从属引用、双版本、可复核验收（已被 v0.4 取代） | 🗄 归档 |
| [components/cogsteward/specs/REVIEW-20261119-SPEC-认知管家-v0.1.md](./components/cogsteward/specs/REVIEW-20261119-SPEC-认知管家-v0.1.md) | v1.0 | 一审：Major 8 / Minor 8，决议「修改后接受」；§5 路由与 §12 验收为阻断项 | ✅ 已出报告 |
| [components/cogsteward/specs/REVIEW-20261119-SPEC-认知管家-v0.2-复审.md](./components/cogsteward/specs/REVIEW-20261119-SPEC-认知管家-v0.2-复审.md) | v1.0 | 二审：上轮关闭 5 / 部分 2 / 未关闭 1；新增 Major 6 / Minor 15，P0 为 R1 自动写入无回滚、R2 runs 循环依赖、R3 confidence 无算法 | ✅ 已出报告 |
| [components/cogsteward/specs/REVIEW-20261119-SPEC-认知管家-v0.3-三审.md](./components/cogsteward/specs/REVIEW-20261119-SPEC-认知管家-v0.3-三审.md) | v1.0 | 三审：R1–R6 全关闭、N1–N15 全处理；新增 Major 3（confidence 联调 / 默认 apply 与 V12 冲突 / 缺校准验收）、Minor 10；距 M0 关闭仅差 3 项 | ✅ 已出报告 |
| [components/cogsteward/specs/REVIEW-20261119-商品叠加认知管家评估.md](./components/cogsteward/specs/REVIEW-20261119-商品叠加认知管家评估.md) | v1.0 | 商品叠加评估：免费版 / Pro / 按次版的能力边界与复用结论 | ✅ 已出报告 |
| [contracts/](./contracts/) | v1.0 | **契约层（唯一源）**：组件元数据与输出外壳 schema、九项指标口径、数据源授权台账、全局红线、禁用引用黑名单 | ✅ P1 完成 |
| [tools/](./tools/) | v1.0 | **闸门与构建**：`check_boundaries.py`（G1–G7）、`gen_index.py`（INDEX 生成）、`build_product.py`（分发构建） | ✅ P1 完成 |
| [platform/site/](./platform/site/README.md) | v1.0 | **对外站点**：产品介绍、免费体检（每日额度 + 402 付费）、使用说明、只读管理后台；静态页 + 复用 `skillhub-audit-api`，nginx 8081 | ✅ 2026-11-20 |

---

## 3. 组件登记（生成式）

> 本表由 `tools/gen_index.py` 从 `components/*/component.yaml` 生成；发版前跑 `python3 tools/gen_index.py --check`，禁止手工修改生成块内内容。
> 新建组件时先在 `components/<name>/component.yaml` 声明，再执行 `python3 tools/gen_index.py --write`。

<!-- GEN:COMPONENT-REGISTRY:BEGIN -->
| 组件 | 目录 | 版本 | 生命周期 | 分发变体 | 入口 |
|---|---|---|---|---|---|
| 认知管家 CogSteward `cogsteward` | components/cogsteward/ | v0.7.0 | active | — | 3 个 |
| 事件上下文（官方源·五层装配） `event-context` | components/event-context/ | v1.0.0 | active | — | 3 个 |
| 数据服务（宏观·披露·链上·上下文） `market-data` | components/market-data/ | v1.0.1 | active | — | 6 个 |
| 市场事实日报 `market-facts-daily` | components/market-facts-daily/ | v1.0.2 | active | — | 1 个 |
<!-- GEN:COMPONENT-REGISTRY:END -->

---

## 3.1 商品与发版状态（手工维护）

> 生成块只记录组件元数据；对外商品 ID、审核状态、价格与渠道在此维护。

| 组件 | 分发形态 | 版本 | 状态 |
|---|---|---|---|
| 认知管家 CogSteward | WorkBuddy Skill（本地安装，`components/cogsteward/skill/`） | v0.7.0 | 🟢 `init/scan/doctor/route/pack/triage/mark-done/rollback/config/index/map/skill lint/selfcheck` 与 `eval_golden`、`release_check` 已实现；九项指标由 `references/metrics-contract.json` 单一源驱动，`python3 -m unittest discover -s tests` 全部通过（2 项跳过）；真实黄金集待人工标注 |
| 认知管家 Pro `cogsteward-pro` | SkillPay 订阅制商品（¥2.99/月，`components/cogsteward/variants/pro/`） | v1.1.1 | 🟡 契约驱动 + `coverage` 透明；v1 销售中，`P0806000213876724` |
| 认知管家 Pro 按次版 `cogsteward-pro-pay` | SkillHub Pay Skill（¥0.99/次，`components/cogsteward/variants/pro-pay/`） | v1.1.1 | 🟡 口径对齐免费版 0.7.0（九项 + 契约），评测整改完成待发版 |
| 市场数据服务 `market-data-hub` | SkillPay 订阅制商品（¥19.9/月，试用 5 次，`components/market-data/skill/`） | v1.0.1 | 🟡 审核中 `P0806000213882316`（旧 P0806000213878528 已归档）；cloud 通道不支持 context |
| 事件上下文服务 `event-context` | SkillPay 订阅制商品（¥19.9/月，试用 5 次，`components/event-context/skill/`） | v1.0.0 | 🟡 审核中 `P0806000213878529` |
| 市场事实日报 `market-facts-daily` | SkillPay 买断制商品（¥0.99，`components/market-facts-daily/skill/`） | v1.0.2 | 🟢 v2 销售中；v3（补免责声明）审核中；`--json` 尚未携带 `data.v1` 外壳（见 SPEC §9 P2 备注） |
| 数据服务专业版 `market-data-pro` | SkillHub Pay Skill（¥2.99/次，`components/market-data/variants/pro/`） | v1.0.3 | 🟢 已发布（评测 4.4）；1.0.3 评测整改完成待发版 |
| 事件上下文专业版 `event-context-pro` | SkillHub Pay Skill（¥2.99/次，`components/event-context/variants/pro/`） | v1.0.1 | 🟢 已发布（评测 4.5）；1.0.1 评测整改完成待发版 |

---

## 3.2 平台工程（非组件，不占 §3 登记位）

> 服务于本模块自身的发布、计费与运维，无外部分发形态；不计入组件依赖图、不参与 golden 输出校验（决策 DC-2，见 [SPEC-通用组件管理-架构重构-v0.1.md §11](./docs/SPEC-通用组件管理-架构重构-v0.1.md)）。

| 单元 | 路径 | 版本 | 职责 |
|---|---|---|---|
| SkillHub 体检收费后端 `skillhub-audit-api` | `platform/services/skillhub-audit-api/` | v1.2.0 | 402 付费后端：契约驱动九项体检，已部署 49.233.123.96 |
| 巡检 `patrol` | `platform/ops/patrol/` | — | 定时巡检与事故记录 |
| 沙箱测试 `sandbox` | `platform/sandbox/` | v0.1 | 复刻 402 付费协议的本地回归：16 场景、mock 服务、fixtures、基线报告（不改 Skill） |
| 发布交互 `skillhub-publisher` | `platform/tools-skills/skillhub-publisher/` | v1.1.0 | SkillHub 免费/付费发布协议 |
| SkillPay 工作流 `skillpay-workflow` | `platform/tools-skills/skillpay-workflow/` | v1.1.0 | 支付宝 / SkillHub / 402 三链路脚本入口 |
| 技能运营台 `skill-ops` | `platform/tools-skills/skill-ops/` | v1.1.0 | 每日运营闭环与竞品基线 |

---

## 4. 维护规则

1. 新增组件 → 先建 `components/<name>/component.yaml` 并跑 `python3 tools/gen_index.py --write`，再建目录与 SPEC
2. 组件升级 → 更新版本号（`component.yaml` 与 `skill/SKILL.md` 必须一致）+ CHANGELOG + §3.1 状态
3. 组件对外分发 → 必须通过「不依赖内部私有路径/数据」检查
4. 本模块 INDEX 变更 → 同步更新 [0-系统文档管理/INDEX.md](../0-系统文档管理/INDEX.md)
5. 任何 Skill 发新版本 → 按 `platform/tools-skills/skillpay-workflow/SKILL.md` §8 检查单执行，并在 §3.1 更新版本号
6. 内部工具与服务 → 登记 §3.2 平台工程，不进入组件依赖图与 golden 校验
7. 任何组件发版前 → 必须跑 `make check`（`sync_kernel --check` + G1–G7 + `gen_index --check`），全绿才允许 `make build` 打包
