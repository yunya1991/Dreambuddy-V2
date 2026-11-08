# 第二轮复审报告 — 49 双决策链架构 v0.14.2 / 50 v0.2.0（指定复核 M2/M5）

> 评审依据：`1-ARCHITECTURE/skills/dream-science-peer-review`（四视角 + Devil's Advocate 让步阈值 + 7 模式阻断清单）
> 评审对象：SPEC-49 v0.14.2、50 SPEC v0.2.0、ADR-0002、42/48 集成文档（工作区修订稿）
> 评审范围：**指定复核 M2（evidence→path 合成）与 M5（11 子池状态写入条件）**；其余 M1/M3/M4/M6-M9 仅核对修订落点是否存在，不重新展开
> 日期：2026-11-07
> 性质：AI 复审报告；最终决策 human-in-the-loop

## 评审摘要

- 整体评价：**通过（有条件）**
- M2/M5 的主体缺口已闭合：path 字段映射与 23 实际消费结构一致；11 子池写入条件已用代码事实确认，signal-only 配置可行。
- 复审发现 **3 项 Minor**（M2-1 / M2-2 / M5-1），全部转入 R0-03 / R0-07 验收项，不构成 ADR 阻塞。
- ADR-0002 可转 `accepted`；R0 仍受 MVB 5/5 门禁约束（49 SPEC §13.10.1）。

---

## 一、复审范围与方法

1. **M2**：核对 50 SPEC §4.1a 的 path 字段映射是否覆盖 23 `_discover_paths` / `ContradictionIdentifier` / `DominanceResolver` 实际消费的字段，以及 D3 数据源是否可落地。
2. **M5**：核对 `_write_subpool_state()` 的真实调用条件、11 执行权配置能否同时满足 42 供源与 11 执行、42 适配器 TTL/开关是否匹配。
3. **方法**：静态代码取证（当前工作区，HEAD `b92bd82` + 未提交修订）；未运行生产实例、未执行 A/B。
4. 其他 M 项：只检查 v0.14.2 / v0.2.0 中是否存在对应修订落点（DEC-44、R3-01、50 §3.1、R4-01、§4.10、DEC-45、DEC-02 行），未做二次代码核验。

---

## 二、M2 evidence→path 复审

### 2.1 字段映射 vs 23 实际消费

| path 字段 | 50 §4.1a 映射 | 23 实际消费点 | 判定 |
|---|---|---|---|
| `path_id` | `ev:{source}:{symbol}:{dimension}:{horizon}:{intent}` | `dominance_resolver._path_id()`；矩阵/审计键 | ✅ 覆盖 |
| `source` | `evidence.source` | `_score_side` 的 `SOURCE_WEIGHT_MAP`；`_identify_dimension` 的 `SOURCE_DIM_MAP`；`SOURCE_TF_MAP` | ⚠️ 映射表未定义（M2-2） |
| `direction` | `evidence.direction` | 共振/冲突裁决、dominance `_alignment` | ✅ 覆盖 |
| `confidence` | `confidence × freshness × (1 - conflict_penalty)` | 力量对比、dominance、`_identify_dimension` 取最大置信路径 | ✅ 覆盖 |
| `expected_return` | `confidence × horizon_factor`（归一化排序分，非年化） | `_score_side`：`power = Σ(confidence × expected_return)`；`dominance._production_score` | ✅ 覆盖；23 自身 `_discover_paths` 取值亦为 0.15~0.4 级启发式分，不是年化收益，语义一致 |
| `resistance` | `1 - confidence` | `dominance._production_score` 的 `(1 - resistance)` | ✅ 与 23 路径构造口径一致 |
| `continuation_score` | trend/reversal/event_shock 分轨公式 | `dominance_resolver._pair_delta()`（缺省 0.5）；23 `_discover_paths` 不产出该字段，但 dominance 消费 | ✅ 覆盖；50 补充该字段不冲突 |
| `metadata` | `dimension_hint / intent / granularity / evidence_id / provenance` | 审计；`_identify_dimension` 不用 metadata | ⚠️ 需确保维度识别不丢失（M2-2） |

**结论**：50 的 path 集合可被 23 的 identify/dominance 逻辑直接消费，字段无缺项；`expected_return`/`resistance` 的语义与 23 现有路径构造一致，不存在“年化收益 vs 排序分”的口径冲突。

### 2.2 D3 数据源可行性

- `_last_bcrm2_result` 确实存在（`11-易经推理系统/scripts/memory_l4/polling_trader.py:5825`），但它是**实例级“最后一币”单值**，每币推理时覆盖，并非每币快照字典。
- 全库检索无 `11-bcrm-tactical` 实现；50 SPEC 将其定义为 **R0 新增**（§4.1a、R0-03/R0-07），方向可行，但“11 `_last_bcrm2_result` 每币快照”的措辞容易被误读为既有能力。
- 缺失降级已定义：无该源时 D3=neutral，不得用资产类 `11-bcrm` 冒充。逻辑成立。

**结论**：D3 落地路径成立，需在 R0 明确“新增每币持久化文件 + 42 适配器”，并修正措辞（M2-1）。

---

## 三、M5 11 子池写入条件复审

### 3.1 代码事实核验

| 事实 | 证据 | 判定 |
|---|---|---|
| `_write_subpool_state()` 仅在 `_write_shadow_signal()` 内调用 | `polling_trader.py:6785`（shadow 写盘）、`:6810`（调用 subpool state） | ✅ 与 M5 描述一致 |
| 只有被执行权限拦截的开仓意图进入 shadow | `_open_position()` 在 `:17621` 全局 shadow 闸门之后、`:17652` 执行权判定失败时调用 `_write_shadow_signal`；evolution 建仓路径 `:11981` 同理 | ✅ 一致 |
| 默认执行权排除 bcrm/bdsm/event/washout | `EXECUTION_AUTHORITY` 默认 `evolution_only`（`:842-861`）→ `allowed={"evolution"}`；上述子池标签被拦截并落盘 | ✅ signal-only 可行 |
| 子池标签与 42 文件名匹配 | washout `WASHOUT_ENTRY_SOURCE_TAG="washout_entry"`（`:9478`）；event 显式 `source_tag="event_arbitrage"`；42 适配器分别读 `washout_entry_state.json` / `event_arbitrage_state.json` | ✅ 一致 |
| 42 适配器 TTL/开关 | washout TTL 24h、event TTL 4h；`ENABLE_11_STATE_ADAPTER=1` 才发布（`_subpool_state_common.py:94`） | ✅ 一致 |

### 3.2 残余风险

1. **全局 `shadow_mode=True` 不会写子池状态**：`_open_position()` 在 `:17621` 直接 return，早于执行权判定。因此“signal-only”不能靠全局 shadow 模式实现，必须靠 `EXECUTION_AUTHORITY` 白名单。
2. **`EXECUTION_AUTHORITY=all`（或白名单包含 `washout_entry`/`event_arbitrage`/`bcrm`/`bdsm`）时，子池信号会被真实执行而不是写状态文件**，42 将逐步失去 washout/event-arb 源。
3. 需要在 R0-03 把上述配置写成可复现的验收项，并加负向测试/告警（M5-1）。

**结论**：M5 的主体结论成立——默认配置即可同时满足“11 子池 signal-only 供源”与“evolution 真实执行”；但必须把配置口径与负向场景写入 R0 验收。

---

## 四、Devil's Advocate（让步阈值协议）

| # | 反驳 | 评分 | 让步判定 |
|---|---|---|---|
| D1 | “M2 只写了公式，source→维度/权重映射缺失，23 算法跑出来的维度会全部退化” | **3** | 不阻塞复审通过；作为 M2-2 强制纳入 R0-07 验收 |
| D2 | “D3 源 `11-bcrm-tactical` 不存在，`_last_bcrm2_result` 只是最后一币，M2 的 D3 仍是纸面” | **3** | 不阻塞；R0-03 已列为新建任务，需修正措辞并加每币持久化验收 |
| D3 | “M5 依赖默认 authority；运维一旦设 all，42 供源静默消失” | **3** | 不阻塞；M5-1 要求负向测试 + 空源告警 |
| D4 | “本轮只复审 M2/M5，其他 M 项可能回归” | **3** | 范围限制已声明；其他 M 项仅核对落点，正式结论仍以 MVB 为准 |

> 无评分 ≥4 的反驳；M2/M5 的原始缺口（算法输入形态、子池写入依赖）已被代码事实闭合，剩余为验收精度问题。

---

## 五、7 模式阻断清单

| 模式 | 结果 | 说明 |
|---|---|---|
| 1. 幻觉引用 | ⚠️ 部分通过 | “`_last_bcrm2_result` 每币快照”措辞不准确（实为最后一币单值）；其余代码引用可验证 |
| 2. 数据造假 | ✅ 通过 | 代码事实与行号均可复核 |
| 3. 方法捏造 | ✅ 通过 | path 字段映射与 23 实际消费结构一致 |
| 4. 框架锁定 | ✅ 通过 | 本轮为指定项复审；共享库替代方案已在 ADR Alternatives 中否决并给出理由 |
| 5. 结果幻觉 | ✅ 通过 | 未宣称 A/B 或运行态结果 |
| 6. 逻辑跳跃 | ✅ 通过 | evidence→path→identify/dominance 链路已闭合 |
| 7. 边界忽略 | ⚠️ 部分通过 | M5 的 signal-only 配置边界需写成 R0 验收（M5-1） |

---

## 六、复审意见清单

### Minor（转入 R0 验收，不阻塞 ADR）

| ID | 意见 | 落点 |
|---|---|---|
| **M2-1** | `_last_bcrm2_result` 是“最后一币”单值而非每币快照；SPEC 措辞改为“R0 新增每币持久化 + 42 适配器”，验收要求 per-symbol 状态文件 | R0-03 / R0-07；50 SPEC §4.1a |
| **M2-2** | 50 必须定义自己的 `SOURCE_DIM_MAP` / `SOURCE_WEIGHT_MAP` / `SOURCE_TF_MAP`（或统一读 `metadata.dimension_hint`）；否则 `11-*` 源在 23 口径下全部退化为 C3 / 0.05 / medium | R0-07 验收；50 SPEC §4.1a |
| **M5-1** | signal-only 必须用 `EXECUTION_AUTHORITY` 白名单（默认 `evolution_only`），不得用全局 `shadow_mode=True`；增加负向测试：authority=all 或包含子池标签时，状态文件停止更新并告警 | R0-03；MVB-2 验收 |

### Major

无。

---

## 七、决议

1. **第二轮复审通过（有条件）**：M2/M5 主体闭合，3 项 Minor 作为 R0-03/R0-07 验收项。
2. **ADR-0002 可转 `accepted`**。接受的是“双决策链接构 + 50 独立实现 + 48 唯一对接口”的架构决策；不代表 R0 已完成。
3. **R0 门禁不变**：MVB 5/5 全绿前不得进入 R2；上述 Minor 纳入 MVB-2/MVB-3 证据链。
4. 后续动作：ADR-0002 状态更新；本轮修订与评审报告一并提交。

---

## 八、复审局限

- 本报告为 AI 复审，未运行生产实例、未执行 differential harness 或 A/B。
- 仅静态核验 M2/M5；M1/M3/M4/M6-M9 只检查修订落点，未重新做代码级验证。
- 最终架构决策与 R0 资源排期由 human-in-the-loop 作出。