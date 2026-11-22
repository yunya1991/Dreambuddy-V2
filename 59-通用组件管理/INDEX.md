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
| [docs/SPEC-通用组件管理-架构重构-v0.1.md](./docs/SPEC-通用组件管理-架构重构-v0.1.md) | v0.7 | **模块级**：目录重构、契约层、共享内核、一份源码构建生成、独立性闸门、分阶段验收 | ✅ P0–P6 完成 |
| [docs/PLAN-20261120-SkillHub评测优化与沙箱测试-v0.1.md](./docs/PLAN-20261120-SkillHub评测优化与沙箱测试-v0.1.md) | v0.1 | 三个已上线 Skill 的 TRACE 评测问题清单、优化动作（P0/P1）、`platform/sandbox/` 本地测试环境方案（16 场景） | 🟡 待确认，未改代码 |
| [docs/RESEARCH-20261121-59域接入SkillHub与AI宿主-v0.1.md](./docs/RESEARCH-20261121-59域接入SkillHub与AI宿主-v0.1.md) | v0.1 | **接入调研**：现状取证（dreambuddy CLI / 组件契约 / SkillHub CLI / Trae MCP）、CLI·Skill·MCP·在线运行四层对比、一份 `component.yaml` 生成四形态的目标架构与 P0–P3；附可发现性路由基准对照实验（描述优化后覆盖命中 36.4%→100%，越界误选 0） | ✅ P0–P2 已落地；描述优化对照实验完成 |
| [docs/SPEC-20261121-SkillHub产品优化引擎-v0.1.md](./docs/SPEC-20261121-SkillHub产品优化引擎-v0.1.md) | v0.1 | **产品优化引擎**：5 维 20 规则评分卡、四类评分对象、`score/advise/ab/gate/report` CLI 契约、legacy/new 门禁策略 | ✅ P0–P2 已落地（v0.1.0） |
| [docs/RESEARCH-20261121-产品优化引擎三路调研-v0.1.md](./docs/RESEARCH-20261121-产品优化引擎三路调研-v0.1.md) | v0.1 | **三路调研**：已有实现盘点、RAG-MCP/MCP-Zero/SCOUT/Semantic Tool Discovery 与 semantic-router 对比、ASO/JTBD/落地页转化可迁移实践 | ✅ 结论已落 SPEC |
| [docs/SPEC-20261121-59域全生命周期-现状与缺口-v0.1.md](./docs/SPEC-20261121-59域全生命周期-现状与缺口-v0.1.md) | v0.2 | **全生命周期盘点（SPEC-A）**：七段完备度、17 项缺口（P0×8/P1×5/P2×4）、业务闭环现状；已对齐手机 AGENT 主仓 v0.14.0/schema 7，指出 59 mobile 副本为旧桩 | 🚧 P0 已全部落地 |
| [docs/SPEC-20261121-59域全生命周期-框架与操作流程-v0.1.md](./docs/SPEC-20261121-59域全生命周期-框架与操作流程-v0.1.md) | v0.2 | **目标框架与操作流程（SPEC-B）**：七平面架构（含 L3.5 手机执行面）、契约扩展、CLI/工作流/调度/三态审批、数据→研究→博文→手机填稿→人工发布→回流、六组件测试矩阵与 P0–P2 路线图 | ✅ P0/P1/P2/P3 已落地 |
| [docs/SPEC-20261122-跨域能力注册表-v0.1.md](./docs/SPEC-20261122-跨域能力注册表-v0.1.md) | v0.1 | **跨域能力注册表**：两域单一动作源、`dreambuddy.capabilities.v2` 合并索引与来源指纹、`escalate` 动态升权、双向子进程调度、MCP 索引优先投影；含 P0–P3 验收与决策记录 | ✅ P0–P3 已落地 |
| [docs/SPEC-20261122-59域云端出站通道-v0.1.md](./docs/SPEC-20261122-59域云端出站通道-v0.1.md) | v0.1 | **云端出站通道（P5）**：现状证据（6 动作/令牌未配置/入站非出站）、四层架构（数据面/控制面/执行面/治理）、`cloud_client` 契约与错误码、能力矩阵、P5-1~P5-4 验收与红线 | ✅ P5-1~P5-4 + P5-R 已落地（正式证书/IP 白名单待条件具备） |
| [docs/SPEC-20261120-59站点与体检产品化改造-v0.3.md](./docs/SPEC-20261120-59站点与体检产品化改造-v0.3.md) | v0.3 | **站点与体检产品化改造（当前版）**：必填项禁灰度、文案生成清单、`patches[]` 付费交付、全局额度单事务、基线门禁、S0a/S0b 拆步、规则结构校验、范围冻结到 S2 | ✅ S0a–S2 已完成并部署 49.233.123.96（外网验收通过）；HTTPS 用 Let's Encrypt IP 证书（6 天自动续期）；域名待 ICP 备案 |
| [docs/SPEC-20261120-59站点与体检产品化改造-v0.2.md](./docs/SPEC-20261120-59站点与体检产品化改造-v0.2.md) | v0.2 | 已被 v0.3 取代（保留审计痕迹） | 🗄 归档 |
| [docs/SPEC-20261120-59站点与体检产品化改造-v0.1.md](./docs/SPEC-20261120-59站点与体检产品化改造-v0.1.md) | v0.1 | 初稿（已被 v0.2 取代，保留审计痕迹） | 🗄 归档 |
| [docs/REVIEW-20261120-SPEC-59站点与体检产品化改造-v0.1.md](./docs/REVIEW-20261120-SPEC-59站点与体检产品化改造-v0.1.md) | v1.0 | 初稿评审：4 项阻断、8 项 Major、15 项 Minor；关闭核对见 SPEC v0.2 §13 | ✅ 已关闭 |
| [docs/REVIEW-20261120-SPEC-59站点与体检产品化改造-v0.2-复审.md](./docs/REVIEW-20261120-SPEC-59站点与体检产品化改造-v0.2-复审.md) | v1.0 | 复审：3 项阻断、7 项 Major、15 项 Minor；关闭核对见 SPEC v0.3 §13 | ✅ 已关闭 |
| [docs/RESEARCH-20261120-预约与抢票工具-GitHub调研-v0.1.md](./docs/RESEARCH-20261120-预约与抢票工具-GitHub调研-v0.1.md) | v0.1 | **新组件前置调研**：9 个成熟项目对比、七层能力抽象、四条技术路线、合规红线与 `reservation-assist` 落地建议 | ✅ 已落地为 reservation-assist 0.2.0 |
| [docs/SPEC-20261120-预约助手-reservation-assist-v0.2.md](./docs/SPEC-20261120-预约助手-reservation-assist-v0.2.md) | v0.2 | **新组件 SPEC（当前版）**：8 阻断全关闭；`reservation.v1` 契约、6 适配器协议、虚拟时钟、grant 门禁、launchd 模板、P0–P3 验收 | 🟡 P0/P1 已落地（0.2.0）；P2/P3 待施工 |
| [docs/SPEC-20261120-预约助手-reservation-assist-v0.1.md](./docs/SPEC-20261120-预约助手-reservation-assist-v0.1.md) | v0.1 | 历史版本：首版架构与门禁设计（已被 v0.2 取代） | 🗄 归档 |
| [docs/REVIEW-20261120-SPEC-预约助手-reservation-assist-v0.1.md](./docs/REVIEW-20261120-SPEC-预约助手-reservation-assist-v0.1.md) | v0.1 | **三视角评审报告**（架构/合规/工程）：8 阻断 + 10 重要 + 6 次要，含 SPEC v0.2 修订清单与 3 项待拍板决策 | ✅ 已出报告 |
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
| [platform/site/](./platform/site/README.md) | v1.2 | **对外站点**：产品介绍、免费体检（SQLite 额度/UTC+8/防刷）、使用说明、隐私说明、商品详情页（`catalog.yaml` → `p/<family>.html`）；静态页 + `skillhub-audit-api`；公网 8081，后台 8082（loopback + Basic Auth + 8789 token），匿名埋点 | ✅ 2026-11-20 |

---

## 3. 组件登记（生成式）

> 本表由 `tools/gen_index.py` 从 `components/*/component.yaml` 生成；发版前跑 `python3 tools/gen_index.py --check`，禁止手工修改生成块内内容。
> 新建组件时先在 `components/<name>/component.yaml` 声明，再执行 `python3 tools/gen_index.py --write`。

<!-- GEN:COMPONENT-REGISTRY:BEGIN -->
| 组件 | 目录 | 版本 | 生命周期 | 分发变体 | 入口 |
|---|---|---|---|---|---|
| 认知管家 CogSteward `cogsteward` | components/cogsteward/ | v0.7.1 | active | — | 3 个 |
| 19-DAL 数据访问（内部） `dal-data` | components/dal-data/ | v0.1.0 | active | — | 1 个 |
| 事件上下文（官方源·五层装配） `event-context` | components/event-context/ | v1.0.2 | active | — | 3 个 |
| 数据服务（宏观·披露·链上·上下文） `market-data` | components/market-data/ | v1.0.3 | active | — | 6 个 |
| 市场事实日报 `market-facts-daily` | components/market-facts-daily/ | v1.0.4 | active | — | 1 个 |
| 手机预约助手 Mobile Reservation Assist `mobile-reservation-assist` | components/mobile-reservation-assist/ | v0.20.0 | draft | — | 1 个 |
| 预约助手 Reservation Assist `reservation-assist` | components/reservation-assist/ | v0.11.2 | draft | — | 1 个 |
| 研究博客发布 `site-blog` | components/site-blog/ | v1.0.0 | draft | — | 1 个 |
<!-- GEN:COMPONENT-REGISTRY:END -->

---

## 3.1 商品与发版状态（手工维护）

> 生成块只记录组件元数据；对外商品 ID、审核状态、价格与渠道在此维护。

| 组件 | 分发形态 | 版本 | 状态 |
|---|---|---|---|
| 认知管家 CogSteward | WorkBuddy Skill（本地安装，`components/cogsteward/skill/`） | v0.7.0 | 🟢 `init/scan/doctor/route/pack/triage/mark-done/rollback/config/index/map/skill lint/selfcheck` 与 `eval_golden`、`release_check` 已实现；九项指标由 `references/metrics-contract.json` 单一源驱动，`python3 -m unittest discover -s tests` 全部通过（2 项跳过）；真实黄金集待人工标注 |
| 认知管家 Pro `cogsteward-pro` | SkillPay 订阅制商品（¥2.99/月，`components/cogsteward/variants/pro/`） | v1.1.1 | 🟡 契约驱动 + `coverage` 透明；v1 销售中，`P0806000213876724` |
| 认知管家 Pro 按次版 `cogsteward-pro-pay` | SkillHub Pay Skill（¥0.99/次，`components/cogsteward/variants/pro-pay/`） | v1.1.1 | 🟡 口径对齐免费版 0.7.0（九项 + 契约），评测整改完成待发版 |
| 市场数据服务 `market-data-hub` | SkillPay 订阅制商品（¥19.9/月，试用 5 次，`components/market-data/skill/`） | v1.0.2 | 🟢 销售中 v1；**v2（包 1.0.2）审核中**；cloud 通道不支持 context；数据源措辞已与台账对齐（默认不接，例外见 DC-1） |
| 事件上下文服务 `event-context` | SkillPay 订阅制商品（¥19.9/月，试用 5 次，`components/event-context/skill/`） | v1.0.1 | 🟢 销售中 v1；**v2（包 1.0.1）审核中** |
| 市场事实日报 `market-facts-daily` | SkillPay 买断制商品（¥0.99，`components/market-facts-daily/skill/`） | v1.0.3 | 🟢 销售中 v3；**v4（包 1.0.3）审核中**；免责声明已与 DC-1 对齐，`--json` 携带 `data.v1` 外壳 |
| 数据服务专业版 `market-data-pro` | SkillHub Pay Skill（¥2.99/次，`components/market-data/variants/pro/`） | v1.0.3 | 🟢 已发布（评测 4.4）；1.0.3 评测整改完成待发版 |
| 事件上下文专业版 `event-context-pro` | SkillHub Pay Skill（¥2.99/次，`components/event-context/variants/pro/`） | v1.0.1 | 🟢 已发布（评测 4.5）；1.0.1 评测整改完成待发版 |

---

## 3.2 平台工程（非组件，不占 §3 登记位）

> 服务于本模块自身的发布、计费与运维，无外部分发形态；不计入组件依赖图、不参与 golden 输出校验（决策 DC-2，见 [SPEC-通用组件管理-架构重构-v0.1.md §11](./docs/SPEC-通用组件管理-架构重构-v0.1.md)）。

| 单元 | 路径 | 版本 | 职责 |
|---|---|---|---|
| SkillHub 体检收费后端 `skillhub-audit-api` | `platform/services/skillhub-audit-api/` | v1.2.0+ | 402 付费后端：规则 YAML v3 驱动（公开检查项数见 `platform/site/data/rules.json`），含免费额度/限流/埋点/管理口；已部署 49.233.123.96（8788 公开、8789 loopback） |
| 产品优化引擎 `product-optimizer` | `platform/optimizer/` | v0.1.0 | 发布前可发现性门禁：5 维 20 规则评分卡（`contracts/product-scorecard.yaml`）、`score/advise/ab/gate/report` CLI；`make check` 跑 legacy、`make release` 跑 new |
| 巡检 `patrol` | `platform/ops/patrol/` | — | 定时巡检与事故记录 |
| 沙箱测试 `sandbox` | `platform/sandbox/` | v0.1 | 复刻 402 付费协议的本地回归：16 场景、mock 服务、fixtures、基线报告（不改 Skill） |
| 发布交互 `skillhub-publisher` | `platform/tools-skills/skillhub-publisher/` | v1.2.0 | SkillHub 免费/付费发布协议 |
| SkillPay 工作流 `skillpay-workflow` | `platform/tools-skills/skillpay-workflow/` | v1.2.0 | 支付宝 / SkillHub / 402 三链路脚本入口 |
| 技能运营台 `skill-ops` | `platform/tools-skills/skill-ops/` | v1.1.0 | 每日运营闭环与竞品基线 |

---

## 4. 维护规则

1. 新增组件 → 先建 `components/<name>/component.yaml` 并跑 `python3 tools/gen_index.py --write` 与 `python3 platform/site/scripts/build_site.py --write`，再建目录与 SPEC
2. 组件升级 → 更新版本号（`component.yaml` 与 `skill/SKILL.md` 必须一致）+ CHANGELOG + §3.1 状态
3. 组件对外分发 → 必须通过「不依赖内部私有路径/数据」检查
4. 本模块 INDEX 变更 → 同步更新 [0-系统文档管理/INDEX.md](../0-系统文档管理/INDEX.md)
5. 任何 Skill 发新版本 → 按 `platform/tools-skills/skillpay-workflow/SKILL.md` §8 检查单执行，并在 §3.1 更新版本号
6. 内部工具与服务 → 登记 §3.2 平台工程，不进入组件依赖图与 golden 校验
7. 任何组件发版前 → 必须跑 `make check`（`sync_kernel --check` + G1–G7 + `gen_index --check` + `sync_rules --check` + `build_site --check` + 规则测试），全绿才允许 `make build` 打包
8. 体检规则变更 → 只改 `contracts/skill-quality-rules.yaml`（bump version + changelog），再跑 `python3 tools/sync_rules.py --write` 与 `python3 platform/site/scripts/build_site.py --write`，禁止手改生成物
