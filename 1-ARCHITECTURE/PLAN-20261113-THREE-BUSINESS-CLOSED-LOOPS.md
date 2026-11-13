# PLAN：三大业务闭环链 施工计划

> **版本**: v0.4.1
> **更新日期**: 2026-11-13
> **依据 SPEC**: [SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS.md](./SPEC-20261113-THREE-BUSINESS-CLOSED-LOOPS.md) v0.3.3
> **依据评审**: [REVIEW-20261113-THREE-BUSINESS-CLOSED-LOOPS.md](./REVIEW-20261113-THREE-BUSINESS-CLOSED-LOOPS.md) v1.0
> **状态**: Phase 0 已完成；Phase 1 契约已打通（DEC-BCL-06 B+C、DEC-BCL-07 执行层落位 22），门禁 G-BCL-1 仍 FAIL——纸面成交刚开始累积，未达 n≥100；Phase 2 执行链 trace 已落地（待真实样本）
> **硬约束**: 本计划不授权 live 切流、不授权生产权重变更、不授权绕过 45 门禁的任何发布

---

## 一、计划边界

### 1.1 本计划做什么

把 SPEC 中已定稿的 P0/P1/P2 转成**有依赖顺序、有验收命令、有回滚点**的施工批次，并明确每批的放行门禁。

### 1.2 本计划不做什么

| 非目标 | 原因 |
|---|---|
| 不改 49/50/48/47 等领域契约 | 定义权归各域，本计划只消费 |
| 不新建"超级 MCP" | 违背 SPEC §9 与 47 H1—H8 |
| 不为 P3 插件生态排期 | 依赖 P2 完成，当前只登记不施工 |
| 不在本计划内开放 live | 需 49 显式授权 + Mandate + 人工评审 |
| 不以 AI 评分替代 D2 人工盲评 | SPEC §12.2.2 明确禁止 |

### 1.3 开工前置（用户决策，未完成则不失衡开工）

| 编号 | 待确认项 | 影响 |
|---|---|---|
| D-01 | 关联覆盖率阈值 `0.95` 是否认可 | ✅ 2026-11-13 已确认，作为硬下限生效，禁止为通过门禁下调 |
| D-02 | 回放抽样量 `n ≥ 100` 是否认可 | ✅ 2026-11-13 已确认，同上 |
| D-03 | 是否接受"单用户环境只用时序前后对照、不申报 A/B" | 决定 T4-2 结论强度上限 |
| D-04 | 能力包登记表放 `1-ARCHITECTURE/registry/`（方案 B）是否最终确认 | 决定 T6-1 是否可开工 |

> D-01/D-02 已于 2026-11-13 由用户确认。`bcl_gate_check.py` 的 `DEFAULT_JOIN_COVERAGE=0.95`、`DEFAULT_MIN_SAMPLE=100` 即为生效阈值，判定结果具备放行效力；如需变更阈值须重新取得用户确认并更新脚本注释。

---

## 二、阶段总览

| 阶段 | 目标 | 对应 SPEC | 出口门禁 | 依赖 |
|---|---|---|---|---|
| **Phase 0** | 判定基础设施可跑 | §12.1、§8.1.1 | 脚本可产出 verdict JSON | 无 |
| **Phase 1** | D1 交易证据闭环 | BCL-P1-01/02 | G-BCL-1 | Phase 0 |
| **Phase 2** | 执行链 trace 贯穿 | BCL-P1-03 | G-BCL-3 | Phase 0 |
| **Phase 3** | 涌现验证闭环（D2/D3） | BCL-P1-04/05 | G-BCL-2 | Phase 2（D3 依赖 task 关联） |
| **Phase 4** | 25—28 确定性经典模式 | BCL-P1-06 | 无独立门禁，随 G-BCL-1 复验 | Phase 0（可并行） |
| **Phase 5** | 能力包固化与选择性 MCP | BCL-P2-01/02/03 | G-BCL-4 | Phase 1/2/3 至少各 1 条通过 |
| **Phase 6** | 插件生态 | BCL-P3 | 另行评审 | Phase 5 |

**关键路径**：Phase 0 → Phase 1 → Phase 3 → Phase 5。

**可并行**：Phase 2 与 Phase 1 并行；Phase 4 独立并行（仅 25 模块内变更）。

---

## 三、Phase 0：判定基础设施

> 目标：让 G-BCL 从"文字描述"变成"可执行判定"。这是所有后续放行的前提。
>
> **状态：✅ 已完成（2026-11-13）**。出口验证：脚本 0 FAIL / 3 not_evaluated；V8 正向通过 + 负向拦截成功；映射表 15 条可解析。

### T0-1 门禁判定脚本

| 项 | 内容 |
|---|---|
| 产物 | `1-ARCHITECTURE/registry/scripts/bcl_gate_check.py` |
| 输入 | `capability_packages.yaml`、TrainingEvent 记录、`execution_rights.json`、task/trace 记录 |
| 输出 | `{gate_id, verdict, value, threshold, evidence_ref, checked_at}` JSON |
| 实现范围 | G-BCL-1/2/3/4/5 五条；G-BCL-0 用文档静态扫描单独实现 |
| 验收 | 对当前真实数据跑通，输出 `not_evaluated` 或 `FAIL` 均可，但**不得崩溃、不得虚报 PASS** |
| 风险 | 阈值未确认时用占位常量，输出 `threshold_unconfirmed` |

### T0-2 跨链事件样例

| 项 | 内容 |
|---|---|
| 产物 | `1-ARCHITECTURE/registry/fixtures/cross_chain_event.sample.json` |
| 内容 | D1/D2/D3 各 1 条，字段齐全，含 `business_key → event_id` 推导注释 |
| 验收 | 能被 T0-1 读取并成功解析；`event_id = sha256(business_key)` 可复算 |
| 用途 | 防止各端对信封字段理解不一致 |

### T0-3 47 registry V8 交叉引用

| 项 | 内容 |
|---|---|
| 产物 | `47-MCP管理系统/registry/scripts/validate_mcp_registry.py` 新增 V8 |
| 规则 | 能力包中每个标了 `mcp` 暴露的节点，必须在 `mcp_capabilities.yaml` 存在且 layer 一致 |
| 验收 | 构造 1 条不存在的节点引用，V8 必须报错；正常 6 条能力包必须通过 |
| 归属 | 47 域 owner |

### T0-4 事件类型映射表

| 项 | 内容 |
|---|---|
| 产物 | 36 域 `signal_type_mapping.yaml`（`event_type ↔ SignalType`） |
| 约束 | 只增不删；删除需 36 域评审 |
| 验收 | SPEC §7.2 列出的全部 `event_type` 均有映射 |
| 归属 | 36 域 owner |

**Phase 0 出口**：T0-1 可跑 + T0-2 可解析 + T0-3 生效 + T0-4 覆盖齐全 → 允许进入 Phase 1/2/4。

---

## 四、Phase 1：D1 交易证据闭环

> **状态：🟡 契约已打通，门禁仍 FAIL（2026-11-13）**。T1-1 证据器实测严格 join 0/180、G-BCL-1 FAIL；DEC-BCL-06 已裁决 **B 短期 + C 中期** 并完成契约落地；DEC-BCL-07 纠正执行层落位——40 只产意图（X0），成交由 **22** 纸面执行器产生。剩余 FAIL 原因：纸面成交样本尚不足 n≥100，非契约问题。

### T1-1 D1 统一 join

| 项 | 内容 |
|---|---|
| 状态 | 🟢 B/C 契约已落地（2026-11-13）；🟢 成交事实已由 22 纸面执行器产生（DEC-BCL-07）；🟡 门禁未通过（样本 n<100） |
| 产物 | `48-涌现架构/metrics/d1_join_evidence.py`；证据 `metrics/artifacts/d1_join_evidence.jsonl`；报告 `d1_join_report.json` |
| 目标 | 打通 `decision_id → order_id → fill_id → pnl → training_event_id` |
| 变更范围 | 48 域查询/聚合；40 域意图侧（`x0_pipeline.py` 回写 `decision_id`/`decision_ts`、多板块 `paper_only` 意图、`config.json` 增 `decision_source`）；22 域成交侧（`trade_execution_gateway.py` 增 `decision_id`、新增 `x1_paper_executor.py` 与 `audit/x1_paper_fills.jsonl`）；新增 `40/execution/portfolio_execution.py` 与 `portfolio_executions.jsonl`；**未改** 13/16/43/42/50 生产代码 |
| 关键约束 | join 主键是 `decision_id`，`trace_id` 仅作辅助定位，不替代主键 |
| 实测结果 | 存量：50 域 180 条决策全 `MULTI`、40 域 96 条记录无主键、严格覆盖 0.0；新契约 fixture：`join_coverage_strict = 1.0`（`matched_by=decision_id`，2 条纸面平仓成交）；G-BCL-1 因 n=2<100 仍 FAIL（不虚报） |
| 验收 | `join_coverage ≥ 0.95`（D-01 已确认）→ 存量数据 **FAIL**，待纸面成交累积到 n≥100 后复测 |
| 阻塞 | ~~DEC-BCL-06 选型~~ 已解除；~~执行层无成交~~ DEC-BCL-07 已由 22 纸面执行器补齐；剩余为样本量累积（7 天持仓周期 ⇒ 约需 15 周达到 100 笔平仓，或按板块并行开仓加速） |
| 回滚 | 证据器为纯读；40 新增字段与组合级文件为追加型，回滚 = 删除新文件 + 回退 `config.json` 段 |

### T1-2 跨端事件同步幂等

| 项 | 内容 |
|---|---|
| 目标 | 本地 12 条 / 云端 3 条 TrainingEvent 可同步且不重复 |
| 实现要点 | 统一 `business_key` 推导；两端**同一算法**生成 `event_id = sha256(business_key)`；`dedupKey = event_id` |
| 禁止 | 保留任何"端内自增/随机 UUID"作为去重键 |
| 验收 | 重复同步 3 次后总条数不变；`duplicate_count = 0`；补录不改 `event_id` 只更新 `ingested_at` |
| 证据 | 同步前后计数对比 + T0-1 verdict |
| 风险 | 历史 15 条若 `business_key` 缺失，需一次性回填映射表，不得重新生成新 ID |

### T1-3 训练建议采纳审计

| 项 | 内容 |
|---|---|
| 目标 | 48 只出建议；40/50 各自门禁决定采纳/拒绝，全程可审计 |
| 记录字段 | `suggestion_id / target(40|50) / evidence_ref / gate_verdict / adopted / rejected_reason / approver / version` |
| 禁止 | 48 直接写生产权重；任何"建议即上线"路径 |
| 验收 | 任意一条生产权重变更，均可反向追溯到 suggestion + 门禁结论 |

**Phase 1 出口**：G-BCL-1 PASS（且 D-01/D-02 已确认）→ 允许 Phase 5 启动的能力包状态提升。

---

## 五、Phase 2：执行链 trace 贯穿

> 前提：不透传层已被核实存在（`api-client.ts`、`dsh-execution-engine.ts`），本阶段只补 3 个缺口。
>
> **状态：🟢 代码已落地（2026-11-13），门禁待真实样本**。已实现：入口生成 trace（复用 `src/lib/trace-id.ts` 既有 `FE` 格式，不引入第二套）→ L1/L2 同一 trace 透传 → `task.trace_id` 落盘 → 五阶段台账 `events/frontend/execution_chain_trace.jsonl`（`src/lib/execution-trace.ts`）。G-BCL-3 契约已用合成样本正负向验证（100 任务 5 阶段 → PASS；同任务双 trace → FAIL），真实数据仍为 `not_evaluated`，须待实际请求累积 n≥100。

### T2-1 task 结构增加 trace_id

| 项 | 内容 |
|---|---|
| 文件 | `3.1-FRONTEND/src/lib/task-manager.ts` |
| 变更 | 任务对象增加 `trace_id`；创建时取入参，缺省生成 `tr_<ulid>`；禁止用 `taskId` 冒充 |
| 验收 | 新建任务后 `trace_id` 非空且全局唯一 |

### T2-2 入口统一生成

| 项 | 内容 |
|---|---|
| 文件 | `3.1-FRONTEND/src/components/features/chat/ChatPanel.tsx` |
| 变更 | 提交时生成 trace，随 L1 请求头携带；L1 未命中转 L2 时**原样透传** |
| 禁止 | L2 侧重新生成 trace |
| 验收 | 同一用户请求在 L1 与 L2 日志中 trace 相同 |

### T2-3 L1 侧接收与 settle

| 项 | 内容 |
|---|---|
| 文件 | `3.1-FRONTEND/scripts/l1_route_signal.py` |
| 变更 | 接收 `--trace-id`；写入 `settle_to_cognitive()` payload |
| 验收 | settle 记录含 trace_id，且与前端一致 |

### T2-4 L2 侧 settle 透传

| 项 | 内容 |
|---|---|
| 文件 | `3.1-FRONTEND/src/app/api/task/stream/route.ts` |
| 变更 | `settleL2ToCognitive()` 从 task 元数据取 `trace_id` |
| 验收 | SSE 完成后 settle 记录 trace_id 非空 |

**Phase 2 出口**：G-BCL-3 PASS —— 抽样 `n ≥ 100`，贯穿率 100%，降级项 `degraded_reason` 非空率 100%，**且同请求 trace 唯一**（防双 trace 虚高）。

---

## 六、Phase 3：涌现验证闭环

### T3-1 D2 人工盲评批次

| 项 | 内容 |
|---|---|
| 依赖 | 人工评审者 ≥2（**外部依赖，不可自动化**） |
| 复用 | 45 `scorers/human/workflow.py` 的 `_validate_blind()`，不重建 |
| 产物 | `45.human_review` 记录：`reviewer_id(脱敏) / blind_payload_hash / scores / alpha / verdict` |
| 阈值 | Krippendorff `α ≥ 0.6`；未达 → 增补评审者或判 `inconclusive` |
| 验收 | 存在 ≥1 批有效盲评；D2-A 由 `candidate` 可判定地升级或明确停留 |

### T3-2 48 verdict 引用人工证据

| 项 | 内容 |
|---|---|
| 变更 | 48 D2 verdict 增加 `human_review_ref` |
| 规则 | 该字段为空时，状态**不得**置 `verified` |
| 验收 | 构造缺字段场景，判定逻辑必须拒绝升级 |

### T3-3 E6 需求单回填

| 项 | 内容 |
|---|---|
| 变更 | 48 域将 D2-B 已落地产出回填 `resolved` |
| 验收 | 需求单状态与代码实际落点一致，可逐条核对 |

### T4-1 D3 标签采集

| 项 | 内容 |
|---|---|
| 依赖 | Phase 2 的 `task_id/trace_id` 关联 |
| 变更 | 前端采集 `accept/edit/reject`（explicit）；`abandon` 用超时推断并标 `inferred` |
| 隐私 | 只存标签、时间、能力版本、内容哈希；不存会话原文 |
| 验收 | 主终点只用 explicit；inferred 单独统计 |

### T4-2 D3 前后对照实验

| 项 | 内容 |
|---|---|
| 设计 | 上线前 vs 上线后同分布任务，不做 A/B |
| 验收 | 报告必须写明"单用户、时序对照、外部效度受限"；**禁止**出现"A/B 显著"表述 |
| 门禁 | G-BCL-2 判定时不接受以 `task_type` 代理标签申报在线收益 |

**Phase 3 出口**：G-BCL-2 PASS。

---

## 七、Phase 4：25—28 确定性经典模式

> 可与 Phase 1/2/3 并行，改动集中在 25 模块。

### T5-1 无 LLM 生成入口

| 项 | 内容 |
|---|---|
| 文件 | `25-用户策略生成系统/strategy_gen/` 新增 `generate_from_template()` |
| 流程 | 占位符替换 → 语法检查 → lookahead 检测 → 可选 hyperopt → 回测 → S5 清单 |
| 复用 | `template.py` 骨架、`paramopt.py` 的 config_patch、`backtest_engine` |
| 禁止 | 复制一套新的回测或检查逻辑；复制即违反"同一验收标准" |
| 验收 | `llm_available()==False` 时仍产出语法有效、可回测、无 lookahead 的策略 |

### T5-2 模板版本与参数 Schema

| 项 | 内容 |
|---|---|
| 产物 | 模板清单含 `template_id / version / param_schema(JSON Schema)` |
| 规则 | 参数越界直接拒绝，**不做隐式裁剪** |
| 验收 | 越界参数请求必须失败并返回明确原因 |

### T5-3 双模式同门禁校验

| 项 | 内容 |
|---|---|
| 校验 | 26 注册、27 审批对两种模式无差异化权限 |
| 验收 | 构造同参数策略，两模式走到同一审批队列，权限判定结果一致 |

### T5-4 信号 provenance

| 项 | 内容 |
|---|---|
| 变更 | 28 → 36 的 `trade_signal.*` 增加 `provenance.template_id / params_hash` |
| 验收 | 信号可追溯到模板与参数，且无 LLM 调用痕迹 |

---

## 八、Phase 5：能力包固化与选择性 MCP

> 前置：Phase 1/2/3 至少各有一条链通过对应门禁。

### T6-1 能力包状态提升流程

| 项 | 内容 |
|---|---|
| 变更 | `capability_packages.yaml` 从 `draft` 逐条提升，禁止跳级 |
| 规则 | `published` 前必须有 `evidence_ref` 且通过 T0-1 判定 |
| 审批 | 按 SPEC §8.1.1 的具名主体 |
| 验收 | 任一 `approved` 条目均可反查到证据与审批记录 |

### T6-2 选择性 MCP 投影

| 项 | 内容 |
|---|---|
| 范围 | 只读观察类优先；写工具必须有 Mandate + 预算 + trace |
| 禁止 | L1 热路径、live、任何交易执行能力 |
| 验收 | G-BCL-4 PASS：`layer=L1 且含写工具` 条目数 = 0，`live` 暴露数 = 0 |

### T6-3 预算与 trace 强制

| 项 | 内容 |
|---|---|
| 变更 | L2 写工具统一接入 token 计量与 trace |
| 验收 | 无预算或 trace 缺失的调用被拒绝，而非静默放行 |

---

## 九、Phase 6：插件生态（仅登记）

不排期。进入条件：Phase 5 完成 + G-BCL-4 稳定 + 47 域明确插件生命周期。遵循 53 的"先消费 → 再封装 → 后治理"。

---

## 十、依赖与并行关系

```text
Phase 0 ──┬── Phase 1 (D1 join / 同步 / 采纳审计) ──┐
          ├── Phase 2 (trace) ─────────────┬──────┤
          └── Phase 4 (25—28 确定性)       │      │
                                            │      │
                     Phase 3 (D2 盲评 / D3 标签) ←┘
                              │
                              ▼
                        Phase 5 (能力包 / MCP)
                              │
                              ▼
                        Phase 6 (插件, 仅登记)
```

- **Phase 2 → Phase 3**：D3 标签依赖 task/trace 关联；
- **Phase 1 与 Phase 2 可并行**：join 主键是 `decision_id`，不依赖 trace；
- **Phase 4 完全独立**：只动 25/26/27/28；
- **Phase 5 必须最后**：能力包状态提升需要前序证据。

---

## 十一、放行检查点

| 检查点 | 条件 | 不满足时的处置 |
|---|---|---|
| CP-0 | T0-1 可跑、T0-2 可解析 | 后续全部不启动 |
| CP-1 | G-BCL-1 PASS 且 D-01/D-02 确认 | Phase 1 不得宣称完成 |
| CP-2 | G-BCL-3 PASS 且同请求 trace 唯一 | Phase 3 的 D3 不启动 |
| CP-3 | G-BCL-2 PASS（含人工盲评证据） | Phase 5 不启动 |
| CP-4 | G-BCL-4 PASS | 不新增任何 MCP 暴露 |
| CP-5 | 回滚演练 ≥1 次成功 | 不允许 `published` |

---

## 十二、风险登记

| ID | 风险 | 影响阶段 | 缓解 |
|---|---|---|---|
| PR-1 | 阈值未确认即开工，验收失真 | 0/1 | ✅ 已关闭：D-01/D-02 于 2026-11-13 确认，脚本常量即生效阈值，下调须重新确认 |
| PR-2 | 历史 15 条 TrainingEvent 缺 `business_key` | 1 | 一次性回填映射，禁止重造 ID |
| PR-3 | L1/L2 双 trace 导致 G-BCL-3 虚高 | 2 | 判定式校验同请求唯一性 |
| PR-4 | 人工盲评无人执行，D2 卡在 candidate | 3 | 提前指定评审者；不接受 AI 替代 |
| PR-5 | D3 被包装成 A/B 结论 | 3 | 报告模板强制写明对照类型与效力上限 |
| PR-6 | 25 确定性模式退化为人工挑参 | 4 | 参数 Schema + 越界拒绝 |
| PR-7 | 能力包状态跳级 | 5 | T0-1 校验 + 审批留痕 |
| PR-8 | D1 决策侧与执行侧无共享主键，join 恒为 0，Phase 1 假性通过 | 1/3/5 | 已实测确认：180 条决策全 `MULTI`、96 条执行记录无 `decision_id`/`order_id`，严格 join 0/180。裁决前禁止模糊匹配、禁止用覆盖率 0 数据训练；须先裁决 DEC-BCL-06（SPEC §12.3）三路选型 |

---

## 十三、变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1.0 | 2026-11-13 | 首版：Phase 0—6、16 个任务卡、5 个检查点、7 项风险；关键路径 Phase 0→1→3→5 |
| v0.2.0 | 2026-11-13 | Phase 0 完成：T0-1 `bcl_gate_check.py`、T0-2 fixture、T0-3 V8、T0-4 映射表；出口验证通过（0 FAIL / 3 not_evaluated，退出码 2） |
| v0.3.0 | 2026-11-13 | 阈值 D-01（0.95）/D-02（n≥100）确认生效并关闭 PR-1；Phase 1 开工：新增 `48-涌现架构/metrics/d1_join_evidence.py` 产出严格 join 证据，实测 0/180、G-BCL-1 FAIL（根因契约缺失，非数据质量），Phase 1 阻塞于 DEC-BCL-06；新增 PR-8；PLAN 依据 SPEC 升至 v0.3.1 |
| v0.4.0 | 2026-11-13 | DEC-BCL-06 裁决 B（短期）+ C（中期）并落地：40 `x0_pipeline.py` 回写 `decision_id`/`decision_ts`（标的归一 + 伪符号排除 + fail-open）、`config.json` 增 `decision_source` 与 `output.portfolio_executions`、新增 `40/execution/portfolio_execution.py` 组合级执行记录（幂等）；fixture 验证 `join_coverage_strict=1.0`；Phase 1 阻塞项由"契约缺失"变为"执行层无成交"，T1-1 状态更新；依据 SPEC 升至 v0.3.2 |
