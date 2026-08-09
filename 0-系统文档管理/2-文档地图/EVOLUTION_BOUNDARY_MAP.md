# 进化系统边界地图（EVOLUTION_BOUNDARY_MAP）

> **版本**: v1.0 | **创建**: 2026-08-09 | **依据**: SSoT v3.0 §2.5.2 + COGNITIVE_ARCHITECTURE.md v3.4 + superpowers-integration-design.md
> **目的**: 理清两大进化系统与认知系统两分结构，**防止跨层误改**。任何涉及"进化"的修改前必读本文档。

---

## 1. 两大进化系统（SSoT §2.5.2 明确切分）

> 原文："Evolution 处理的是'交易策略怎么变'，认知系统处理的是'代码怎么写'。"

### A. 交易系统自进化（"交易策略怎么变"）

| 项 | 内容 |
|:---|:---|
| 进化对象 | 交易参数（confidence_threshold 等）→ `data/okx_sim/config.json` → 生产引擎 |
| 核心代码 | `11-易经推理系统/scripts/memory_l4/self_evolution_engine.py`（SelfEvolutionEngine，三层反思闭环：A8/做梦部/联网） |
| 回测门禁 | `memory_l4/evolution_backtest.py`（walk-forward 真回测，PROP-20260809） |
| 参数寻优 | `memory_l4/evolution_optimize.py`（Optuna 数据驱动，PROP-20260809） |
| 生产接线 | `BCRMEngine.from_config()`（bcrm/engine.py，PROP-20260810） |
| 执行链 | A 系列 cron（A1-A9）= 分析/执行链，是进化的**输入源与执行器**，不是进化引擎本身 |
| 提案治理 | `memory_l4/evolution_config.json` 白名单 + `docs/proposals/PROP-*.md` + 飞书审批（trading 类） |

### B. 认知系统进化（"代码怎么写"）

| 项 | 内容 |
|:---|:---|
| 进化对象 | 开发流程（SKILL / Solution Path）+ 记忆质量等级 |
| 核心代码 | `4-MEMORY/9-工具与接口/cognitive_*.py`（9 文件）：cognitive_daemon（5s mtime 轮询）/ cognitive_hook（git post-commit 触发）/ cognitive_session / cognitive_superpowers / cognitive_backtest / cognitive_loop_entry / cognitive_mcp_server / cognitive_install / cognitive_health_check |
| 进化机制 | 贝叶斯 v2（Beta-Binomial + 指数遗忘）；cognitive_backtest.py 统一回测框架（P1/P2/P3 更新验证） |
| 触发方式 | git commit → cognitive_hook.py → 提取行动链 → 生成/更新 Solution Path |

---

## 2. 认知系统内部结构：开发认知 × 交易认知（两大维度，用户 2026-08-09 定义）

> 依据 SYSTEM_ARCHITECTURE_OVERVIEW.md §1/§6.1（"交易决策闭环 + 开发认知闭环，对称"）+ TECHNICAL_DESIGN §6.6 + COGNITIVE_ARCHITECTURE.md v3.4。
> **主维度 = 开发认知 / 交易认知**（按领域分）；通用/应用是**次级分层**（按抽象度分），每个维度内部都有。

### 2.1 两大维度

| 维度 | 解决什么 | Process 层 Skill | 应用记忆落点 | 召回路由 |
|:---|:---|:---|:---|:---|
| **开发认知** | "代码怎么写" | 元认知 Superpowers 14 Skill（`0-元记忆/superpowers/skills/`） | APP-DEV-* → `1-开发记忆单元/solution_paths/` | 开发类 task_type |
| **交易认知** | "交易怎么决策" | T 系列 6 Skill T0-T5（`0-元记忆/trading-cognition/skills/`） | APP-TRD-* → `2-交易记忆单元/solution_paths/`（MU-TRD 路由） | 8 个交易 task_type（strategy-research/backtest/execution/governance 等） |

**T 系列定义**（TECHNICAL_DESIGN §6.6）：T0 市场认知(A0+A1+A2) / T1 战略合成(A3) / T2 交易执行(A4+A5+A9) / T3 风控门禁 t3-risk-gatekeeper(A7+A4) / T4 情报雷达 t4-intelligence-radar(A6) / T5 元认知复盘 t5-meta-reflection(A8)。
✅ Mac 端原版 T 系列已入库（2026-08-09 main@273110c0，含 cognitive-supplement.md 本地化补充，SkillLoader 双源加载验证通过）。

### 2.2 次级分层（每个维度内部）

| 层 | 名称 | 进化规则 | 红线 |
|:---|:---|:---|:---|
| 通用层 | 原版 SKILL.md（开发=Superpowers，交易=T 系列） | 只增不改，允许系统性完善 | **原版内容禁改**；补充写入同级 supplement 文件 |
| 应用层 | Solution Paths（APP-DEV-* / APP-TRD-*） | 贝叶斯进化 C→B→A→S；交易类用客观指标（P&L/夏普/回撤/胜率 → path_advantage） | 等级由验证驱动，不手工改 |

**认知三要素** = Knowledge（2-KNOWLEDGE）+ Memory（4-MEMORY L0/L1/L2）+ Process（上表 Skill 体系）

### 2.3 运行实体（2026-08-09 激活）

| 组件 | 状态 | 说明 |
|:---|:---|:---|
| SkillLoader 双源加载 | 🟢 14 开发 + 6 交易 | cognitive_superpowers.py（COG-FIX-20260809 修复 macOS 硬编码路径） |
| cognitive_daemon | 🟢 systemd 用户服务 cognitive-daemon.service | 全仓库文件监听 5s/防抖10s |
| git post-commit hook | 🟢 已安装 | commit → 经验捕获 → 贝叶斯验证 |
| L1 向量库 | 🟢 4-MEMORY/data/cognitive_memory.db | 2026-08-09 初始化 |
| trading_recall() API | 🟢 已验证 | polling_trader A7 门禁前注入（建议非约束，失败安全） |
| MCP server | ⚪ 未接入 Hermes | cognitive_mcp_server.py 存在，待配置 |

---

## 3. 相关但独立的"进化"实体（四个同名，勿混淆）

| 实体 | 位置 | 性质 | 状态 |
|:---|:---|:---|:---|
| `self_evolution_engine.py` | 11-易经推理系统/scripts/memory_l4/ | 交易**参数**进化（A 类） | 🟢 生产（PROP-20260809/810 升级） |
| `EvolutionEngine`（evaluation_memory.py） | 1-ARCHITECTURE/dreamos/core/memory/ | DreamOS **经验教训**进化（LessonDistiller/GapAnalyzer/NodeOptimizer） | 🟢 已实现 |
| `3-EVOLUTION/` TS 引擎 | 3-EVOLUTION/*.ts | 实验进化引擎（9 阶段流水线 + 三桥接） | ⚠️ **实验态，未集成主线**，改动不影响生产 |
| 「记忆进化」cron | 治理周二 22:00 | 记忆审计/压缩（治理层） | 🟢 运行中，与上面三者无关 |

---

## 4. 两系统的交互接口（唯一合法通道）

```
交易实践（A系列/polling_trader）
      │ P&L / 决策记录 / episode
      ▼
A8 知行合一校验（gap_score）──┐
      │                        │  记忆系统（L0/L1/L2）
      ▼                        │  = 两系统互通介质
交易参数进化（A类）             │
      │ config.json            │
      ▼                        ▼
生产引擎生效            认知进化（B类）：行动链沉淀 → Solution Path
```

- 互通介质：**记忆系统**（SSoT 原则 2："两个闭环各自螺旋上升，通过记忆系统互通"）
- 禁止：A 类代码直接写 solution_paths/；B 类代码直接改 config.json 交易参数

---

## 5. 修改前检查清单（防误改）

1. 改"进化"相关代码前，先确认目标属于 A 类还是 B 类（本文档 §1）
2. A 类修改范围：`11-易经推理系统/scripts/memory_l4/` + 其 docs/proposals/；须走提案+审批（trading 类）
3. B 类修改范围：`4-MEMORY/9-工具与接口/`；通用认知层遵守"只增不改"红线
4. 涉及两层交互 → 只走记忆系统通道（§4）
5. `3-EVOLUTION/` 是实验区，不要在那里找生产逻辑，也不要把生产改动放进去
6. PROP-20260809/810 归属核验：全部在 A 类范围内，零触碰 B 类 ✅

---

**维护**: 本文档属 0-系统文档管理/2-文档地图 导航体系，架构变更时随 SSoT 同步更新。
