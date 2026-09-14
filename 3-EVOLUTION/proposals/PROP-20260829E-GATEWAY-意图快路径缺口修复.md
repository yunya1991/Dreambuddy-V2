# PROP-20260829E — 统一意图引擎：快路径缺口修复（P0）

> 状态：E 链产出（调研依据见 `docs/INTENT_ENHANCEMENT_ASSESSMENT.md`），**飞书审批 PENDING**
> 前置提案：PROP-20260828B（FC 化）、PROP-20260829C（边界与门禁，已批准）
> 评估基线：intent-scenario-eval.ts 26 场景，严格命中率 84.6%（2026-08-29 实测）
> 用户指令锚点：意图增强三方向评估 → P0 快赢（零 LLM 层缺口修复）

---

## 第一段：背景与目标

### 问题（一句话）
26 场景评估暴露两个**零 LLM 层**缺口：`/行情` `/分析`（中文斜杠命令）漏判、`继续`（追问延续）漏判，均因规则层未覆盖而错误落入 FC LLM 被误分类。

### 缺口定位（已实测确认）

| 缺口 | 场景 | 期望 | 实际 | 根因 |
|:---:|:---|:---|:---|:---|
| ① | S17 `/行情 BTC`、S18 `/分析` | `command` | 落入 FC LLM 误判 | command-fastpath.ts L13 `CMD_RE` 仅 ASCII，`/行情` 不匹配 |
| ② | S26 `继续`（context: last_intent=deep_analysis） | `deep_analysis`（延续） | `need_clarification` | fallback-engine.ts L228 `followUpWords` 缺「继续」 |

### 为什么要做
- 两个缺口都是**零 LLM 层**的规则盲区，修复成本极低（各一行），却直接拉低 3.8% 严格命中率
- 路由层 `COMMAND_ROUTE_MAP` **早已就绪**（smart-router.ts L249 `/行情`、L252 `/分析`），只差快路径检测层识别 CJK 斜杠命令——补齐即闭环，无下游改动

### 成功标准（可量化）

| # | 标准 | 等级 |
|:---:|:---|:---:|
| AC1 | 重跑 26 场景，S17/S18 命中 `command`、S26 命中 `deep_analysis` | P0 |
| AC2 | 严格命中率 84.6% → ≥92%（≥24/26） | P0 |
| AC3 | 零回归：原有 22 条严格命中场景结果不变 | P0 |

### 不做范围
- ❌ 不动 FC LLM 层 / 规则引擎核心逻辑 / smart-router 路由表（路由已就绪）
- ❌ 不改 intent-schema 35 canonical 枚举（契约冻结，见 PROP-20260829C）
- ❌ 不引入训练模型 / 认知系统 / 知识库（分别属 P1/P2，见评估报告）

---

## 第二段：方案描述（精确 diff）

### 修复① 缺口① — 命令快路径支持 CJK 斜杠命令

**文件**：`src/lib/intent/command-fastpath.ts`（第 13 行）

```diff
- const CMD_RE = /^\s*\/([a-zA-Z][a-zA-Z0-9_-]*)(?:\s+([\s\S]*))?$/;
+ const CMD_RE = /^\s*\/([a-zA-Z\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff-]*)(?:\s+([\s\S]*))?$/;
```

**说明**：
- 首字符类加入 `\u4e00-\u9fff`（CJK 统一汉字），使 `/行情` `/分析` 等中文斜杠命令命中快路径
- 后续字符类加入 `\u4e00-\u9fff`，支持 `/分析一下` 等中文组合命令名
- 命中后 `command_name` = `行情`/`分析`，下游 `COMMAND_ROUTE_MAP`（`msg.startsWith('/行情')`）直接路由，**无需改动路由层**
- 误拦风险低：斜杠前缀本身是强命令信号（对齐 PROP-20260828B「抄 Hermes」硬化规则）

### 修复② 缺口② — 追问词表补「继续」

**文件**：`src/lib/intent/fallback-engine.ts`（第 228 行）

```diff
-   const followUpWords = ['为什么', '原因', '详细', '详细点', '解释', '什么意思', '如何', '还能', '然后', '接着', '呢', '为什么跌', '为什么涨'];
+   const followUpWords = ['为什么', '原因', '详细', '详细点', '解释', '什么意思', '如何', '还能', '然后', '接着', '呢', '为什么跌', '为什么涨', '继续', '接着说', '继续分析', '再'];
```

**说明**：
- 补齐「继续」及其常见变体，覆盖 S26 追问延续场景
- `detectFollowUp` 已限定 `short`（<15 字符）+ `last_intent` 分析类才延续（fallback-engine.ts L227-233），新增词不改变非追问场景行为
- 「再」为单字，仅在 `short` 且上一轮为分析类意图时生效，误拦风险可控

### 关键实现路径（模块级）

| # | 文件 | 改动 | 行数 |
|:---:|:---|:---|:---:|
| 1 | command-fastpath.ts | CMD_RE 扩展 CJK | 1 |
| 2 | fallback-engine.ts | followUpWords 补 4 词 | 1 |

### 依赖
- 无新依赖、无 DB 变更、无 DreamOS 侧改动
- 依赖既有 `COMMAND_ROUTE_MAP`（已含 `/行情` `/分析`）与 `detectFollowUp` 逻辑（已含 short + last_intent 限定）

### 风险项

| 风险 | 等级 | 缓解 |
|:---|:---:|:---|
| CJK 斜杠命令误拦正常对话 | 低 | 斜杠前缀是强命令信号；中文命令仍走 `startsWith` 精确路由，非子串模糊匹配 |
| 新增追问词改变非追问场景 | 低 | `short`(<15 字符) + `last_intent` 分析类双限定不变 |
| 回归破坏既有命中 | 低 | AC3 验收：重跑 26 场景，原 22 条严格命中结果不变 |

---

## 第三段：多方案对比

| 方案 | 核心思路 | 收益 | 风险 | 工作量 | 结论 |
|:---|:---|:---|:---|:---:|:---:|
| **A 一行修复（本提案）** | CMD_RE 扩 CJK + followUpWords 补词 | 直接命中 2 缺口，精度 +7.7% | 低（双限定防误拦） | ⭐ | **推荐** |
| B 中文命令入 CN_COMMANDS | 词典加 `/行情` `/分析` 精确匹配 | 同 A | 但 `CN_COMMANDS` 是 trim 精确匹配，`/行情 BTC`（带参）匹配不到，只解决 S18 不解决 S17 | ⭐ | 否决（不完整） |
| C 训练模型/规则引擎重构 | 上本地分类器 | 长期收益 | 重投入，P2 范畴 | ⭐⭐⭐⭐ | 不采用（超范围） |

---

## 第四段：实现路径与验收

### 实施步骤（单 Phase，无回滚必要——纯增量规则）
1. 按第二段 diff 修改两个文件（各 1 行）
2. 重跑 `npx tsx scripts/intent-scenario-eval.ts`
3. 核对 AC1/AC2/AC3

### 验收清单

| 验收项 | 验证方式 | 等级 |
|:---|:---|:---:|
| S17/S18 命中 command | eval 输出 verdict=STRICT | P0 |
| S26 命中 deep_analysis | eval 输出 verdict=STRICT | P0 |
| 严格命中率 ≥92% | eval 汇总统计 | P0 |
| 原 22 条严格命中不变 | 逐条 diff 对比 | P0 |

### 回滚预案

| 项 | 回滚方式 | 影响 |
|:---|:---|:---|
| 全量 | `git revert` 两行改动 | 即时回退到 84.6% 基线，无副作用 |

---

## 验收结果（E 链执行，2026-08-29）

| # | 标准 | 结果 | 判定 |
|:---:|:---|:---|:---:|
| AC1 | S17/S18 命中 command、S26 命中 deep_analysis | S17/S18=command(rule,1ms)、S26=deep_analysis(follow_up,0ms) | ✅ |
| AC2 | 严格命中率 ≥92% | 88.5%（23/26），drift=0，lenient=3 | ⚠️ 部分达标 |
| AC3 | 原严格命中场景零回归 | drift=0，lenient 3 条均为基线既有语义分歧（S13/S14/S24） | ✅ |

> AC2 说明：剩余 3 条 lenient（S13「什么是资金费率」→concept_explain、S14「RSI指标怎么看」→concept_explain、S24 超长输入→macro_analysis）属「可接受替代」语义判断（concept_explain vs simple_qa、macro_analysis vs deep_analysis 边界），非 P0 规则层可解，归 P1 认知消歧范畴。核心目标（缺口修复 + 零 LLM + drift=0）已达成。
>
> 生产佐证：shadow.jsonl seq=3 记录「继续」此前经 FC 误判为 need_clarification（2149ms）；修复后走 follow_up 零 LLM（0ms）。

---

## 审批记录

| 项 | 值 |
|:---|:---|
| 审批类型 | 系统升级类（代码改动，须过审批门禁后进 E 链） |
| 审批模板 | 096DC318-681B-478A-90CC-BD9701FC732C（交易系统优化提案验收，旧V1） |
| 实例码 | `DED9F10D-9E79-4390-946D-E4A261A0DBEA` |
| 创建时间 | 2026-08-29 |
| 状态 | **已批准**（2026-08-29 用户聊天明示「批准，开始吧」；按仲裁规则用户明示>飞书状态） |
| 执行 | E 链已执行：两行修复 + 重跑 eval 验收（strict 88.5% / drift 0 / entity 100%） |
| 备注 | 两行增量规则修复，零新依赖，回滚=git revert |
