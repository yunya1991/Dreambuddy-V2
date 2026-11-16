# 同行评审报告 — SPEC-v1.4 L0/L1/L2 路由边界与认知裁决

> 评审对象: `34-前端应用训练系统/SPEC-v1.4-L0L1L2-路由边界与认知裁决.md`（v1.4，待评审）
> 评审日期: 2026-11-16
> 评审方式: 4 角色独立评审 + Devil's Advocate 让步阈值 + 7 模式阻断清单
> 评审依据: 代码核验（非文档推演），关键声明均回溯到实现行号
> **修订状态（2026-11-16）**: M1–M5 与 DA-1/2/4 已落入 SPEC v1.4-r1（见 SPEC §8.1 对照表）；Minor 保留待排期。

---

## 评审摘要

- **整体评价: 修改后接受**
- Major: **5** 条（M1–M5，必须修改）
- Minor: **7** 条（m1–m7，建议修改）
- Devil's Advocate: 最高评分 **5**，两条 ≥4 的必须让步
- 7 模式阻断清单: **2 项不通过**（方法可实施性、逻辑跳跃），1 项部分通过

---

## 一、Journal-Fit Reviewer（定位与目标适配）

**结论: 通过（有边界条件）**

- 与 SPEC-v1.3 §1 判据自洽：“本地模型/向量检索/确定性算法 → L1”，本 SPEC 把认知召回移出 L1 准入，方向正确。
- 与产品意图自洽：数据类门控、语义类小模型、认知裁决三分法可落到现有组件，不引入新模型。
- 边界条件：本 SPEC 只解决“路由与裁决”，不解决 L1 答案质量（数据时效、口径）。需在文中显式声明“L1 直答质量受数据源时效约束”，否则会被误读为“L1 直答等于权威结论”。

---

## 二、方法评审（可实施性）

**结论: 需修改（M2/M3/M4）**

核验到的实现事实：

| SPEC 声明 | 代码事实 | 判定 |
|---|---|---|
| 19 个执行器全零 token | `data_query_executor.py` 无 LLM/生成式调用；全部经 `L0Foundation.fetch_context` 或本地算法；`exec_price_query` 走 `market.ticker`，`exec_event_analysis` 走 `event.state` | ✅ 成立 |
| 执行器 `success=false` 表示“答不了” | 19 个执行器**全部**返回 `success=True`；失败一律用 `degraded=true` 或 `need_clarification=true` 表达（如 `exec_price_query` 无币种时返回 `need_clarification`） | ❌ 契约不成立（M2） |
| 异常/超时 → `success=false` → L2 | 现有 `_route_deterministic` 捕获异常后返回 `handled=true` + `degraded` + “执行异常”答案 | ❌ 与 §5 矛盾（M2） |
| 数据类 / 语义类可分离 | 现实现只有“正则通道 / 语义兜底”二选一，没有机器可读的 `channel` 字段；分类规则仅存在于散文 | ❌ 不可实施（M3） |
| 裁决输入为“能力目录索引” | `intent_units/*/executor.md` 只是文件，未进入 41 索引，未注册可召回 scope | ❌ 前提不存在（M4） |

---

## 三、统计评审（阈值与门禁）

**结论: 修改后通过**

- 语义阈值 0.66（bge-base，golden 407、FPR=0%）与认知裁决 0.65（bge-small 分布 0.6–0.7）来源清晰、互不混用，✅。
- `margin δ` 无任何标定数据（§9.2 只给了 0.03 建议值），但 §4 判定表把 `margin<δ` 写成可判定分支 → **提案值不能当验收依据**。建议：δ 先作为“观测项+告警”，等 P2 上线后用真实 trace 标定，再升级为门禁。
- A7“准确率/FPR 不劣化”未给基线数值与回放脚本路径，不满足“机器可判定”自述（M5）。

---

## 四、Devil's Advocate（反驳与让步）

### DA-1（评分 **5**，必须让步）
> “P0 移除唯一门控，但你承诺的‘认知裁决’要到 P3 且没有索引。等于先交付一个无护栏的 L1：闭集语义模型会把域外问题自信地映射到最近意图，用户得到一个**看起来很确定的错答案**，比现在静默转 L2 更危险。”

**让步**：原方案 P0 的护栏不足。修订为：
- P0 只放开**已注册且有执行器**的意图，语义通道**不启用**（P2 才启用），因此不存在开集映射风险；
- P0 必须同时交付“过度覆盖审计”：用生产 trace 抽样 ≥200 条，人工标注“该问法是否属于该意图”，误覆盖 >2% 则回滚；
- P2 启用语义前，必须建 **≥100 条域外/unknown 测试集**，δ 与阈值用该集标定。

### DA-2（评分 **4**，必须让步）
> “能力目录索引不存在，裁决①在 P3 之前恒为 unknown，‘认知裁决’实际上没有落地，L2 变成垃圾桶。”

**让步**：把 §3.4 裁决①改为**分两级**：
- P0–P2：`coverage=unknown`，但必须产出 `out_of_scope` 的**启发式初筛**（寒暄/闲聊/明显非金融问法），并把 L2 交接原因完整落 trace；
- P3：能力目录入 41 索引后，才允许 `in_scope/out_of_scope` 作为硬判定。

### DA-3（评分 **3**，可坚持，需补强）
> “19 个执行器零 token 不等于答案可靠；L1 可能在过期数据上给出自信答案。”

**回应**：SPEC 的 G3 只校验“可用”，未校验“时效”。接受为 **m8（新增 Minor）**：G3 增加 `observed_at` 时效标注，超期时 `degraded=true` 并在 answer 中提示。不改架构。

### DA-4（评分 **4**，必须让步）
> “A1 用 mock 执行器验证，只能证明门控移除，不能证明云端链路恢复；原缺陷是端到端表现。”

**让步**：新增 **A9 云端冒烟**：`price_query`、`event_listing`、`data_insight` 三条真实调用，断言 `handled=true` 且 `data` 非空，作为 P0 合并条件。

---

## 五、7 模式阻断清单

| 模式 | 结果 | 说明 |
|---|---|---|
| 1 幻觉引用 | ⚠️ 部分通过 | M4：把不存在的“能力目录索引”当成既有输入 |
| 2 数据造假 | ✅ 通过 | 云端实测值均可复现 |
| 3 方法捏造 | ❌ 不通过 | M2/M3：执行器契约与分类规则不可实施 |
| 4 框架锁定 | ⚠️ 部分通过 | 未比较替代方案（纯模型分类 / 纯规则引擎 / 现有门控+能力目录索引） |
| 5 结果幻觉 | ✅ 通过（无实验） | 本 SPEC 不含实验结论 |
| 6 逻辑跳跃 | ❌ 不通过 | M2 自相矛盾（§3.3 vs §5）；M1 未声明前端消费约束 |
| 7 边界忽略 | ⚠️ 部分通过 | 未定义复合问法、闲聊/滥用、数据时效边界 |

---

## 六、Major 意见（必须修改）

### M1 前端消费契约冲突（route_confidence）
- **事实**：[canHandleL1WithSignal](../3.1-FRONTEND/src/lib/l1-intent-registry.ts#L232-L245) 要求 `decision=L1_DIRECT **且** route_confidence ≥ 0.65`；ChatPanel 以此决定是否消费 L1 答案（[L184-185](../3.1-FRONTEND/src/components/features/chat/ChatPanel.tsx#L184-L185)）。
- **冲突**：SPEC §4.1 示例信号写 `route_confidence: 0.0`（因为不再有认知召回）。若 P0 按此实现，聊天入口会继续拒答，只有新闻 tab 正常。
- **修改**：明确二选一并写入 §4.1：
  - 方案 A（推荐，改动小）：契约直答统一 `route_confidence=1.0`（与现有 `_route_deterministic` 一致，[L544-545](../3.1-FRONTEND/scripts/l1_route_signal.py#L544-L545)）；
  - 方案 B：前端只信 `decision`，移除 `>=0.65` 判断（需同步改 4 个测试）。

### M2 执行器状态机不成立且自相矛盾
- **事实**：19 个执行器均无 `success=false`；失败用 `degraded` / `need_clarification`。
- **冲突**：§3.3 说“异常 → handled=true + degraded”，§5 说“超时 → success=false → L2”。
- **修改**：§3.3 重写为四态：`answered` / `degraded_answered` / `need_clarification` / `declined`；并给出各状态对应的 `decision/handled`。明确 `need_clarification` 属于 L1 正常输出（问用户币种），不得交 L2。

### M3 数据类/语义类缺少机器可读定义
- **修改**：注册表增加 `channel: "data" | "semantic" | "generative"` 与 `requiredPattern` 并列；`intent_units/*/intent.yaml` 增加同名字段；Python 侧只读注册表，不再各自维护正则分类。判定表引用该字段而不是散文。

### M4 裁决①的前提缺失
- **修改**：§3.4 明确“能力目录索引”为 P3 交付物；P0–P2 裁决输出降级为 `unknown` + 启发式 `out_of_scope`；同时补一条“交付定义”（41 索引 scope 名称、更新频率、召回方式）。

### M5 验收门禁不可机器判定
- **修改**：A1 明确 mock 注入点（`monkeypatch.setitem(EXECUTORS, ...)`）；A7 给出基线文件与回放命令；新增 A9 云端冒烟（DA-4）；δ 从门禁降为观测项。

---

## 七、Minor 意见

| # | 问题 | 建议 |
|---|---|---|
| m1 | `reasons` 码表更名（`deterministic_keyword_registry` → `deterministic_registry`）会断 trace 历史 | 保留旧码并在文档中登记别名，或提供映射表 |
| m2 | 未定义复合问法（“BTC价格和CPI”） | 先按“多意图 → L2”处理，写入判定表 |
| m3 | `metric_series` 语义命中但非确定性序列的落点未覆盖 | 判定表补一行 → `l1_low_confidence` |
| m4 | 语义服务超时/本地 fallback 只有矩阵描述 | 补配置表：`L1_EMBED_SERVER_TIMEOUT=2`、`L1_EMBED_LOCAL_FALLBACK=0`（生产） |
| m5 | 指标只定义未给采集落点 | 复用 `execution-trace` 的 `route` 阶段字段，明确字段名 |
| m6 | “L1 不得调用认知”与 `settle_to_cognitive` 冲突 | 区分“读”（禁止）与“写沉淀”（允许） |
| m7 | §4 row3 引用 §5 策略表，但默认值未定 | P0 前先定默认值，否则无法实现 |
| m8 | G3 只判可用、不判时效（DA-3） | 增加 `observed_at` 超期 → degraded |

---

## 八、修改建议（按优先级）

1. 先改 **M1/M2**（契约层），否则 P0 实现必然返工。
2. 再改 **M3/M4**（可实施性），这两条决定 P1/P3 是否可落地。
3. 最后改 **M5** 与 Minor（验收与可观测）。
4. DA-1/DA-2/DA-4 的让步项写入 §6.2 与 §7，作为阶段合并条件。

---

## 九、综合决议

- **结论：修改后接受**（Major 全改 + m1–m3 必改，其余可排期）。
- **可进入 Plan 的前提**：M1–M5 修订完成，且 A9 云端冒烟用例写入验收。
- **不建议**：跳过修订直接进入 P0 编码（会重复当前“假绿验收”问题）。
