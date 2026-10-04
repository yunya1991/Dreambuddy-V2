# SPEC — PR68 意图识别与 DreamOS 优化技术内核评估

> **状态**: 📋 评估稿，待用户审阅
> **范围**: 仅评估，不含代码实施
> **来源**: PR68 分支（`pr-68` / `origin/integrate-remote`）
> **编制日期**: 2026-09-15
> **关联**: 替代 `PROP-20260829-hermes-drives-dreamos*.md` 两份 Hermes 旧方案

> ⚠️ **架构定位更新（2026-09-16）**：意图识别的权威规范已明确为
> [`intent-recognition-spec/intent-taxonomy.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/intent-recognition-spec/intent-taxonomy.md)，
> 采用 **6×30 对话意图体系**，落地于 DreamOS 操作系统内核 S 层。
> 本 SPEC 评估的前端 35 型正典（intent-schema.ts）作为过渡方案，最终应迁移到 DreamOS 内核统一意图识别。
> 意图识别分两层：对话意图（内核 6×30）+ 策略意图（交易能力域 7 种）。

---

## 0. 评估目的

PR68 分支基于 **Hermes** 作为外部 LLM agent runtime 设计了一套"前端 → Hermes 意图识别 → DreamOS 物理编排"的架构。引入 **DeepSeek Harness** 后，Hermes 已变成架构债务——Harness 通过 Cordis plugin + IPC 直接调用 DreamOS，无需中间的 Hermes 层。

本 SPEC 不采纳 PR68 的 Hermes 驱动方案，但**提取其中关于意图识别和 DreamOS 优化的技术内核**，评估其在 DeepSeek Harness 架构下的可复用性，并给出整合路径建议。

**核心判断**：PR68 的意图识别管线（TS 侧 4 级管线 + 正典 35 型）和 DreamOS 优化（复杂度分级 + 渐进式编排）是与 Hermes 解耦的纯技术资产，可直接迁移到 Harness 架构。

---

## 1. 意图识别技术内核（前端 TS 侧）

### 1.1 意图正典 (Single Source of Truth)

**源文件**: `3-FRONTEND/dream-universal-gateway/src/lib/intent/intent-schema.ts`

**核心设计**:
- **35 型正典**：15 基础意图（系统级）+ 20 多场景分析意图（深度分析子类）
- **环归属**：execution（执行环）/ intelligence（情报环）/ governance（治理环）/ general（通用环）
- **角色门禁矩阵**：FREE / PRO / ADMIN 三级（草案，未强制）
- **三链别名映射双向无损**：planner 视图（11 型，`risk_alert` ↔ `risk_alert_response` 命名分歧修复）
- **Legacy 视图降级**：20 场景意图归并到自然父类 `deep_analysis`（task 链按父类路由）

**技术价值评估**:
| 维度 | 评估 | 说明 |
|---|---|---|
| 架构正交性 | ⭐⭐⭐⭐⭐ | 零运行时依赖，可被所有链安全引用 |
| 命名分歧修复 | ⭐⭐⭐⭐ | planner `risk_alert` vs fallback `risk_alert_response` 双向映射 |
| 可扩展性 | ⭐⭐⭐⭐ | 新增意图必须在 schema 登记（编译期类型约束） |
| 角色门禁 | ⭐⭐⭐ | 草案状态，Phase 3 评审后才强制 |

**对 Harness 架构的迁移建议**:
- **直接复用**：intent-schema.ts 与 Hermes 零耦合，可原样保留
- **唯一调整**：环归属中 `intelligence` 环意图过桥逻辑（原走 Hermes MCP），改为走 Harness Cordis plugin + IPC
- **价值**：DeepSeek Harness 的 agent loop 通过此正典可做出"哪些意图委托 DreamOS 物理编排"的决策

### 1.2 统一意图识别管线（四级）

**源文件**: `intent-unified.ts`

**管线架构**:
```
⓪ 追问检测（零 LLM）→ 继承 last_intent + last_symbol
    ↓ 不命中
① command-fastpath（零 LLM）→ /斜杠命令 + 中文命令词典精确匹配
    ↓ 不命中
② FC 结构化识别（callLLM + recognize_user_intent 工具）+ 修复级联
    ↓ FC 失败/修复失败
③ 规则引擎兜底（matchRuleEngine，零 LLM）
    ↓ 无命中
④ 默认兜底（defaultFallback）
```

**关键技术点**:
1. **追问检测最优先**：`detectFollowUp` 在所有路径之前，继承 `last_intent/last_symbol/last_complexity`，confidence=0.85
2. **FC 参数修复级联**：`repairIntentArgs` 处理 LLM 返回的缺字段/类型错误/意图值非法
   - intent: trim/lowercase → aliasToCanon → 正典
   - confidence: 数值化 + [0,1] 钳制
   - entities: 仅保留字符串值，symbol 大写规范化
   - complexity: 非法值默认 `moderate`
   - 审计痕迹：`repairs` 数组记录所有修复动作
3. **记忆双写**：`finalize` 函数单点补录，失败不阻塞主流程
4. **方法可观测**：`IntentMethod` 类型标记识别路径（rule/fc/llm/follow_up/default）

**技术价值评估**:
| 维度 | 评估 | 说明 |
|---|---|---|
| 降级链路 | ⭐⭐⭐⭐⭐ | FC 失败→规则兜底→默认兜底，FAIL-OPEN 完整 |
| LLM 成本控制 | ⭐⭐⭐⭐ | ⓪①零 token，②才调 LLM |
| 参数鲁棒性 | ⭐⭐⭐⭐⭐ | 修复级联处理 LLM 输出缺陷 |
| 追问继承 | ⭐⭐⭐⭐ | 上下文连续性保证 |

**对 Harness 架构的迁移建议**:
- **方案 A（推荐）**：保留 TS 侧管线，作为 Harness agent loop 的"意图识别 tool"（Cordis plugin 包装）
  - Harness agent loop 调用 `recognizeIntentUnified` → 返回 `UnifiedIntentResult`
  - 再由 Harness 决定走 DreamOS 物理编排还是直答
- **方案 B**：迁移到 Python server 侧作为 IPC 方法
  - 优势：与 DreamOS IntentEngine 同进程，减少跨语言开销
  - 劣势：TS 侧 4 套意图实现的迁移工作量大
- **建议**：先走方案 A，TS 侧管线已验证可用（golden-set 23/23 一致率），Harness 包装为 tool 即可

### 1.3 命令快路径

**源文件**: `command-fastpath.ts`

**设计要点**:
- `/斜杠命令` 正则匹配：`/^\s*\/([a-zA-Z\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff-]*)/`
- 中文命令词典整句精确匹配（trim 后）：`查看状态`→`status`、`暂停交易`→`pause` 等 10 条
- **宁可漏不可误**：不做子串匹配，避免"帮我查看一下状态好吗"被误拦

**对 Harness 的价值**: 直接复用，零 LLM 成本处理系统命令

### 1.4 影子对比探针

**源文件**: `shadow-probe.ts`

**设计哲学**:
- **旧路径为准**：统一管线仅并行执行并记录差异，不改变对外行为
- **预算上限硬编码**：SHADOW_BUDGET=200 样本，达到自动停影子（磁盘样本数为准，跨进程重启仍生效）
- **记忆污染封闭**：影子调用传 `recordMemory=false`，不写入 intent-memory
- **任何失败静默吞掉**：绝不影响主路径
- **原子追加写**：`appendFileSync` 写 JSONL

**实测修正记录**:
- 原设计 `SHADOW_MAX_TOKENS=50`，实测 FC tool_call 需 ~100 token（4 条样例：98/99/91/97），50 会截断 arguments JSON
- 修正为 `SHADOW_MAX_TOKENS=150`（观测峰值 99 × 1.5 安全边际）

**技术价值评估**:
| 维度 | 评估 | 说明 |
|---|---|---|
| 灰度切流安全性 | ⭐⭐⭐⭐⭐ | 新旧并行，旧为准，差异可观测 |
| 预算控制 | ⭐⭐⭐⭐ | 硬编码 200 样本，跨进程生效 |
| 记忆污染防护 | ⭐⭐⭐⭐⭐ | recordMemory=false 封闭 |
| 实测修正 | ⭐⭐⭐⭐ | token 上限从 50→150 有实证依据 |

**对 Harness 的价值**: 这是 PR68 最具工程价值的资产之一。Harness 接入 DreamOS 时可采用同样的影子探针模式——Harness 路径与旧路径并行，旧为准，差异写 JSONL，达到一致率阈值才切流。

---

## 2. DreamOS 优化技术内核（Python 侧）

### 2.1 问题复杂度分级器

**源文件**: `1-ARCHITECTURE/dreamos/core/sense/complexity_classifier.py`

**分级定义**:
| 档 | 含义 | 编排建议 | 典型例子 |
|---|---|---|---|
| T0 | 简单查询 | 零编排直答（≤2s） | "BTC多少钱" |
| T1 | 单域问题 | phase=1 渐进式起步 | "BTC 现在能做多吗" |
| T2 | 多域/战略 | 完整多链编排 | "综合评估本周行情并制定策略" |
| T3 | 深度研究 | 委托深度分析（原写 Hermes，需改） | "对这波回调做深度分析" |

**设计原则**:
- **纯规则、零 Token、毫秒级**：规则优先，无命中时保守落档
- **宁浅勿深**：模糊时倾向更浅的档，避免过度编排浪费
- **不改变意图类型**：只附加复杂度维度

**规则优先级**: T3（深度触发词）> T0（纯查询）> T2（战略/多域）> T1（默认）

**黄金集验证**: 23 条测试用例，一致率 23/23 = 100%（AC2 要求 ≥90%）

**影子观测**: `log_shadow_event` 落 `~/.dreamos/phased_shadow.jsonl`，best-effort 不抛异常

**Hermes 遗留点**:
- `TIER_DESCRIPTIONS` 中 T3 = "委托 Hermes 深度分析"
- `tier_orchestration_hint` 中 T3 mode = `delegate_hermes`

**对 Harness 的迁移建议**:
- **直接复用分级器本体**：规则词表和分级逻辑与 Hermes 零耦合
- **T3 委托对象改为 Harness**：`delegate_hermes` → `delegate_harness`（Harness agent loop 委托 A 系列深度分析）
- **价值**：Harness 接到用户输入后，先调 `classify_complexity` 决定编排深度，T0 直答、T1 走 phase=1、T3 委托深度分析

### 2.2 渐进式编排（phase 参数）

**源文件**: `dreamos/core/arrange/graph_planner.py` + `types.py`

**设计**:
- `phase=None`：完整编排（默认，向后兼容，零回归）
- `phase=1`：仅执行 `is_required` 节点，可选节点记入 `deferred_nodes` 并生成 `next_step_hint`
- `phase=2`：完整执行（语义上的"深化追问"）

**安全兜底**: 若 phase=1 过滤后为空（链路无必要节点），回退完整编排

**数据结构扩展**（`ExecutionPlan`）:
```python
phase: Optional[int] = None
deferred_nodes: List[str] = field(default_factory=list)
next_step_hint: str = ""
```

**API 端点支持**: `api_server.py` 的 `_parse_phase` 函数解析请求体中的 phase 参数（仅接受 1 或 2）

**验收锚点**:
- AC1 轻量首答：phase=1 → 节点 ≤5、估算 tokens 显著下降（1000 vs 5300）
- AC3 零回归：phase 缺省编排与基线快照逐字段一致

**对 Harness 的价值**:
- **直接复用**：Harness Cordis plugin 调用 DreamOS IPC 时传 `phase` 参数
- **对话模式**：Harness agent loop 可实现"先呈现后追问"——首答 phase=1，追问"展开/深入"时 phase=2
- **T0 短路**：复杂度分级 T0 时，Harness 直接报行情快照，不触发 DreamOS 编排

### 2.3 DreamOS MCP Bridge（需重构）

**源文件**: `dreamos/apps/dreamos_mcp_server.py`

**Hermes 包装内容**:
- 文件头声明 "Hermes ↔ DreamOS 物理编排的 MCP 适配器"
- 硬编码路径 `/home/ubuntu/.hermes/hermes-agent/venv/bin/python3`
- 注册方式写入 `~/.hermes/config.yaml`

**技术内核（剥离 Hermes 后有价值）**:
- **懒启动 api_server**：未运行时自动拉起，等待健康检查通过
- **HTTP 转发**：4 个只读工具
  - `dreamos_health`：服务健康 + 预算守卫状态
  - `dreamos_recognize_intent`：只读意图识别（S 层）
  - `dreamos_run_analysis`：完整编排（S→P→E→action），自动装配实时行情
  - `dreamos_list_nodes`：能力节点注册表
- **结果结构化回流**：JSON 结构化返回

**对 Harness 的迁移建议**:
- **不迁移此文件**：dream-harness-bridge 的 [python-server/server.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/packages/python-server/server.py) 已通过 IPC + Cordis plugin 实现了等效的桥接功能
- **吸收其工具设计**：server.py 的 IPC 方法可参考这 4 个工具的职责划分（health/recognize/run/list_nodes）
- **剥离硬编码**：所有 `/home/ubuntu/.hermes/` 路径需移除

### 2.4 前端 DreamOS 桥

**源文件**:
- `src/lib/dreamos/bridge.ts`：决策是否走 DreamOS 物理编排（feature flag 默认关）
- `src/lib/dreamos/intent-canon-map.ts`：正典 → DreamOS 6 策略意图映射
- `src/lib/dreamos/client.ts`：HTTP 客户端，AbortController 超时
- `src/app/api/dreamos/route.ts`：Next.js API route

**技术价值**:
- **intent-canon-map.ts**：保守可审计的映射表，仅 intelligence 环分析型意图过桥；execution/governance 环一律不过桥
- **bridge.ts**：feature flag 灰度安全，`DREAMOS_BRIDGE_ENABLED=true` 才启用
- **client.ts**：async/sync 双模式（生产走 async + 轮询，sync 仅降级兜底）

**对 Harness 的迁移建议**:
- **client.ts 可复用**：Harness agent loop 可通过此客户端直接调用 DreamOS api_server
- **bridge.ts 的 feature flag 模式可借鉴**：Harness 接入 DreamOS 时同样应灰度切流
- **intent-canon-map.ts 直接复用**：正典 → DreamOS 6 策略意图映射，与 Hermes 零耦合

---

## 3. Hermes 遗留剥离清单

### 3.1 必须剥离（P0 — 架构一致性）

| 文件 | Hermes 遗留点 | 处理方式 |
|---|---|---|
| `dreamos/apps/dreamos_mcp_server.py` | 文件头、硬编码路径、注册方式 | **废弃此文件**，由 dream-harness-bridge/server.py 取代 |
| `dreamos/core/sense/complexity_classifier.py` | T3 描述"委托 Hermes 深度分析"、mode=`delegate_hermes` | 改为"委托 Harness 深度分析"、`delegate_harness` |
| `dreamos/docs/PHASED_DIALOGUE_MODE.md` | "Hermes 呈现规范"章节 | 改写为"Harness 呈现规范" |
| `3-EVOLUTION/proposals/PROP-20260829-hermes-drives-dreamos*.md` | 整份方案基于 Hermes | **废弃**，由本 SPEC 取代 |

### 3.2 可暂缓（P1 — 部署侧，不影响本地开发）

| 文件/目录 | 说明 |
|---|---|
| `deploy/hermes/` 整个目录 | 生产服务器的旧 Hermes 网关部署包，本地开发不影响 |
| `deploy/ops/com.dreambuddy.hermes_*.plist` | 三个 launchd 服务（gateway/dashboard/group_poller） |
| `1-ARCHITECTURE/README.md` | 提到 "Hermes 网关部署"、"Hermes 配置包" |
| `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` | "Dream Bot + Hermes Bot" 双 bot 架构 |

### 3.3 剥离原则

1. **只剥离 Hermes 包装，保留技术内核**：意图识别管线、复杂度分级、渐进式编排等纯技术资产与 Hermes 解耦，可直接迁移
2. **dream-harness-bridge 已有等效实现**：dreamos_mcp_server.py 的 4 个工具职责已由 python-server/server.py 的 IPC 方法覆盖
3. **提案文档废弃不删**：`PROP-20260829-hermes-drives-dreamos*.md` 保留作为历史记录，但标注"已被 SPEC_INTENT_DREAMOS_OPTIMIZATION.md 取代"

---

## 4. 整合路径建议（评估，不含实施）

### 4.1 意图识别层整合

**现状**: 前端有 4 套互不兼容的意图实现（chat 内联 9 意图 / fallback-engine 15 / llm-planner 5(FC) / clarification-engine）

**PR68 的统一方案**: intent-unified.ts 四级管线 + intent-schema.ts 35 型正典，单一入口识别

**Harness 架构下的整合路径**:

```
用户对话（前端 UI）
    ↓ 自然语言
Harness agent loop（取代 Hermes）
    ↓ 调用意图识别 tool（Cordis plugin）
intent-unified.ts 四级管线（TS 侧保留）
    ↓ 返回 UnifiedIntentResult（35 型正典 + 环归属 + 角色门禁）
Harness 决策：走 DreamOS 物理编排 or 直答
    ↓ intent-canon-map.ts 映射（intelligence 环过桥）
DreamOS IPC（python-server/server.py）
    ↓ phase 参数（复杂度分级决定）
GraphPlanner 渐进式编排
```

**关键决策点**:
1. **intent-unified.ts 保留在 TS 侧**：作为 Harness 的 Cordis plugin tool，不迁移到 Python
2. **正典 35 型作为 SSoT**：Harness agent loop 和 DreamOS 都引用此正典
3. **影子探针模式复用**：Harness 接入 DreamOS 时采用同样的灰度切流策略

### 4.2 DreamOS 优化整合

**复杂度分级器**: 直接复用，T3 委托对象从 Hermes 改为 Harness

**渐进式编排**: Harness 调用 DreamOS IPC 时传 `phase` 参数
- T0 → 不调用 DreamOS，Harness 直答
- T1 → phase=1 轻量首答
- T2 → phase=None 完整编排
- T3 → Harness 委托 A 系列深度分析（phase=None）

**对话模式**: "先呈现后追问"规范从 Hermes 呈现规范改写为 Harness 呈现规范
- 先呈现：action/confidence/rationale 直接给用户
- 后追问：响应含 `next_step_hint` 时附深化引导
- 不越权：`deferred_nodes` 是"可选深化项"，不是"缺失项"

### 4.3 评估结论

| 评估维度 | 结论 |
|---|---|
| 意图识别管线可复用性 | ⭐⭐⭐⭐⭐ 与 Hermes 零耦合，直接迁移 |
| 复杂度分级器可复用性 | ⭐⭐⭐⭐⭐ 仅改 T3 委托对象 |
| 渐进式编排可复用性 | ⭐⭐⭐⭐⭐ phase 参数与 Hermes 无关 |
| 影子探针模式可复用性 | ⭐⭐⭐⭐⭐ 灰度切流通用模式 |
| 前端桥可复用性 | ⭐⭐⭐⭐ client.ts + intent-canon-map.ts 直接复用 |
| MCP Bridge 可复用性 | ⭐⭐ 剥离 Hermes 后由 dream-harness-bridge 取代 |
| 工程化质量 | ⭐⭐⭐⭐⭐ 黄金集 + 影子探针 + 审计痕迹 + FAIL-OPEN |

**总体结论**: PR68 的意图识别和 DreamOS 优化技术内核是高质量工程资产，与 Hermes 解耦后可直接服务于 DeepSeek Harness 架构。建议采纳本 SPEC 评估的技术内核，废弃 Hermes 驱动方案。

---

## 5. 不做范围

- 不在本 SPEC 中实施代码（用户明确要求"先评估"）
- 不动 cron/:30 自动交易循环（独立泳道）
- 不修改 `deploy/hermes/` 部署包（P1 暂缓）
- 不处理 `6-TRADING` AI 理论架构（并行代理域，0 触碰）

---

## 5.5 意图识别实现全景与职责边界

意图识别在系统中存在**三套独立实现**，各自负责不同场景，通过映射表桥接：

| 实现 | 位置 | 识别体系 | 触发场景 | 识别策略 |
|------|------|---------|---------|---------|
| **前端四级管线** | `3-FRONTEND/.../intent/intent-unified.ts` | 35 型正典 | 前端用户对话入口 | 追问 → 快路径 → LLM(FC) → 规则 → 默认兜底 |
| **DreamOS IntentEngine** | `dreamos/core/sense/intent_engine.py` | 7 型策略意图 | TradingAgent 内部 S 层 | 规则 + LLM + 动态识别器 + 复杂度分级 |
| **桥接层算法层** | `dream-harness-bridge/.../algorithm_server.py` | 7 型（仅规则） | AlgorithmEnhancedAgent 短路预识别 | RuleBasedRecognizer + 复杂度分类 |

**数据流**：

```
用户输入
  │
  ├─ 前端 TS 四级管线 → 35 型正典
  │     └─ canonToDreamOS() → 7 型策略意图 → bridge.ts 过桥（feature flag 控制）
  │
  ├─ AlgorithmEnhancedAgent（Harness 侧）
  │     └─ AlgorithmLayerBridge（IPC 子进程）→ 7 型（仅规则）
  │           └─ 置信度 ≥0.70 → 构造 intent_hint → TradingAgent.run()
  │           └─ <0.70 或 degraded → 走现有链路
  │
  └─ TradingAgent 内部
        └─ IntentEngine → 7 型（规则+LLM+复杂度）→ GraphPlanner 编排
```

**桥接映射**（前后端镜像，有 assert 自检）：
- `CANON_TO_DREAMOS`：35 型 → 7 型（前端 `intent-schema.ts` + 后端 `canon_intent_bridge.py`）
- `KERNEL_TO_CANON`：6×30 二级意图 → 35 型（取代表）
- `CanonNLPRecognizer`：35 型关键词识别，修复 7→35 多对一信息损失

**FAIL-OPEN 铁律**：桥接层（AlgorithmLayerBridge）任何异常 → `degraded=True` → 走现有链路，绝不阻塞交易热路径。

---

## 5.6 /intent/route 端点说明

**位置**：`6-TRADING/bridge/api/intent_router_api.py`，在 `run_api_server.py` 的 `create_enhanced_app()` 中注册为 `intent_bp` Blueprint（`url_prefix='/intent'`），HC-1a 合规（不修改 dreamos/apps/api_server.py）。

**端点列表**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/intent/route` | 单条意图路由主入口 |
| POST | `/intent/batch` | 批量意图路由 |
| GET | `/intent/examples` | 获取各意图示例 |

**POST /intent/route**：

请求体：
```json
{
  "text": "分析BTC趋势",
  "use_engine": false
}
```
- `text`/`message`/`input`：用户输入（必填，三选一）
- `use_engine`：可选，`true` 时调用 `IntentRecognitionEngine` 返回三层完整输出（Objective+OKRSet+Blueprint+canon_type），引擎失败时 FAIL-OPEN 回退到正则结果

响应体（核心字段）：
```json
{
  "success": true,
  "user_input": "分析BTC趋势",
  "intent": {
    "primary_intent": "deep_analysis",
    "canon_intent": "deep_analysis",
    "legacy_intent": "market_analysis",
    "confidence": 0.6,
    "skills": ["A1", "A2", "regime"]
  },
  "extracted": { "symbol": "BTC-USDT-SWAP", "direction": null },
  "routing": {
    "primary_skill": "A1",
    "suggested_action": "建议执行 A1调研 + A2第一性原理 分析"
  }
}
```

**意图体系**：内部维护 9 个 `INTENT_PATTERNS`（market_analysis/trade_execution/risk_control 等），每个模式含 `canon_intent` 字段映射到 35 型正典。`primary_intent` 输出 35 型正典值，`legacy_intent` 保留旧 9 型键兼容旧消费方。

---

## 6. 关联文档

- [SPEC.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/SPEC.md) — dream-harness-bridge 总体规范
- [SPEC_INFRASTRUCTURE_INTEGRATION.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/SPEC_INFRASTRUCTURE_INTEGRATION.md) — 基础设施集成规范
- PR68 源文件（pr-68 分支）：
  - `intent-schema.ts` / `intent-unified.ts` / `command-fastpath.ts` / `intent-args-repair.ts` / `shadow-probe.ts`
  - `complexity_classifier.py` / `graph_planner.py` / `types.py` / `api_server.py`
  - `bridge.ts` / `intent-canon-map.ts` / `client.ts` / `route.ts`
  - `PHASED_DIALOGUE_MODE.md` / `_plan/z1-z4*.md`
- 废弃提案（保留作历史记录）：
  - `PROP-20260829-hermes-drives-dreamos.md`
  - `PROP-20260829-hermes-drives-dreamos-P1-validation.md`
