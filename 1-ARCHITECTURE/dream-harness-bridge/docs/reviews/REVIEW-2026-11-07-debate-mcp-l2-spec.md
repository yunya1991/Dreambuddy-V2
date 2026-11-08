# 同行评审报告 — Debate MCP × C-Drive × L2 集成 SPEC v0.1

> 评审依据：`1-ARCHITECTURE/skills/dream-science-peer-review`（四视角 + Devil's Advocate 让步阈值 + 7 模式阻断清单）
> 评审对象：`SPEC-DEBATE-MCP-L2-INTEGRATION-v0.1.md`
> 评审维度：架构 / 数据流 / 实际代码实现可行性
> 日期：2026-11-07
> 性质：AI 评审报告；最终决策 human-in-the-loop

## 评审摘要

- 整体评价：**修改后接受（Major 10 / Minor 12）**
- 结论：方向正确（统一 MCP facade + 调研预检 + C-Drive/L2 复用），但 **当前 Spec 把若干“目标态”写成了“现状”**，且 Research Prepass 的关键数据源在 MCP 边界上存在实际 bug；P0 前必须修正。

---

## 一、Journal-Fit Reviewer（架构适配性）

**结论：修改后接受。**

1. 统一 `agent.debate.mcp` 作为 C-Drive / 32 Bot / L2 的外部接口，方向正确；DSH `debate_engine.py` 已明确“C-Drive 与 Trae/32-bot 共用此引擎”，有代码基础。
2. **两套辩论路径未区分**：C-Drive 内部辩论（`_bull_bear_debate`，默认 v1；v2 才走 `DebateEngine.run_fast`）与 DreamOS A3B 节点（`a3b_bull_bear_debate.py`，按 C1/C2/C3/A2/BCRM/BDSM 加权）是两条不同链路；SPEC 将“C-Drive 结果注入 Aggregator/A0”混写，实际 C-Drive 走 `_reflect_after_debate` 更新决策，Aggregator 是另一子 agent 路径。
3. **L2 暴露面未注册**：47 `worker_roles` 中没有 `agent.debate.mcp`，L2 Worker 无法通过 Worker 能力集调用；需新增角色/允许项或独立 L2 profile。
4. **L1 MCP 依赖未标注**：L2 链路引用的 `l1.trading.mcp` 当前不存在（49 设计态），P2 依赖应显式写成前置门禁。

## 二、方法评审（架构与数据流）

### 2.1 Research Prepass 的检索数据流在 MCP 边界上断了（Major，最致命）

实测 `l0.cognition.mcp` 的 `unified_search`：

```json
{"ok": true, "data": {}, "source": "search.unified", "degraded": false}
```

原因：`_handle_unified_search` 调用 `get_unified_search().search()` 得到**已封装 envelope**（`data.hits/per_source/...`），随后又调用 `_wrap_merge(result, "search.unified")`；`_wrap_merge` 把 `data` 视为信封字段丢弃，导致最终 `data:{}`。证据：`cognitive_mcp_server.py:628-652` + `dreambuddy_l0/search/unified.py:55-57`。

影响：SPEC 的 P0 验收“citations 非空”在当前 MCP 边界不可达；Research Prepass 会“成功但空结果”，比失败更危险。

### 2.2 `run_deep` 不产出 `adjudication`（Major）

`debate_engine.run_deep()` 返回 `{topic, transcript, verdict}`，没有 `adjudication`（6 维评分）。SPEC 的 `DebateResult.adjudication` 对 deep/review 的承诺与代码不符；需在 MCP 壳或后端适配器中显式调用 `adjudicator.py`，否则契约虚设。

### 2.3 C-Drive 当前不是“直接走 run_deep”（Major）

- `c_drive_agent.py` 默认 `debate_engine="v1"`；v1 走 `_llm_based_debate` / `_rule_based_debate`，v2 才走 `DebateEngine.run_fast`。
- `run_deep` 目前没有 C-Drive 生产调用点；`handle_debate(action=run, mode=deep)` 是 IPC 对外入口，不等于 C-Drive 内部链路。
- SPEC 应把“C-Drive 切 MCP fast/deep”写成迁移任务（含 feature flag、回滚、灰度），不能写成现状。

### 2.4 Citation 映射未定义（Major）

SPEC 要求 `{source, path|memory_id, line?, quote}`，但没有定义各源到 Citation 的映射：

| 源 | 实际返回 | 需要的 adapter |
|---|---|---|
| `unified_search` | `hits[{ref, score, ...}]`（且当前被双层信封吞掉） | `ref → path/url`、snippet → quote |
| `recall` | `memories[...]`（实测 0 条） | memory_id/title/content → citation |
| `semantic_lookup` | `{symbol, aliases, type, ...}` | 术语 ID → source |
| `data_fetch` / `data_store_read` | 表/作用域结果 | table/row → citation |
| `code_search` | P1 未实现 | path:line + snippet |

没有 per-source adapter，`ResearchBrief` 无法稳定生成。

### 2.5 契约缺少 schema/版本注册（Major）

`DebateRequest v1` / `DebateResult v1` 只是文档表格，没有 JSON Schema、manifest、校验器；C-Drive、32 Bot、L2 三方消费会漂移。建议放 49/47 契约目录并加 `validate`。

### 2.6 源健康与降级判定不足（Major）

`unified_search` 在“全后端失败”时才 `degraded=true`；若后端返回空 hits 或 `data:{}`，仍 `ok=true`。Research Prepass 需要独立判定：`hits==0`、`degraded_sources`、`recall==0` 都应按源降级，并进入 `research.degraded`。

### 2.7 L2 频控与 job 生命周期未落地（Major）

SPEC 写“每 Worker 每分钟 ≤2 次、总并发 ≤2”，但 MCP 壳没有 rate limiter、队列上限、job TTL/清理；`start_debate` 直接起线程。需要落地 enforcement 点，否则只是口号。

## 三、统计/评测评审

1. A/B 设计只有指标，没有固定 seed、样本量、置信区间；建议沿用 49 的预注册模式（主/安全指标 + 非劣效边界）。
2. “citation 覆盖率”需定义分母：每条论据 vs 每个结论 vs 每场辩论；否则不可比较。
3. fast/deep/review 三种 mode 的成本/延迟差异大，A/B 必须按 mode 分层，不能混池。
4. C-Drive 置信度校准应作为独立指标（辩论前后 confidence 变化 vs 实际结果），不能只看 Judge 分数。

## 四、Devil's Advocate（让步阈值）

| # | 反驳 | 评分 | 让步判定 |
|---|---|---|---|
| D1 | “Research Prepass 可按 Spec 实现” | **5** | 必须让步：`unified_search` MCP 返回 `data:{}`，citation 映射缺失 |
| D2 | “C-Drive 可平滑切到 MCP” | **5** | 必须让步：当前默认 v1，run_deep 无生产调用，adjudication 不存在 |
| D3 | “L2 可直接调用 agent.debate.mcp” | **4** | 必须修改：worker_roles 未注册，l1.trading.mcp 不存在 |
| D4 | “DebateResult 契约定稿” | **4** | 必须修改：无 schema/版本/校验，adjudication 字段与后端不符 |
| D5 | “安全边界足够” | **5** | 必须让步：code_search 未排除 `.env`/凭证/密钥，检索内容可能泄露；注入防护未实现 |

## 五、代码实现评审（取证）

| 事实 | 证据 | 影响 |
|---|---|---|
| `unified_search` 经 MCP 返回空 data | 实测；`cognitive_mcp_server.py:628-652`、`unified.py:55-57` | P0 检索不可用 |
| `recall` 实测 0 条 | 实测 | 记忆 citation 可能为空 |
| C-Drive 默认 v1 辩论 | `c_drive_agent.py:257`；`_bull_bear_debate:730` | 不是 run_deep |
| `run_deep` 无 adjudication | `debate_engine.py:173-250` | 契约虚设 |
| C-Drive 结果进 `_reflect_after_debate` | `c_drive_agent.py:386-388` | Aggregator/A0 混写 |
| Worker roles 无 debate 壳 | `mcp_capabilities.yaml:405-430` | L2 不可调用 |
| `l1.trading.mcp` 不存在 | `find mcp_shells` 无 l1 | L2 前置缺失 |
| MCP 壳无 mode/research 参数 | `mcp_shells/debate_adversarial/server.py` | Spec P0 未实现 |
| 47 工具面 37/40 | validator | 加工具会超限，research 参数方案正确 |

## 六、7 模式阻断清单

| 模式 | 结果 | 说明 |
|---|---|---|
| 1. 幻觉引用 | ❌ | 把“目标态”写成“现状”（C-Drive run_deep/Aggregator/adjudication） |
| 2. 数据造假 | ✅ | 未编造数据；但未披露 `unified_search` 空 data |
| 3. 方法捏造 | ⚠️ | 方法合理，但关键检索链路在 MCP 边界上有 bug |
| 4. 框架锁定 | ⚠️ | DSH vs 32 canonical engine 未做决策标准 |
| 5. 结果幻觉 | ✅ | 未宣称已实现/已验证 |
| 6. 逻辑跳跃 | ❌ | C-Drive→MCP、L2→debate、research→citations 三处跳跃 |
| 7. 边界忽略 | ❌ | 安全/频控/数据敏感性/依赖门禁未闭合 |

## 七、Major 意见（必须修改）

| ID | 意见 | 建议 |
|---|---|---|
| M1 | `unified_search` 双层信封 bug | 修 `_handle_unified_search`（直接返回 `result` 或正确 merge），P0 前修复并加测试 |
| M2 | Research citation 映射缺失 | 定义 per-source `CitationAdapter`，每源输出 `{source, ref, quote, line?}` |
| M3 | C-Drive 现状误写 | 明确 v1/v2、`run_deep` 无生产调用；把切 MCP 写成迁移任务 |
| M4 | adjudication 不存在 | 在 MCP 壳/后端适配器调用 `adjudicator.py`，或从 deep 契约移除 |
| M5 | L2 Worker 未注册 | 在 `worker_roles` 增加只读 debate 工具，或新增 `l2.analysis` 角色 |
| M6 | `l1.trading.mcp` 不存在 | 写成 L2 P2 前置门禁，未落地前 L2 链路不可验收 |
| M7 | 契约无 schema | 为 `DebateRequest/Result v1` 建 JSON Schema + 校验 + 版本 |
| M8 | 源健康判定不足 | `hits==0`/`data:{}`/`degraded_sources` 都触发源降级 |
| M9 | 安全边界不足 | code_search 排除 `.env`/凭证/密钥；检索内容脱敏；注入防护实现 |
| M10 | 频控/TTL 未落地 | 在 MCP 壳实现 rate limiter、并发上限、job TTL/清理 |

## 八、Minor 意见（建议修改）

1. C-Drive 阈值应写全：>0.75 跳过、0.65-0.75 只 recall、0.50-0.65 加辩论、<0.50 全链路。
2. `DebateResult.adjudication` 对 fast 可空，需在契约中明确。
3. 32/DSH 的 JSON 解析双实现（`robust_json` vs `_extract_json`）应在 P1 收敛并加一致性测试。
4. `agent.debate.mcp` 的 `capability_id=l0.rea` 语义牵强，建议单独 capability 或注明复用理由。
5. job 文件 TTL/清理/磁盘上限未定义。
6. `research` 默认 false 会限制 C-Drive 收益；建议按决策价值自动开关。
7. `unified_search` 的 sources 名称（search41/chroma/recall）与 Spec 的 `research_sources` 枚举需对齐。
8. citation 去重键（ref）与 top_k 截断规则需明确。
9. code_search 建议提前到 P0（代码定位是本次核心价值），至少提供最小 `rg` adapter。
10. L2 配额数值需与 46/47 治理对齐，不能只在 Spec 写数字。
11. fast/deep/review 的 token/成本预算需量化。
12. 失败语义需区分“源不可用”与“检索成功但无结果”，避免“空结果伪装成功”。

## 九、综合决议与修改顺序

**决议：修改后接受。** M1-M10 闭合前不建议进入 P0 实现。

顺序：
1. **M1 + M2 + M8**：先让 Research Prepass 真正能拿到并映射 citations（否则 P0 无意义）。
2. **M3 + M4**：修正 C-Drive 现状与 adjudication 契约（避免把设计当现状）。
3. **M5 + M6 + M10**：L2 可调用性与频控/TTL。
4. **M7 + M9**：契约 schema 与安全边界。
5. Minor 批量修订。

## 十、评审局限

- 未运行 C-Drive 全链路；`unified_search` 空 data 是基于本地 stdio 实测，云端可能不同，但代码路径存在双层信封问题。
- 未覆盖 47 全部治理规则；worker_roles 只读约束需与 46/47 进一步对齐。
- 最终决策与排期由 human-in-the-loop 作出。