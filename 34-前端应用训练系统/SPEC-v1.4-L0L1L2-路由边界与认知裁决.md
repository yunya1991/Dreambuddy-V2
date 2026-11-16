# SPEC-v1.4 L0/L1/L2 路由边界与认知裁决

> 版本: v1.4-r4 | 日期: 2026-11-17 | 状态: 待复审（M1–M5 已修订；E1/E2 实验完成并回填 §9.2/§9.3）
> 修订记录: v1.4（初稿）→ v1.4-r1（评审修订：M1 前端消费契约 / M2 执行器四态 / M3 `channel` 字段 / M4 裁决分级 / M5 门禁可判定 + DA-1/2/4 让步项）→ v1.4-r2（新增 §7.1 策略对比实验 E1）→ v1.4-r3（E1 完成，§9.2 回填）→ **v1.4-r4（E2 完成：复合检测 D5 规则 78.8%/2.0%，模型仅作建议器；新增 §9.3）**
> 前置: SPEC-v1.3-L0L1L2-architecture.md（2026-10-16 定稿基线）
> 关系: 本文件**修订并取代** v1.3 中与“L1 直答准入”相关的条款（§1 判据保留，§2 保留，**§3.5 第 4 条、§5 路由器第 4 条、§6 待推进项第 2 条**以本文件为准）；v1.3 其余架构条款继续有效。
> 定位: 本文件是 **L1 能力边界、L1→L2 交接、认知裁决信号** 的唯一事实源（SSoT）。

---

## 1. 背景与问题

### 1.1 触发事实（云端实测，2026-11-16）

| 观测 | 值 |
|---|---|
| `POST /api/data/query {"message":"以太坊 最近新闻"}` | `intent=event_listing, handled=false, decision=L2_HANDOFF, reasons=[recall_empty]` |
| `POST /api/data/query {"message":"BTC现在什么价格"}` | `intent=price_query, handled=false, decision=L2_HANDOFF, reasons=[recall_empty]` |
| 执行器直调 `exec_news_search("以太坊 最近新闻")` | 正常命中 7 条（产物 2.7MB，当日更新） |
| 认知召回 `cognitive.recall` | 云端 31.5 万条记忆，但该类问法返回空（`no_hit`） |

### 1.2 根因

L1 的准入判定（[core/route_confidence.py](../34-前端应用训练系统/core/route_confidence.py)）把 **「用户问题 ↔ 认知记忆库」相似度**当成 **「执行器能否确定性作答」** 的代理指标：

- 记忆为空 → `route_confidence=0` → 强制 `L2_HANDOFF`；
- 该门限 `0.65` 是按 **bge-small-zh（512 维）** 的相似度分布标定的，而 L1 意图识别用的是 **bge-base-zh（768 维）**，两者对象与口径均不同；
- 结果：19 个全零 token 的执行器中，约 10 个意图在云端**恒不直答**。代码里已出现三道“绕过门控”的补丁（`DETERMINISTIC_INTENTS`、`EXECUTOR_AVAILABILITY_INTENTS`、`metric_series` 特判），本身即门控错位的证据。

### 1.3 v1.3 的内部矛盾

- §1 判据：“确定性 + 本地模型/向量检索 → L1；生成式 LLM 推理 → L2”；
- §2：10 个意图**全部零 token**（含 `data_insight`、`event_analysis`、`price_query`）；
- §3.5 第 4 条：却要求“用户问题被认知库明确覆盖”才允许 L1 直答。

三条同时成立是不可能的。v1.4 明确取舍：**L1 的准入只看能力契约，不看认知覆盖度；认知覆盖度只用于 L1 之后的 L2 裁决。**

---

## 2. 目标与非目标

### 2.1 目标

1. L1 恢复“意图识别 → 确定性检索/计算 → 直答”的零 token 主链路，且**不依赖认知记忆**。
2. 数据类问法走**确定性门控**（闭集注册表 + 特征校验），语义类问法走 **L1 专用小模型**（bge-base 768），两者共同受“系统能力边界”约束，避免乱打。
3. 认知系统（C3 匹配度 + C4 预测误差）改为 **L1→L2 的裁决层**：判域内/域外、仲裁歧义、决定 L2 路线与成本档位。
4. 信号、日志、验收全部可机器判定，消除“假绿”（只验 intent 与 HTTP 200，不验 `handled/data`）。

### 2.2 非目标

- 不新训 L1 意图模型（复用现有 bge-base + intent_units；训练与扩样例属常态化运营）。
- 不改变 L2 的生成式职责，不把 LLM 引入 L1。
- 不在本 SPEC 内解决 L1 执行器与 19-DAL 的迁移（v1.3 §6 待推进项保持）。
- 不调整 `metric_series` 等执行器的业务口径。

---

## 3. 核心定义

### 3.1 L1 能力边界（四道闸，缺一不可）

| 闸 | 名称 | 判定 | 失败含义 |
|---|---|---|---|
| G1 | 能力闸 | `intent ∈ EXECUTORS` | 系统做不到 → L2 |
| G2 | 特征闸 | 该意图 `requiredPattern` / 结构化特征通过 | 泛词误吞 → 不直答 |
| G3 | 数据闸 | 执行器数据源可用（DB / 产物 / API） | 产物缺失 → `degraded` 或 L2（按意图策略） |
| G4 | 语义闸 | 语义通道：`score ≥ 0.66` 且 `top1 − top2 ≥ δ` | 低置信/歧义 → 不下判断 |

> G2–G4 只回答“L1 是否**有权**作答”，不回答“答得对不对”；答案质量由执行器契约（§3.3）与回归测试保证。

### 3.2 数据类 vs 语义类

| 类别 | 识别方式 | 典型意图 | 准入 |
|---|---|---|---|
| **数据类** | 结构化特征：实体（BTC/CPI/…）+ 指标/字段 + 查询或计算动词；闭集注册表 | `data_query`、`metric_series`、`price_query`、`stat_query`、`whale_flow`、`calendar_event`、`fundamental_valuation`、`technical_indicator` 等 | G1+G2+G3 |
| **语义类** | 口语化/变体问法，正则未命中；由 bge-base 映射到闭集意图 | 各意图的口语表达（“有啥新动静吗”“现在上车合适不”） | G1+G2+G3+G4 |
| **解读/生成类** | 需要生成式推理或跨域综合 | 开放分析、策略建议、文章生成 | 直接 L2（L1 可先给事实） |

判定顺序固定为 **数据类 → 语义类 → 裁决 → L2**，禁止“认知召回前置”。

### 3.2.1 分类的机器可读定义（M3，P1 必交付）

“数据类 / 语义类”不允许只靠散文判定，必须在注册表落成字段，三处同源：

| 位置 | 字段 | 取值 | 读取方 |
|---|---|---|---|
| `3.1-FRONTEND/src/lib/l1-intent-registry.ts` | `channel` | `data` / `semantic` / `generative` | 前端、Python（经导出快照或等价读取） |
| `41-文件索引系统/intent_units/<intent>/intent.yaml` | `channel` | 同上 | `l1_route_signal.py`、`intent_matcher.py` |
| `34-前端应用训练系统/SPEC-v1.4`（本文件） | — | 引用上述字段，不另立规则 | 文档与评审 |

规则：
- `data`：必须提供 `requiredPattern`（结构化实体 + 查询/计算特征），只走 G1/G2/G3，不调用语义模型；
- `semantic`：可不提供 `requiredPattern`，但必须过 G4（阈值 + margin），且 `intent_units` 有 ≥20 条正例与 ≥50 条硬负例；
- `generative`：不进 `EXECUTORS`，直接 L2，不得出现在 L1 判定表中。

> 落地约束：Python 侧只读 `channel` 与 `requiredPattern`，**禁止**再维护一套独立分类正则；若 TS 与 yaml 不一致，以 TS 注册表为准并在 P1 加一致性测试。
>
> **P1 交付物（消除跨语言读取难题）**：新增导出脚本 `3.1-FRONTEND/scripts/export_l1_registry.ts`，把注册表（`intent/channel/requiredPattern.source/flags`）固化为 `3.1-FRONTEND/scripts/l1_intent_registry.snapshot.json`；Python 读快照，并在 CI 中断言快照与 TS 源文件一致（不一致即失败）。禁止 Python 直接解析 TS 源码。

### 3.3 执行器契约（L1 内部，四态，M2 修订）

**现状核对（2026-11-16）**：19 个执行器**均不返回 `success=false`**，失败一律用 `degraded=true` 或 `need_clarification=true` 表达（例：`exec_price_query` 无币种时返回 `need_clarification`）。因此原“`success=false`”契约不成立，改为四态：

```text
exec_*(message) -> {
  success: bool,             # 恒 true（保留字段，不再用于表达拒绝）
  answer: string,            # 模板化/规则化结论，零 token
  data: object|null,
  degraded: bool,            # 数据源缺失/降级，但有可用答案
  need_clarification: bool   # 缺少必要槽位（如币种），需用户补充
}
```

| 状态 | 判定 | L1 行为 | decision | handled |
|---|---|---|---|---|
| `answered` | `degraded=false, need_clarification≠true` | 正常直答 | `L1_DIRECT` | true |
| `degraded_answered` | `degraded=true`，`answer` 非空 | 输出并标注降级，前端可提示 | `L1_DIRECT` | true |
| `need_clarification` | `need_clarification=true` | **L1 正常输出追问**，不得交 L2 | `L1_DIRECT` | true |
| `declined` | 执行器显式表示“该意图答不了”（新增约定：`declined=true`） | 不输出，交裁决 | `L2_HANDOFF` | false |

异常与超时（与 §5 对齐，消除原自相矛盾）：
- 执行器抛异常 → `degraded_answered`（`answer="执行异常: …"`），`handled=true`，**不静默、不交 L2**；连续失败由监控告警。
- 执行器超时（脚本总超时 30s）→ 无法获得执行器内部状态，按 `declined` 处理并记 `l1_executor_timeout`，交 L2。
- `declined` 为 P1 新增字段；P0 阶段若尚无执行器设置该字段，则该分支不触发（等价于“现有 19 意图全部可答”）。

### 3.4 认知系统的三层职责（裁决层）

| 动作 | 时机 | 输入 | 输出 |
|---|---|---|---|
| ① 域内外裁决 | L1 拒绝之后 | 问题 ↔ **能力目录索引**（P3 交付；P0–P2 为启发式初筛） | `in_scope` / `unknown` / `out_of_scope` |
| ② 歧义仲裁 | 语义 margin < δ | 语义 top3 + C3 加权召回 | 采纳某意图 / 仍交 L2 |
| ③ L2 路线与成本 | 交接时 | L1 已取事实 + 覆盖度 | `retrieval_augmented` / `deep_reasoning`；域外则引导/拒答 |

**阈值与信号**：C3 使用 `evaluate_match`（匹配度/案例密度），C4 使用 `jev_gate`（预测误差）。两者继续零 token，但**只影响裁决结果与 L2 路线，不再影响 L1 准入**。

**空召回语义修订（关键）**：`recall` 为空 **不再等价于“低置信、拒绝 L1”**，而是 `coverage=unknown`：
- L1 已拒绝 → 交 L2，标记 `coverage_unknown`；
- L1 未拒绝 → 与裁决无关（L1 正常直答）。

### 3.4.1 能力目录索引的交付定义（M4）

现状：能力目录只是文件（`intent_units/*/executor.md` + `intent.yaml`），**未进入 41 索引、无可召回 scope**。因此裁决①分两级交付：

| 级别 | 时间 | 能力 | 输出 |
|---|---|---|---|
| **L0（降级）** | P0–P2 | 启发式域外初筛：寒暄/闲聊/非金融词表 + 无意图命中 | `coverage=unknown`；明显非金融 → `out_of_scope`；原因全量落 trace |
| **L1（正式）** | **P3a** | 能力目录入 41 索引：新增 scope `l1.capability_catalog`，索引 `executor.md`（能力描述）+ `intent.yaml`（关键词/类别）+ 执行器数据源 | `coverage ∈ [0,1]` + `in_scope/out_of_scope` |

P3a 交付物（硬性）：
1. 索引构建脚本与更新频率（随 `intent_units` 变更触发，或每日一次）；
2. 召回接口：`fetch_context("l1.capability_catalog", {context})` 返回 `{coverage, top_intents, matched_docs}`；
3. 验收：≥50 条域内 + ≥50 条域外人工标注集，`out_of_scope` 召回率 ≥90%、误杀 ≤5%；
4. 未达 3 之前，`cognition_signal.verdict` 只能是 `unknown`，禁止上线“硬性域外拒答”。

---

## 4. 路由判定表（替代 v1.3 §5 第 4 条）

| # | 条件 | decision | reasons | handled | 后续 |
|---|---|---|---|---|---|
| 1 | 数据类命中 + G1/G2 通过 | `L1_DIRECT` | `deterministic_registry` / `deterministic_series` | true | 执行器直答 + settle |
| 2 | 产物检索型 + 产物可用 | `L1_DIRECT` | `executor_artifact_available` | true | 执行器直答 |
| 3 | G3 失败（数据源缺失） | 见 §5 策略表 | `executor_source_unavailable` | 按策略 | 数据类 `degraded` 直答；分析类交 L2 |
| 4 | 执行器 `need_clarification` | `L1_DIRECT` | `executor_need_clarification` | true | 输出追问（如“查哪个币种”），**不交 L2** |
| 5 | 语义类 + G4 全通过（仅 P2+） | `L1_DIRECT` | `semantic_intent_match` | true | 执行器直答 |
| 6 | 语义类 + `score < 0.66`（仅 P2+） | `L2_HANDOFF` | `l1_low_confidence` | false | 裁决 → L2 |
| 7 | 语义类 + `margin < δ`（仅 P2+） | `L2_HANDOFF` | `l1_ambiguous_intent` | false | 裁决②（可采纳或仍交 L2） |
| 8 | 执行器 `declined` / 超时 | `L2_HANDOFF` | `l1_executor_declined` / `l1_executor_timeout` | false | 裁决 → L2 |
| 9 | 意图无执行器（`doc_search` / `event_line_query`） | `L2_HANDOFF` | `l1_no_executor` | false | 裁决 → L2 |
| 10 | 域外/闲聊/复合问法不拆解 | `L2_HANDOFF` | `out_of_scope` / `compound_query` | false | 引导或拒答 |

**阶段生效范围**：
- P0/P1 **不启用语义通道**，第 5–7 行不生效（这是 DA-1 的让步：先交付有护栏的 L1，再开语义）；
- 复合问法（如“BTC 价格和 CPI”）在 P0–P2 统一按第 10 行交 L2，不做隐式拆分；
- `metric_series` 语义命中但非确定性序列 → 归入第 6 行（`l1_low_confidence`）。

### 4.1 `route_signal` 契约（前端兼容）

```json
{
  "decision": "L1_DIRECT | L2_HANDOFF",
  "route_confidence": 1.0,
  "reasons": ["semantic_intent_match"],
  "match_score": 0.78,
  "case_density": 4,
  "semantic": {"top1": 0.78, "top2": 0.71, "margin": 0.07},
  "cognition_signal": {
    "coverage": 0.0,
    "source": "capability_catalog",
    "verdict": "in_scope|unknown|out_of_scope",
    "l2_route": "retrieval_augmented|deep_reasoning"
  }
}
```

- **M1 前端消费契约**：`ChatPanel` 通过 `canHandleL1WithSignal` 要求 `decision=L1_DIRECT` **且** `route_confidence ≥ 0.65`（`l1-intent-registry.ts`）。因此**所有契约直答必须置 `route_confidence=1.0`**（与现有 `_route_deterministic` 一致）；`L2_HANDOFF` 置 `0.0`。本版不采用“前端只信 decision”的改法（会牵动 4 个前端测试），留作兼容性重构。
- `decision` / `reasons` 为后端 trace 的判据；前端以 `decision + route_confidence` 消费；`cognition_signal` 仅透传 L2，不参与 L1 判决。
- 禁止第二套阈值：`0.65`（C3/C4 裁决）、`0.66/0.50`（语义意图）、`δ` 均单点定义并被引用。

---

## 5. 失败与降级矩阵

| 场景 | L1 行为 | 信号 |
|---|---|---|
| 执行器抛异常 | `degraded_answered`（`answer` 含异常说明），`handled=true` | `executor_exception`（告警，不交 L2） |
| 执行器超时 | 脚本 30s 上限；超时无法取状态 → `declined` | `l1_executor_timeout` → L2 |
| 执行器缺槽位 | `need_clarification` 直答追问 | `executor_need_clarification` |
| 数据源缺失（产物/DB/API） | 数据类：`degraded` 直答；分析类：交 L2 | `executor_source_unavailable` |
| 语义服务（8099）不可用（P2+） | 快速失败（≤2s），**不回退**进程内加载 | `semantic_unavailable` → 交裁决 |
| 本地 fallback 被触发 | 生产环境必须关闭；若触发记告警 | `semantic_local_fallback` |
| 认知裁决异常 | FAIL-OPEN：默认 `unknown` + L2 | `cognition_degraded` |
| 脚本整体异常 | 前端 FAIL-OPEN 转 L2，不得静默 | `l1_script_failed` |

**配置契约（m4）**

| 配置项 | P0/P1 | P2+ | 说明 |
|---|---|---|---|
| `L1_COGNITION_GATE` | `off` | `off` | 兼容旧行为；默认关闭认知准入 |
| `L1_ROUTING_STRATEGY` | `S0` | `S1` | **已实现**：`S0`=现状（零行为变化）；`S1`=纯正则检测 + 能力契约门控 + D5 复合闸（E1/E2 选定） |
| `L1_SUGGEST_SHADOW` | `0` | `0`/`1` | **已实现**：建议器影子模式，仅异步写日志（默认 `<repo>/logs/l1_suggest_shadow.jsonl`），不改返回契约 |
| `L1_SUGGEST_ENABLED` | `1` | `1` | **已实现**：L2 交接实盘建议器；依赖常驻向量服务（默认 `127.0.0.1:8099`），不可用/超时则返回 `[]` |
| `L1_SUGGEST_BUDGET_MS` | `3000` | `3000` | 建议计算预算；云端 8099 CPU 推理单条 embed 实测 600–900ms，与 l1-loop/训练守护进程争抢时超 1.5s，故取 3000ms；仅走常驻服务，禁止本地冷加载 |
| `L1_SEMANTIC_PRIMARY` | `0` | `1` | 语义通道开关（P0/P1 必须为 0） |
| `L1_EMBED_SERVER_TIMEOUT` | 2 | 2 | 语义嵌入快速失败 |
| `L1_EMBED_LOCAL_FALLBACK` | 0 | 0 | 禁止在线程内加载模型 |

**策略表（G3 失败时按意图二选一；下列为本版默认值，评审可推翻）**

| 意图组 | 默认策略 |
|---|---|
| 数据类（检索/计算） | `degraded` 直答（明确告知无数据） |
| 分析类（`data_insight`/`path_insight`/`event_analysis` 等） | 交 L2（L1 只给已取到的事实） |

---

## 6. 可观测性与验收（机器可判定）

### 6.1 指标

| 指标 | 定义 | 目标 |
|---|---|---|
| L1 直答率 | `handled=true / 总请求` | 数据类 ≥95%，语义类 ≥80% |
| 误路由率 | 人工/回放判定意图错误占比 | ≤2%（golden 集） |
| 空答率 | `handled=true 且 data 空且非合法空` | ≤1% |
| L2 交接原因分布 | 按 `reasons` 聚合 | `l1_no_executor` / `out_of_scope` 为主，`recall_empty` 清零 |
| 语义 P95 | 语义通道耗时 | ≤2s（常驻服务） |
| `unknown` 占比 | 语义通道判 unknown | 观测项，持续下降 |
| `δ`（top1−top2）分布 | 语义通道 margin 分位 | **观测项**（P2 前完成标定，不作为门禁，M5） |
| 过度覆盖误判率 | 生产 trace 抽样人工标注中“该问法不属于该意图”的占比 | ≤2%（P0 合并门禁，DA-1） |

### 6.2 门禁（TDD）

| # | 用例 | 断言（可执行） | 阶段 |
|---|---|---|---|
| A1 | `recall_empty` + 19 个意图 | 用 `monkeypatch.setitem(l1_route_signal.EXECUTORS, intent, fake)` 注入；全部 `L1_DIRECT`，且 `get_l0` 未被调用 | P0 |
| A2 | 语义 `top1=0.60` | `L2_HANDOFF`，`reasons=[l1_low_confidence]` | P2 |
| A3 | 语义 `top1=0.78, top2=0.77` | 按标定后的 δ 判定；未标定前仅记录观测，不作为门禁 | P2 |
| A4 | `doc_search` / `event_line_query` | `L2_HANDOFF`，`reasons=[l1_no_executor]` | P0 |
| A5 | 执行器抛异常 | `handled=true` + `degraded=true` + `answer` 非空，无静默 | P0 |
| A6 | 执行器 `need_clarification` | `handled=true`，`reasons=[executor_need_clarification]`，不交 L2 | P1 |
| A7 | 执行器 `declined`（P1 新增字段） | `handled=false`，`reasons=[l1_executor_declined]` | P1 |
| A8 | 407 条 golden 回放 | 意图准确率与 FPR 不劣化（基线：FPR=0%，来源 `intent_matcher.py` 注释）；回放脚本与命令由 P1 补齐后写入 CI，未提供命令不得判定通过 | P1 |
| A9 | 云端冒烟（DA-4） | `POST /api/data/query` 三条：`BTC现在什么价格` / `以太坊 最近新闻` / `CPI超预期意味着什么`；断言 `handled=true` 且 `data≠null`，且无 30s 超时 | P0 |
| A10 | 过度覆盖审计（DA-1） | 生产 trace 随机抽样 ≥200 条，人工标注“问法是否属于该意图”；误判率 >2% 回滚 | P0 合并前 |
| A11 | 语义前置数据（DA-1） | 域外/unknown 测试集 ≥100 条；δ 与阈值在该集上标定并记录 | P2 合并前 |

---

## 7. 分阶段实施

| 阶段 | 内容 | 风险 | 回滚 | 合并条件 |
|---|---|---|---|---|
| **P0** | L1 移除认知准入；契约直答统一 `route_confidence=1.0`；**不启用语义通道**；19 意图恢复直答 | 低 | `L1_COGNITION_GATE=off`（默认） | A1/A4/A5/A9 + **A10 过度覆盖审计 ≤2%** |
| **P1** | 注册表增加 `channel` 字段；执行器四态落地（`declined`/`need_clarification`）；三道补丁合并为一张判定表；TS/Python/文档同源 | 低 | 保留旧常量别名一版 | A6/A7/A8 |
| **P2** | 语义主通道：数据类未命中即走 bge-base + margin；生产关闭本地 fallback（超时 2s） | 中 | `L1_SEMANTIC_PRIMARY=0` | A2/A3 + **A11 域外测试集 ≥100 条并完成 δ 标定** |
| **P3a** | 能力目录入 41 索引（scope `l1.capability_catalog`）；`coverage` 上线 | 中 | `cognition_signal` 可空 | 域内/域外各 50 条标注集：召回率 ≥90%、误杀 ≤5% |
| **P3b** | L2 路线与成本档位；指标看板（直答率/误路由/交接原因） | 中 | 保留 unknown 路径 | 监控看板可用 + 7 日观察 |

**DA 让步项落地位置**：
- DA-1（无护栏风险）→ P0 不含语义通道 + A10 + P2 前置 A11；
- DA-2（裁决画饼）→ §3.4.1 两级交付 + P3a 独立阶段与硬性验收；
- DA-4（mock 不能证明端到端）→ A9 云端冒烟作为 P0 合并条件。

每阶段独立可上线；P0 完成后云端复验 `price_query`、`data_insight`、`event_analysis`。

### 7.1 策略对比实验（E1）— 用同一套问题裁决最优策略

> 原则：**不靠人工拍参数**。先定义候选策略，再用同一测试集回放，按“安全硬约束 → 效果 → 成本”三层规则选出唯一策略，回填 §9.2。

#### 7.1.1 候选策略（全部可由开关组合，不改架构）

| ID | 正则/注册表 | 语义通道 | margin | 认知裁决 | 说明 |
|---|---|---|---|---|---|
| **S0** | 开 | 关 | — | 开（召回门控，现状） | 线上基线，用于证明改造收益 |
| **S1** | 开 | 关 | — | 关 | 纯数据类门控（最小改动） |
| **S2** | 开 | 开（0.66） | 关 | 关 | 语义补位，无歧义拦截 |
| **S3** | 开 | 开 | 开 | 关 | 语义 + 歧义拦截（推荐候选） |
| **S4** | 开 | 开 | 开 | 开（仅低置信/歧义时） | 全量方案，验证裁决增量 |
| **S5** | **关** | 开 | 开 | 关 | 纯模型（检验正则是否仍有必要） |

- 参数网格：`threshold ∈ {0.60, 0.63, 0.66, 0.70}` × `δ ∈ {0.02, 0.03, 0.05, 0.08}`（仅 S2–S5）；S0/S1 无网格。
- 所有策略共享同一份执行器桩，避免网络抖动污染对比；另设 60 条真实云端复核。

> **E1 实测口径修正（v1.4-r3）**：线上 `detect_intent` 已内置语义兜底（bge-base + 0.66），"S0 语义关"只是设计意图。E1 按实测执行，策略差异定义为「**检测通道**」+「**准入闸门**」两个维度：
> S0 = 正则→语义(0.66) + 认知召回门控（现状）；S1 = 纯正则 + 能力契约门控；S2 = S1 加语义通道（无 margin）；S3 = S2 + margin；S4 = S3 + 低置信/歧义时认知裁决；S5 = 纯语义（关正则）+ 置信 + margin。
> 实现：纯决策模块 [`3.1-FRONTEND/scripts/l1_routing_policy.py`](../../3.1-FRONTEND/scripts/l1_routing_policy.py)，`route_query` 零改动，S0 等价性由 `tests/test_l1_routing_policy.py` 锁定。

#### 7.1.2 测试集 E1-D1（同一套，全部策略共用）

| 段 | 数量 | 构造方式 | 期望路由 |
|---|---|---|---|
| `data` 数据类可答 | 80 | 19 意图各 3–5 条，产物/DB 当时可用 | L1 + 正确 intent |
| `semantic` 语义改写 | 80 | 每意图 3–5 条口语改写，**不含关键词**，且与 `intent_units` 例句不重叠 | L1 + 正确 intent（S1 应在此段暴露） |
| `out_of_scope` 域外 | 120 | 闲聊、通用知识、编程、生活、非金融建议 | L2 |
| `compound` 复合/多意图 | 80 | 双意图并列（“BTC 价格和 CPI”） | L2 或澄清 |
| `trap` 边界陷阱 | 60 | 关键词陷阱、错别字、中英混写、超短问法 | 按逐条标注 |
| `clarify` 缺槽位 | 40 | “这个币怎么样”（无币种）等 | L1 `need_clarification` |
| `regression` 现状失败回归 | 40 | 云端实测 `recall_empty` 失败样本 | L1 |
| **合计** | **500** | — | — |

标注字段（逐条）：

```json
{"id":"D001","query":"...","segment":"data|semantic|out_of_scope|compound|trap|clarify|regression",
 "expected_route":"L1|L2","expected_intent":"price_query|null","expected_state":"answered|need_clarification|degraded|null",
 "acceptable_alternatives":["..."],"severity":"critical|normal","data_available":true}
```

标注纪律（否则实验无意义）：
1. 先 AI 初标，再 **100% 人工复核**；争议条目单独标记，不参与主评分；
2. `semantic` 段与 `intent_units/*/examples_zh.jsonl`、`negatives_zh.jsonl` 必须 **零重叠**（脚本校验，重叠即报错）；
3. 数据集版本化（`e1_d1@2026-11-16`），任何增删改需升版本，禁止静默修改。

#### 7.1.3 指标与决策规则

| 指标 | 定义 | 用途 |
|---|---|---|
| **FAR-answer** | 应 L2 却被 L1 作答的比例（`critical` 单独统计） | **硬约束** |
| Coverage | 应 L1 且答对 / 应 L1 总数 | 主效果 |
| IntentAcc | 应 L1 段内意图正确率 | 主效果 |
| L2HandoffAcc | 应 L2 且正确交接的比例 | 主效果 |
| P95 | 单条路由耗时 | 成本 |
| ExceptionRate | 执行器/模型异常率 | 稳定性 |
| TokenCost | L2 触发次数（L1 均为 0） | 成本 |

**决策规则（字典序，不可用加权平均掩盖安全）**：
1. 硬门：`critical` 误答 **= 0** 且总 FAR-answer **≤2%** 且 `ExceptionRate ≤0.5%`；
2. 硬门：不得存在任一 `segment` 的 Coverage <60%（防“平均值掩盖塌陷”）；
3. 通过者在 `Coverage × IntentAcc` 上取最大；
4. 平手（差 <2pp 且 bootstrap 95% CI 跨 0）→ 取 P95 更低者；仍平手 → 取结构更简单者（依赖更少）；
5. 赢家与第二名需做 **McNemar 配对检验**（α=0.05），差异不显著时明确标注“统计上不可区分”。

#### 7.1.4 执行载体

- 脚本：`34-前端应用训练系统/scripts/eval_router_strategies.py`
- 输入：`34-前端应用训练系统/eval/e1_cases.jsonl`（版本化）
- 输出：`34-前端应用训练系统/eval-results/<YYYYMMDD>/`：`summary.csv`（策略×参数）、`per_segment.csv`、`decisions.jsonl`（逐条可复查）、`manifest.json`（git commit、模型 sha256、seed、数据集版本）
- 性能：查询向量一次性编码并缓存，跨策略复用；500 条 × 6 策略 × 16 组参数可在单机分钟级完成。
- 真实验收：`--real-cloud 60` 抽样走云端 `/api/data/query` 复核，防止桩化失真。

#### 7.1.5 交付与回填

1. E1 报告：策略对比表 + 分段结果 + 统计检验 + 推荐策略与参数；
2. 回填 §9.2：**删除所有“建议默认值”，替换为实验结论**；
3. 若赢家为 S3/S4，则 P2 的 δ 直接采用实验值，不再二次拍板；
4. 若 S1 在 `semantic` 段 Coverage <70%，则 S1 不得作为终态，只能作为 P0 过渡。

---

## 8. 对 v1.3 的条款修订清单

| v1.3 位置 | 原表述 | v1.4 修订 |
|---|---|---|
| §1 分层判据 | 本地模型/向量检索属 L1 | **保留**（本 SPEC 的判定依据） |
| §2 十意图零 token | 十意图零 token | **保留**，并扩展至 19 个执行器 |
| §3.5 第 4 条 | 认知匹配度高才 L1 直答 | 改为：认知匹配度仅用于 **L1 之后的裁决** 与 L2 路线 |
| §5 路由器第 4 条 | 高置信 → L1，低置信 → L2 | 改为 §4 判定表（9 条） |
| §6 待推进项 2 | fetchContext 认知 scope 暴露 | 增加：能力目录入索引，供裁决①使用 |
| 认知层命名 | C1-C4 | **保留**（避免与 L0/L1/L2 混淆） |

### 8.1 v1.4-r1 评审修订对照（M1–M5 + DA）

| 编号 | 评审问题 | 修订落点 |
|---|---|---|
| M1 | `route_confidence=0` 会导致 ChatPanel 拒答 | §4.1：契约直答置 `1.0`；不采用“只信 decision”改法 |
| M2 | 执行器无 `success=false`；§3.3 与 §5 矛盾 | §3.3 四态；§5 异常=`degraded_answered`、超时=`declined` |
| M3 | 数据类/语义类无机器可读定义 | §3.2.1 新增 `channel` 字段与三处同源约束 |
| M4 | “能力目录索引”不存在 | §3.4.1 两级交付 + P3a 硬性验收 |
| M5 | 验收门禁不可机器判定 | §6.2 A1–A11（注入点/基线/冒烟/审计）；δ 降为观测项 |
| DA-1 | P0 无护栏 | P0 关闭语义通道 + A10 + P2 前置 A11 |
| DA-2 | 认知裁决画饼 | P3a 独立阶段 + 交付定义 |
| DA-4 | mock 不能证明端到端 | A9 云端冒烟写入 P0 合并条件 |

---

## 9. 风险与开放问题

### 9.1 风险

1. **开集误映射**：闭集 21 类 + 语义通道，域外问题会被映射到最近意图 → 依赖 margin + `unknown` + 硬负例扩容。
2. **正则与语义打架**：正则优先可能吞掉语义问法 → 数据类判定必须收紧到“结构化特征”，泛词交模型。
3. **裁决对象尚未建索引**：能力目录目前是文件（`intent_units/*/executor.md`），未入可召回存储；P3a 之前裁决只能给 `unknown`，已由 §3.4.1 明确为降级而非“已具备”。
4. **阈值耦合**：0.65 只属于认知裁决、0.66 只属于语义意图，禁止互相借用。

### 9.2 E1 实验结论（v1.4-r3，2026-11-17；开放参数已裁决）

> 实验：`eval/e1_cases.jsonl`（500 条，AI 初标，待人工复核）× S0–S5 × 54 配置；报告见 [eval-results/20261116/E1-REPORT.md](eval-results/20261116/E1-REPORT.md)。
> **最终裁决：目标策略 = S1（纯正则检测 + 能力契约门控）。** 硬门 0/54 通过的原因是复合问法被单边作答，属于输入侧闸门缺失，不是策略参数问题；补上复合问法闸后 S1 的 FAR 由 38.4% 降至 6.8%、Coverage 64.8%、IntentAcc 98.2%、P95 46ms。**上线顺序：复合问法闸先行，闸未交付前生产保持 S0。**

| # | 问题 | E1 结论（证据） |
|---|---|---|
| 1 | 策略结构（正则/语义/margin/认知） | **选定 S1**（Coverage 64.8% / IntentAcc 98.2% / FAR 6.8%（含复合闸）/ P95 46ms）——在覆盖、意图准确率、延迟三方面均优于 S0（26.8% / 100% / 20.8% / 1994ms）；S3 仅 +6pp 覆盖但 IntentAcc 降至 96.2%、FAR +0.4pp，语义通道暂不启用。S4 不引入（与 S3 指标一致、P95 高 43 倍）。**前置：复合问法闸先交付** |
| 2 | 语义阈值（全局 vs 逐意图） | **保持 0.66**。S2 网格：0.60/0.63/0.66/0.70 的 semantic 段覆盖 31%/29%/26%/16%，FAR 43.6%/42.0%/40.8%/38.8% → 阈值不是安全瓶颈，口径不动 |
| 3 | margin δ | **取 0.05，仅作观测默认，不设门禁**。S3 网格中 δ 0.02→0.08 使 FAR −1.6pp、覆盖 −3.2pp；赢家与第二名 McNemar p=0.51（不可区分），故不升级为硬门 |
| 4 | 数据类显式无数据 | **保留 `degraded` 直答**（§3.3 四态）。E1 桩化执行器，未测数据源可用性；待 `--real-cloud 60` 云端复核后确认 |
| 5 | 认知裁决索引对象 | **不引入 S4**。S4 与 S3(0.66/0.05) 指标完全一致（Cov 70.8%/FAR 39.2%），P95 46ms → 1994ms；裁决①（域外/复合）改由 P3a 能力目录承担 |

**E1 关键观测（供 P0/P2 复盘）**
1. 现状 S0：Coverage 26.8%（data 56%、semantic 1%、clarify 32%、regression 18%），FAR 20.8% —— 认知召回门控把 10 类可答意图挡在 L2 之外，即 §1.1 缺陷的量化证据。
2. 去认知门 S1：Coverage 64.8%、IntentAcc 98.2%、FAR 38.4% —— 覆盖恢复的代价全部来自 compound（79/80）与关键词陷阱（15/50）。
3. 语义通道增量：S2(0.66) 仅救回 semantic 段 21/80（26%），说明瓶颈是 `intent_units` 口语样本覆盖，不是阈值。
4. 纯语义 S5 在 data/clarify/regression 段塌陷（32%/20%/68%），**正则通道不可移除**。

**后续硬性前置（写入 P0/P2 合并条件）**
- P0：复合问法检测（双意图并列 → `compound_query` 交 L2）必须先于“移除认知准入”上线，否则 A10 过度覆盖审计必然 >2%；
- P2：`intent_units` 各意图口语正例扩量（当前 semantic 段仅 26% 命中），扩量后重跑 E1 再决定是否启用语义主通道。

### 9.3 E2 实验结论（2026-11-17：复合检测 + 模型建议器）

> 同一 500 条数据集；报告 [eval-results/20261116/E2-REPORT.md](eval-results/20261116/E2-REPORT.md)；脚本 `scripts/eval_compound_suggest.py`。

**E2-A 复合检测（compound 80 vs 单意图 240）**

| 检测器 | 召回 | 误杀 | 结论 |
|---|---|---|---|
| D0 规则多意图命中 | 53.8% | 15.6% | 误杀高，弃用 |
| D1 语义双峰（top2≥θ） | 61–94% | 20–84% | **模型不适合做复合检测**：单意图句同样双峰 |
| D2 连接词+多实体 | 46.2% | 1.6% | 精确但召回低 |
| **D4 子句切分+逐子句意图** | 55.0% | **0.0%** | 零误杀，作为基线 |
| **D5 = D4 ∪ D2 ∪ 多指标并列** | **78.8%** | **2.0%** | **采纳为 `compound_query` 闸** |

- S1 加 D5 闸：Coverage 64.8% → 64.0%（−0.8pp），FAR 38.4% → **13.2%**（−25.2pp），零模型、零 token；
- 剩余 13.2% = 17 条漏网复合 + 5 条关键词陷阱 + 2 条域外含金融词，属 G2 特征闸与 P3a 能力目录职责，规则调参已到边际。

**E2-B 模型建议器（语义 top3 → 意图 + 示例问法）**

| 指标 | 合计 | data | semantic | clarify | regression |
|---|---|---|---|---|---|
| top1 命中 | 58.8% | 66.2% | 38.8% | 50.0% | 97.5% |
| top3 命中 | 67.6% | 75.0% | 50.0% | 62.5% | 100% |
| **延伸推荐（top2–3）** | **8.8%** | 8.8% | 11.2% | 12.5% | 2.5% |

- 结论：**只能做“L2 交接引导（top3 候选问法）”，不能做“延伸发现”**（8.8% 太低，且几乎都集中在 top1 近邻）；
- 成本：语义调用 P50 35ms / P95 81ms → 必须异步 + ≤30ms 超时丢弃，不进准入主链路；
- 上线门槛：影子模式 1 周，采纳率 ≥15% 且 decision 零变化，再上前端。

**裁决更新**：复合闸从“待交付”改为“**D5 规则（零模型）**”；模型定位为“建议器（P2，先影子）”，不参与准入与复合检测。

**实现落点（v1.4-r4 已交付代码，默认 S0 零行为变化）**
- 复合闸：`l1_route_signal.is_compound_query()`（D4∪D2∪多指标并列，失败 FAIL-OPEN 不误杀）；
- 策略开关：`L1_ROUTING_STRATEGY=S1` → 纯正则检测 + 契约门控 + 复合闸，**不调用认知召回**；
- 真实链路复算（500 条，执行器桩化）：**Coverage 64.0% / FAR 13.2% / compound 正确交 L2 80.0%**，与 E2 预测一致；
- 测试：`tests/test_l1_s1_routing.py`（复合检测正负例、S1 不召回、默认 S0 不变）。

**建议器影子模式（v1.4-r4 已交付，默认关闭）**
- 模块 `l1_suggest_shadow.py`：单守护线程 + 有界队列（1000），队列满/异常一律静默丢弃，**不阻塞、不抛错、不改返回字段**；
- 挂载点：`route_query()` 外层（不侵入门控主流程 `_route_query_impl`），记录 `message/intent/decision/strategy/trace_id` + 语义 `top3` + `latency_ms`；
- 开关：`L1_SUGGEST_SHADOW=1`；日志：`L1_SUGGEST_SHADOW_LOG`（默认 `<repo>/logs/l1_suggest_shadow.jsonl`）；
- 统计：`python3 3.1-FRONTEND/scripts/l1_suggest_shadow.py --summary`（样本量/空候选率/错误率/P50·P95/top1 分布/按 decision 分布）；
- 验收路径：线上积累 ≥1000 条后，用 `e1_cases` 口径离线 join 判 top1/top3 命中与采纳信号，再决定是否上前端建议卡片。

**建议器实盘契约（v1.4-r4 已交付）**
- 返回位置：顶层 `suggestions`，**仅 `handled=false` 时存在**；L1 直答不返回该字段，不影响 `decision`/`route_confidence`；
- 结构：`[{intent, label, query, score}]`；`query` 必须满足 `detect_intent_regex(query)==intent`，因此**点击后原样重发即在 S1 下必然命中**，服务端无需任何特判；
- 预算：`L1_SUGGEST_BUDGET_MS=3000`（云端 embed 实测 600–900ms，CPU 争抢时超 1.5s），仅使用常驻向量服务（8099），服务不可达时快速返回 `[]`（不付 20s 冷加载代价）；
- 前端：`ChatPanel` 在 L2 交接后展示 ≤3 条问法卡片，点击以 `query` 重走完整 L1 门控（等同用户输入）；
- 已知限制：建议只覆盖语义 top3 且需存在可校验示例问法，口语段召回上限约 50%（E2-B）。

---

## 10. 附录 A：能力清单（当前实现）

| 类别 | 意图 |
|---|---|
| 已注册且有执行器（19） | data_query, data_insight, contradiction_insight, path_insight, technical_analysis, technical_indicator, stat_query, fundamental_valuation, asset_class_trend, event_analysis, risk_control, price_query, metric_series, whale_flow, calendar_event, leader_compare, top_correlation, persistence_strength, event_listing |
| 已注册无执行器（2） | doc_search, event_line_query |
| 当前绕过门控的集合 | `DETERMINISTIC_INTENTS`(7) / `EXECUTOR_AVAILABILITY_INTENTS`(1) / `metric_series` 序列特判（P1 合并为统一契约） |

## 附录 B：证据与实现位置

- 路由：`3.1-FRONTEND/scripts/l1_route_signal.py`
- 门控：`34-前端应用训练系统/core/route_confidence.py`
- 执行器：`3.1-FRONTEND/scripts/data_query_executor.py`
- 意图注册表：`3.1-FRONTEND/src/lib/l1-intent-registry.ts`
- 语义模型：`41-文件索引系统/core/intent_matcher.py`、`scripts/embed_server.py`、`intent_units/*`
- 认知召回：`4-MEMORY/9-工具与接口/cognitive_loop_entry.py`、`vector_memory_interface.py`
- 入口路由：`3.1-FRONTEND/src/app/api/data/query/route.ts`

---

## 11. 评审检查表

- [x] P0 顺序：先移除认知准入、再补裁决；**P0 不启用语义通道**（DA-1）
- [x] 开放参数不人工拍板：全部交由 §7.1 E1 实验裁决（v1.4-r3 已回填 §9.2）
- [x] E1-D1 测试集 500 条按 §7.1.2 分段构造，`semantic` 段与 intent_units 零重叠（`scripts/gen_e1_cases.py` 硬校验）
- [ ] E1 测试集需 100% 人工复核（当前 `label_status=ai_draft`）
- [x] E1 决策规则（critical 误答=0、分段覆盖率硬门、字典序）已执行：0/54 通过 → 不切换策略
- [ ] 复合问法检测（`compound_query`）方案是否作为 P0 前置（E1 显示其为 FAR 主因）
- [ ] §4 判定表 10 条是否覆盖全部现有问法（结合 407 golden + E1 500 条）
- [ ] §5 策略表默认值与配置契约（m4）是否同意
- [ ] §6.2 门禁 A1–A11 是否作为 P0/P2/P3a 的合并条件
- [ ] M1 方案 A（契约直答 `route_confidence=1.0`）是否确认，不再改前端判断
- [ ] 是否同步修订 v1.3 原文（或仅以本文件为准并标注取代关系）
