# 🌐 6-TRADING 系统级主索引 (v1.1)
> **审定**: 2026-06-13
> **覆盖率**: 48/427 = 11.2%（有INDEX） | 0 个 C 级目录（已全部修复）
> **飞书 Base**: 49/50 条「有INDEX」, 0 条「无INDEX」
> **架构**: governance-meta-chain v3.1 — 三段式脑暴→固化→执行
> **调度**: Hermes cron (AI) + Linux crontab (零Token) 双轨
> **导航**: 遇到问题 → 先查本索引 → 找对应目录 → 读目录级 INDEX

---

## Ⅰ. 系统总览

```
                          Dreambuddy-V2 交易系统
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
        🏛️ 架构层        📊 交易层         🛠️ 支持层
    (1-ARCHITECTURE)  (6-TRADING)        (7-产物中台)
            │                 │                 │
        ⚖️ 治理层        🧠 知识层         🔗 集成层
    (2-GOVERNANCE)    (knowledge/)       (8-FEISHU / deploy)
            │                 │
        🗄️ 存储层        ⚡ 运行时层
    (4-MEMORY)          (.hermes / .workbuddy)
```

| 层级 | 目录 | 用途 | 索引状态 |
|:---|:---|:---|---:|
| **🏛️ 架构** | `1-ARCHITECTURE/` | 系统设计文档、架构图、FAQ | ✅ 有 README |
| **⚖️ 治理** | `2-GOVERNANCE/` | 治理规则、合规检查、权限 | ✅ 有 README |
| **🖥️ 前端** | `3-FRONTEND/` | dream-universal-gateway UI | ✅ 有 README |
| **🗄️ 存储** | `4-MEMORY/` | 系统记忆、状态持久化 | ✅ 有 README |
| **💼 业务** | `5-BUSINESS/` | 非交易业务逻辑 | ✅ 有 README |
| **📊 交易** | `6-TRADING/` | ⭐ 核心交易系统 | ✅ 有 README |
| **📦 产物** | `7-ARTIFACT-HUB-V2/` | 产物中心 v2 | ✅ 有 README |
| **📦 产物(旧)** | `7-产物中台/` | 产物中心、研究索引、策略主线 | ❌ 需 INDEX |
| **💬 飞书** | `8-FEISHU/` | 飞书集成(Bitable/审批/文档/Wiki) | ✅ 有 README |
| **🎨 视觉** | `_visual/` | 可视化设计资源 | ❌ 需 INDEX |
| **🚀 部署** | `deploy/` | 部署配置(Hermes skills/cron/memories) | ❌ 需 INDEX |
| **📚 文档** | `docs/` | superpowers 设计文档 | ❌ 需 INDEX |
| **🧠 元数据** | `dreambuddy/` | 元数据、历史产物 | ❌ 需 INDEX |
| **🛠️ 脚本** | `scripts/` | 独立工具脚本 | ❌ 需 INDEX |
| **🔗 三链开发** | `3-CHAIN-DEVELOPMENT/` | 多Agent接力开发方法论（D调研→Z规划→E执行） | ✅ 14+3 文件 |

---

## Ⅱ. 交易系统 (6-TRADING/)

> **核心**: 三屏交易框架 + A系列状态机 + V15基线信号
> **排程**: 双轨调度 — Hermes cron (A1-A9 AI驱动) + crontab (A1/A4/A5/V15 零Token)

### 子系统索引

| 目录 | 用途 | 入口 | 索引 |
|:---|:---|---:|:---:|
| `skills/` | 交易 SKILL (Screen1-3 / A系列 / 智能分析) | → [INDEX](6-TRADING/skills/INDEX.md) | ❌ 新建 |
| `scripts/` | 自动化脚本 (crontab 零Token执行) | → [INDEX](6-TRADING/scripts/INDEX.md) | ❌ 新建 |
| `knowledge/` | 知识库 (哲学/理论/经验三层) | → [INDEX](6-TRADING/knowledge/INDEX.md) | ✅ |
| `artifacts/` | 交易产物的本地归档 | → [INDEX](6-TRADING/artifacts/INDEX.md) | ❌ 新建 |
| `config/` | 交易配置 (参数/阈值/策略配置) | → [INDEX](6-TRADING/config/INDEX.md) | ❌ 新建 |
| `sessions/` | 历史交易会话记录 | → [README](6-TRADING/sessions/README.md) | ✅ |
| `bridge/` | 跨系统桥接 (API/工具) | → [INDEX](6-TRADING/bridge/INDEX.md) | ❌ 新建 |
| `logs/` | 交易系统运行日志 | → [INDEX](6-TRADING/logs/INDEX.md) | ❌ 新建 |
| `baselines/` | 基线策略存档 (V9/V15) | → [README](6-TRADING/baselines/README.md) | ✅ |
| `automation/` | 自动化流程配置 | → [INDEX](6-TRADING/automation/INDEX.md) | ❌ 新建 |
| `reports/` | 历史分析报告 | → [INDEX](6-TRADING/reports/INDEX.md) | ❌ 新建 |

### 知识库层

| 层级 | 目录 | 文件数 | 用途 | 索引 |
|:---|:---|---:|:---|:---:|
| 🏛️ **哲学** | `knowledge/0-哲学/` | 4 | 不可违反的最高原则 | ❌ 新建 |
| 📐 **理论** | `knowledge/1-理论/` | 11 | 可辩论的方法论框架 | ❌ 新建 |
| 📊 **经验** | `knowledge/2-经验/` | 15 | 实战数据和参数 | ❌ 新建 |

### 技能分布

| 分类 | SKILL 数 | 功能域 |
|:---|:---:|:---|
| **三屏交易** | 3 | Screen1(周线)、Screen2(日线)、Screen3(日内) |
| **A系列** | 9 | A1调研→A2第一性原理→A3策略→A4验证→A5执行→A6监控→A7实践→A8检验→A9离场 |
| **智能分析** | 6 | 矛盾论、Regime检测、评分、阻力、贝叶斯、琢梦部 |
| **认知体系** | 3 | 知识库、Master研讨、信号评分 |
| **运营/工具** | 5 | 秘书、双代理冲突、百炼、仓位、执行成本 |

---

## Ⅲ. 运行时系统 (.hermes/)

> **核心**: Hermes Agent 运行时 + cron 调度器
> **文件总量**: ~81K (含 node_modules)

| 目录 | 用途 | 快速链接 |
|:---|:---|:---:|
| `~/.hermes/skills/` | 🔧 所有 Hermes 技能 (含系统/交易/治理) | `skill_view(name)` |
| `~/.hermes/cron/` | ⏰ 定时任务调度器 + 近期产出 | `cronjob list` |
| `~/.hermes/scripts/` | 📜 no_agent 自动化脚本 | 见记忆 |
| `~/.hermes/plugins/` | 🔌 平台插件 (飞书/微信/看板等) | `hermes plugins list` |
| `~/.hermes/providers/` | 🧠 AI 模型提供商配置 | `cat config.yaml` |
| `~/.hermes/data/` | 📊 缓存数据 (v15信号/空) | 看记忆 |
| `~/.hermes/tmp/` | 🗑️ 临时文件 | 自动清理 |
| `~/.hermes/logs/` | 📋 运行日志 | `tail -f` |
| `~/.hermes/backups/` | 💾 系统备份 | `ls backups/` |
| `~/.hermes/hermes-agent/` | 🏗️ Hermes 项目源码 | VSCode |

### 调度详情

| 系统 | 任务 | 频率 | 模式 |
|:---|:---|:---:|:---:|
| **Hermes cron** | A1-A6, A9, Screen1-3, 治理归档 | 各种 | AI+LLM |
| **Linux crontab** | A1脚本, A4, A5, V15信号 | 1-8h | 零Token Python |

_控制权由 `token_budget_state.json` + `trading_execution_loop.json` 联合控制_

---

## Ⅳ. 工作台系统 (.workbuddy/)

> **核心**: 秘书系统 + 产物缓存 + 状态机

| 目录 | 用途 | 关键文件 |
|:---|:---|:---:|
| `memory/` | 🧠 状态机 + 事件记录 | `trading_execution_loop.json` |
| `skills/boss-secretary/` | 📨 秘书邮件系统 | `reports/trading/` |
| `skills/dream-exit-skill-v2/` | 🚪 A9离场决策SKILL | `__pycache__/` |
| `skills/dream-oneirology/` | 🌙 琢梦部 | `intelligence_input/` |
| `artifacts/trading/` | 📦 交易产物缓存 | `screen2/` 等 |

---

## Ⅴ. 快速导航

### 高频入口（按使用频率）

| 需求 | 路径 |
|:---|:---|
| 🔍 **查知识库** | `6-TRADING/knowledge/INDEX.md` |
| 📋 **思维链门禁系统** | `3-CHAIN-DEVELOPMENT/5-GATES/INDEX.md` |
| 📋 **三链开发架构** | `3-CHAIN-DEVELOPMENT/README.md` |
| 📋 **工作笔记本** | `NOTEBOOK.md` |
| 📋 **接力协议** | `3-CHAIN-DEVELOPMENT/4-PROTOCOL/PROTOCOL.md` |
| 📋 **Guard 脚本** | `3-CHAIN-DEVELOPMENT/scripts/chain_guard.py` (`python3 chain_guard.py status`)|
| 📋 **看cron任务** | `cronjob list` |
| 📊 **状态机状态** | `~/.workbuddy/memory/trading_execution_loop.json` |
| 📉 **V15信号** | `6-TRADING/artifacts/v15/latest.md` |
| 🗓️ **Screen2最近产出** | `6-TRADING/artifacts/screen2/` |
| 🧠 **记忆** | `memory` (系统工具) |
| 💾 **最近会话** | `session_search()` |

### 故障排查路径

```
A系列全[SILENT] → 查状态机 status phase match
                → 查 cron 调度器 next_run_at
                → 查 token_budget_state.mode
三屏基线vsA系列冲突 → 查控制权审计 pattern
知识库无解 → 联网搜索 → 回补知识四层
```

### 设计文档索引

| 文档 | 位置 | 用途 |
|:---|:---|:---|
| 日内架构 | `1-ARCHITECTURE/README.md` | A系列状态机设计 |
| 交易流程 | `6-TRADING/TRADING_WORKFLOW_SPEC_v1.md` | 全流程规格 |
| 宪法合规 | `6-TRADING/docs/CONSTITUTION_COMPLIANCE.md` | 宪法映射 |
| 元认知架构 | skill: `governance-meta-chain` | 双链路思考模型 v3.1 |

---

## Ⅵ. 进化生态

> **核心**: 交易系统持续进化引擎。OKR驱动 → 联网学习 → Base记录 → 审批验收
> **架构**: OKR + Feishu Base + SKILL + Approval
> **Baseline**: 三屏+马丁策略技术指标(0 Token) | **门禁**: 贝叶斯+3月回测>基线

| 资产 | 职责 | 入口 |
|:---|:---|:---:|
| **OKR「Dreambuddy-V2 交易进化系统」** | 6个KR跟踪进度 | [飞书OKR](https://icnic28nu1x5.feishu.cn/okr/user/7643352787538955204/) |
| **Base「交易优化注册表」** | 每条优化提案的状态跟踪 | [管理面板](https://icnic28nu1x5.feishu.cn/base/EgINbsT8iaVJ5psDm2Hc7RKqnbd) |
| **trading-evolution SKILL** | 联网搜索→学习→回补→验收 | `skill_view("trading-evolution")` |
| **审批「交易系统优化提案验收」** | 重大变更需你审批 | `approval_code: 096DC318-681B-478A-90CC-BD9701FC732C` |
| **演化日志** | 每次进化的产出记录 | `3-EVOLUTION/changelog.md` |

### 6个进化方向

| 方向 | KR | 第一责任人 |
|:---|---:|:---:|
| 🏗️ 架构优化 | KR1 | A系列状态机调度健壮性 ≥3项 |
| 💻 代码优化 | KR2 | 回测引擎+数据链路可用率 ≥95% |
| 📦 SKILL优化 | KR3 | 新增/迭代SKILL ≥5个 |
| 📚 知识库优化 | KR4 | 内容完善度 ≥90% |
| 📖 理论进化 | KR5 | 联网学习 ≥8篇/月 |
| 🔧 工具进化 | KR6 | 覆盖 ≥3方向 |

### 7大进化系统审批模板

| # | 系统 | 模板Code | 对应Cron |
|:---:|---|---|:---:|
| 1 | **交易系统** | `096DC318-681B-478A-90CC-BD9701FC732C` | trading-evolution-weekly (周一10:00) |
| 2 | **索引系统** | `2F40FE12-255E-4FD4-AAD7-FD36C45FEA66` | index-ops (周三23:00) |
| 3 | **知识库系统** | `E2F6E668-025B-4845-B08A-E3FBB67D016F` | knowledge-sync (周四22:00) |
| 4 | **思维链系统** | `F565BFD2-B7CA-4C80-B634-77D9FAABB193` | 思维链门禁审计 (周五10:00) |
| 5 | **Hermes记忆进化系统** | `0C29BB66-2BFE-4477-B8AE-213CF21B4F84` | Hermes记忆进化 (周二22:00) |
| 6 | **Token节省优化系统** | `386C4416-A39A-41C4-9800-546061A83A4B` | Token节约优化 (周三22:00) |
| 7 | **元链治理系统** | `670573D9-4375-437F-B824-5FEC035932E0` | 元链治理 (周日22:00) |

### 调度

| 任务 | 频率 | 职责 |
|:---|:---:|:---|
| `trading-evolution-weekly` (Hermes cron) | 每**周一10:00** | 交易系统联网搜索+学习回补+Base更新+审批 |
| `Hermes记忆进化` (Hermes cron) | 每**周二22:00** | Hermes记忆进化系统审计 |
| `索引系统token节约` (Hermes cron) | 每**周三22:00** | Token节约优化 |
| `index-ops` (Hermes cron) | 每**周三23:00** | 索引审计 + 反向同步 |
| `knowledge-sync` (Hermes cron) | 每**周四22:00** | 知识库同步 + 飞书Wiki更新 |
| `思维链门禁审计` (Hermes cron) | 每**周五10:00** | 三链门禁/步进式笔记本/D-Z-E审计 |
| `元链治理` (Hermes cron) | 每**周日22:00** | 治理审计(含做梦部+A0+A8) |

---

## Ⅶ. 系统边界

| 领域 | 归属系统 | 关键约束 |
|:---|:---|:---:|
| **交易决策** | 6-TRADING | V9不可改、MA200锚定、V9无单笔上限 |
| **状态调度** | .hermes cron | phase guard、control_mode、双模 |
| **知识管理** | 6-TRADING/knowledge | 哲学(不变)→理论(可调)→经验(积累) |
| **产物投递** | 双通道 | boss-secretary + artifacts/ |
| **飞书通信** | .hermes gateway | 5群 + 飞书API |
| **AI Token** | .hermes token_budget | 100元/月、80%剩余 |

---

## Ⅷ. 任务分级与模型路由 (Task Grading)

> 每个任务都有它应得的模型。tier-map.json 是中心配置，tier-sync.py 自动同步所有 cron。

### 等级体系

| 等级 | 名称 | 模型 | Token/次 | 典型任务 |
|:---:|:---|:---|:---:|:---|
| **G4** | 战略级 | v4-pro | ~80K-200K | A1/A2/A3/A9 (已锁定) |
| **G3** | 复杂级 | v4-flash | ~20K-80K | A4/A5/A6 (A4/A5已降级) |
| **G2** | 常规级 | v4-flash | ~5K-20K | Screen1/2/3, ProcessD, Governance, IndexOps |
| **G1** | 简单级 | self-deepseek | ~1K | ApprovalTimeout, GroupMention (⏳待配置) |
| **G0** | 无脑级 | 无(no_agent) | 0 | TokenBudget, Orchestrator, A8Review |

### 核心文件

| 文件 | 路径 |
|:---|---:|
| `tier-map.json` | `hermes-agent/tier-map.json` |
| `tier-sync.py` | `hermes-agent/tier-sync.py` |
| 飞书Base | `任务分级注册表` (K4osbfDb4aUPxbsvspicJYOQnte) |
| SKILL | `task-grading` (governance) |

### 最近降级

| 任务 | 原模型 | 新模型 | 节省估算 |
|:---:|:---|---:|:---:|
| A4 (每240分钟) | v4-pro | v4-flash | ~90% Token |
| A5 (每480分钟) | v4-pro | v4-flash | ~90% Token |

---

> **维护**: 本索引由 governance-daily-archive cron 自动审计更新。
> **反馈**: 发现死链/过时内容 → 通知系统更新。
