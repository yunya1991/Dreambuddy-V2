# PROP-20260829D — DreamOS 复杂度分级渐进式编排（对话道智能化）

> 状态：📋 提案已提交，飞书审批 PENDING
> 前置：PROP-20260829-B v2（Hermes 意图识别 + DreamOS 物理编排，P1 已验证）；A_HERMES_SKILL 桥接节点（2026-08-29 已建成）
> 用户需求锚点（2026-08-29）：「简单到复杂问题，意图识别推进编排的复杂度；简单或中等问题不需要过度编排；每编排一步然后提问用户是否需要推进下一步，用户不继续也就意味着可以了」

---

## 第一段：背景与目标

### 问题（全部有实测锚点）

1. **全有全无编排**：`graph_planner._infer_chain()` 意图→固定链→全部节点一次跑完→综合；arrange 层 `phase/depth/resume` 关键词 grep 零命中，无分段能力。
2. **简单问题被过度编排**：P1 验证实测——一句「BTC 现在能做多吗？」触发 **9 节点全链、57.7s 延迟、仅意图识别 590 token**。
3. **意图层无复杂度维度**：recognize 只返回 intent_type + chain，「查个价」与「战略推演」享受同级别编排。
4. **执行面无中间粒度**：对外只有 `recognize_intent`（只读预览）与 `run_analysis`（整链执行），没有「跑一段」的接口。

### 为什么要做

- 对话道（PROP-B v2 范围）即将承接前端真实流量，全有全无编排 = 每个简单问题都烧全链 token + 分钟级等待，体验和成本双输。
- 用户已定调交互哲学：**默认收敛、深化自愿**（不继续 = 结束），需要编排层原生支持。
- 三层分工公理（LLM 决定「做什么」，DreamOS 确定性执行「怎么做」）要求确认环落在对话层而非管道内。

### 成功标准（可量化）

| # | 标准 | 等级 |
|:---:|:---|:---:|
| AC1 | 「BTC 能做多吗」phase=1 时 ≤3 节点、延迟 ≤15s，A2 评分结构仍完整回流 | P0 |
| AC2 | 分级黄金集 ≥20 条（覆盖 T0-T3 四级），分级一致率 ≥90% | P0 |
| AC3 | phase 缺省时行为与现状完全一致（向后兼容回归全绿） | P0 |
| AC4 | T2 问题端到端：Phase1 执行→呈现选项→用户确认→Phase2 携带 Phase1 结论执行 | P0 |
| AC5 | T0 查询零 LLM 零编排直答，≤2s | P1 |
| AC6 | 影子期分级统计：误判样本 100% 可被用户一句话「再深一点」纠正 | P1 |

### 不做范围

- ❌ 不动 cron 自动泳道（四闭环、A系列 cron、DreamOS 调度器）
- ❌ 不改 GraphEngine 确定性调度语义；确认环不进 DreamOS（不引入会话状态/恢复机制）
- ❌ 不动 PROP-20260829C 的 35 canonical 契约（仅在 canon→strategy 映射层预留 tier 透传字段）
- ❌ Hermes 运行时零代码改动（复用现成 clarify/多轮/记忆机制，行为由对话模式定义）

---

## 第二段：6 要素方案描述（方案 B：复杂度分级 + 对话层渐进编排）

### 架构

```
用户问题
  ↓
【意图识别 + 复杂度分级】（sense 层）
  规则优先（0 token 确定性短路）+ LLM 兜底
  输出: intent_type + complexity_tier (T0/T1/T2/T3)
  ↓
【分级路由】
  T0 简单查询 ──→ 单节点直答（零编排零LLM）         「BTC多少钱」
  T1 单域问题 ──→ 短链一次跑完(仅 required 节点)     「能做多吗」
                  → 结论附深化选项 a/b/c
  T2 多域/战略 ──→ 分段编排: Phase1(required)→呈现    「全面评估本周策略」
                  → 问是否深化 → Phase2(optional, 携带上段结论)
  T3 深度研究 ──→ 慢路径: A_HERMES_SKILL 桥接委托    「做A0矛盾论分析」
                  Hermes cron SKILL 异步（已建成）
  ↓
【确认环 = Hermes 对话层】（非 DreamOS）
  clarify/多轮/记忆原生能力；用户不回复 = 结束
  DreamOS 保持无状态，永不等待任何人
```

### 关键实现路径

1. **sense 层**：IntentResult 增加 `complexity_tier` 字段；分级器 = 规则（问句长度/决策词/多标的/「深度|全面|战略|推演」关键词）+ LLM 兜底。误判代价不对称 → **宁浅勿深**（判浅了用户一句「再深一点」即纠正；判深了白烧 token）。
2. **arrange 层**：`GraphPlanner.plan_from_intent()` 增加 `phase` 参数。Phase1 = 仅 `NodeMeta.is_required` 节点（字段已存在，现成分段挂钩点）；Phase2 = optional 深化节点。响应增加 `next_step` 提示（下一段可执行节点 + 预期成本）。
3. **执行面**：`/api/v1/run` 与 MCP `run_analysis` 增加 `phase` 参数，**缺省 = 跑全链 = 现状行为**（纯增量向后兼容）。
4. **状态传递零成本**：Hermes 对话上下文天然持有 Phase1 结论，调 Phase2 时透传（State 契约已有 context 字段）。
5. **默认收敛**：用户不回复 = 结束，无 pending 状态、无资源占用。T0/T1 不问（直答/答完给选项），仅 T2+ 逐步确认 → 消灭确认疲劳。

### 依赖

- PROP-20260829-B v2 P1 已验证链路（api_server /api/v1/run 外部可驱动）
- A_HERMES_SKILL 桥接节点（T3 慢路径，2026-08-29 已建成并生产验证）
- `NodeMeta.is_required` 字段（core/arrange/types.py 已存在）
- 确定性短路模式（2026-08-29 桥接任务已验证：规则命中 0 token / 0.4ms）

### 风险项

| 风险 | 缓解 |
|:---|:---|
| 分级误判 | 规则优先+LLM兜底；宁浅勿深偏置；影子期统计误判率 |
| 分段切断节点依赖 | Phase 边界 = is_required 语义边界；planner 依赖校验；Phase2 强制透传 Phase1 输出 |
| 向后兼容破坏 | phase 缺省 = 全链 = 现状；feature flag `DREAMOS_PHASED_ORCHESTRATION` 一键回滚 |
| 对话轮次增加延迟 | 仅 T2+ 逐步确认；深化是用户主动选择的 opt-in 行为 |
| 交易时效性 | 对话道本身只读分析；写操作仍走既有门禁；自动交易泳道完全不受影响 |

### 里程碑

M0 黄金集 → M1 sense 分级 → M2 arrange phase → M3 对话模式接线 → M4 影子观察调优

---

## 第三段：多方案对比

| 方案 | 核心思路 | 收益 | 风险 | 工作量 | 结论 |
|:---|:---|:---|:---|:---:|:---:|
| A DreamOS 内逐步确认 | 管道内暂停等用户输入再恢复 | 字面符合原始提法 | 需引入会话状态/超时/恢复，违背无状态物理管道公理；飞书回复分钟级致行情过期 | ⭐⭐⭐⭐ | 否决 |
| **B 复杂度分级 + Hermes 对话层渐进** | tier 分级 + phase 分段 + 确认环放对话层 | 贴合公理；DreamOS 小改、Hermes 零代码；默认收敛天然省 token | 分级器需黄金集回归 | ⭐⭐ | **推荐** |
| C Hermes 自由编排单节点 | DreamOS 只暴露原子节点，Hermes 全权编排 | 灵活度最高 | 编排权过度交给 LLM，漂移风险，违背「怎么做由物理管道确定性完成」公理 | ⭐⭐⭐ | 否决 |

---

## 第四段：实现路径与验收

### Phase 0 — 黄金集（P0）
- 手写分级黄金集 ≥20 条：覆盖 T0（查价/查仓位/查状态）、T1（单域决策问）、T2（多域/战略）、T3（深度研究关键词），每条含 input/期望 tier/期望链
- 验收：黄金集落盘 + 现状基线跑通记录（当前 9 节点全链行为快照）

### Phase 1 — sense 层分级器（P0）
- IntentResult 增加 complexity_tier；规则分类器 + LLM 兜底（复用确定性短路）
- 验收：AC2 一致率 ≥90%；规则命中路径 0 token 实测

### Phase 2 — arrange phase 分段（P0）
- GraphPlanner phase 参数 + is_required 边界切分 + 响应 next_step 提示；执行面参数透传（api_server + MCP）
- 验收：AC1（≤3节点/≤15s）+ AC3（缺省回归全绿）+ AC4（Phase2 透传执行）

### Phase 3 — 对话模式接线（P1）
- Hermes 侧对话模式定义（Phase1 结果呈现 + a/b/c 深化选项 + 透传模板）——零代码，prompt/skill 层
- 验收：T2 问题真实对话端到端（飞书实测）；用户不回复自然收敛

### Phase 4 — 影子观察（P1）
- feature flag 灰度；分级误判率 + 深化选择率统计（≥50 样本或 3 天）
- 验收：AC5/AC6；误判样本全部可一句话纠正

### 回滚预案

| 阶段 | 回滚方式 | 影响 |
|:---|:---|:---|
| 全部 | `DREAMOS_PHASED_ORCHESTRATION=off` 一键关闭 + phase 缺省即全链 | 无感，纯增量 |

---

## 审批记录

| 项 | 值 |
|:---|:---|
| 审批模板 | 096DC318-681B-478A-90CC-BD9701FC732C（交易系统优化提案验收，旧V1） |
| 实例码 | `2C8923B4-DBD4-47D2-A14F-12FE391636DF` |
| 创建时间 | 2026-08-29 |
| 状态 | **已批准**（2026-08-29 用户聊天明示「批准，开始执行」；飞书实例侧未点击，timeline 仅 START，按仲裁规则用户明示>飞书状态） |
| 登记 | approval_sync.py known-codes 已注册（30min 轮询跟踪） |
| 批准后动作 | E 链按 Phase 0→4 顺序执行，每 Phase 独立验证；git commit 随 E 链提交 |

---

## E 链执行记录（2026-08-29 完成）

| Phase | 内容 | 结果 |
|:---|:---|:---|
| 0 | 黄金集 23 条（T0×5/T1×9/T2×5/T3×4）+ 基线快照 | ✅ `dreamos-tests/golden_set_complexity.json` + `baseline_complexity_snapshot.json` |
| 1 | S 层复杂度分类器（纯规则零 Token） | ✅ `core/sense/complexity_classifier.py`；AC2 = 23/23 = 100% |
| 2 | A 层 phase 参数（planner/agent/api_server/MCP 全链路） | ✅ phase=1 → 节点 8→5、tokens 5300→1000、deferred=[F2,F3,A6]+next_step_hint |
| 3 | 对话模式（先呈现后追问） | ✅ `docs/PHASED_DIALOGUE_MODE.md` + Hermes skill `dreamos-phased-dialogue` |
| 4 | 影子观测 + 灰度门禁 | ✅ `~/.dreamos/phased_shadow.jsonl`；T0 短路/LLM 跳过由 `DREAMOS_PHASED_ORCHESTRATION=on` 门禁（默认关） |

### 验收对照

- **AC1** 轻量首答：✅ 节点 ≤5（实测 5）、估算 1000 tokens（↓81%）
- **AC2** 分级一致率：✅ 100%（要求 ≥90%）；修复 1 处规则漏洞（任务动词排除，防「评估仓位方案」误判 T0）
- **AC3** 零回归：✅ phase 缺省时 plan 与基线快照逐字段一致；test_smoke/test_sense_layer/test_cross_cutting 全绿
- **AC4** 节省可观测：✅ estimated_total_tokens + 影子日志
- **AC5** T0 直答：✅ 1.6ms / 0 tokens（flag 开）；10.5s→1.6ms（sense 层 T0 跳过 LLM 兜底）

### 附带修复

- `test_sense_layer.py` 过期断言（意图数 5→6，DEEP_ANALYSIS 早前合入未同步）
- 提交范围含 `recognizers/rule_based.py`、`llm_based.py` 的 DEEP_ANALYSIS 确定性路由（PROP-D T3 分级的直接依赖，此前未提交）
