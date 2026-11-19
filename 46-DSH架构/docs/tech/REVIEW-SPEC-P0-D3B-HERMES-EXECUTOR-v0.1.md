# REVIEW: SPEC-P0-D3B HermesExecutor v0.1

- **评审日期**: 2026-11-19
- **评审对象**: [SPEC-P0-D3B-HERMES-EXECUTOR-v0.1.md](SPEC-P0-D3B-HERMES-EXECUTOR-v0.1.md)
- **评审方法**: 对照 46 主设计 ADR、P0-D3 launcher 契约、53 插件白名单、3+3 映射、47/49 边界，并逐项核实实现代码
- **评审结论**: 🟡 **修改后接受**（Major 12 / Minor 15）
- **是否可进入实现**: **否**。先补 Phase 0 可行性 spike + 修订 SPEC v0.2，再复审

---

## 一、总体判断

方案的**分层判断是正确的**：Hermes 作为 executor 而非 Worker 角色、不替换 C-drive、不进入 Cordis 插件、只读 + 回执 + 可回退，这些都与 46/53/3+3 一致。

但 SPEC 目前把三个**未验证的假设**写成了既定事实：

1. Hermes 存在稳定的 headless 结构化入口；
2. Hermes 能作为 MCP client 按角色挂载 47 壳；
3. 关掉 terminal/file/browser 后，Hermes 仍显著强于 DSH。

这三点任意一条不成立，POC 的价值前提就不成立。因此 SPEC 必须增加 **Phase 0 可行性门禁**，而不是直接进入 POC。

---

## 二、阻断项（Top 5）

| # | 问题 | 影响 |
|---|---|---|
| B1 | H1/H2 是假设，不是已验证事实 | 可能在投入实现后才发现无程序化入口 / 无 MCP client |
| B2 | 安全约束与价值主张冲突 | 工具全关后 Hermes 只剩多轮推理，增益未量化 |
| B3 | 角色能力存在双事实源（53 vs 47） | 注册表漂移，越权或误拒 |
| B4 | 只挂 shell ≠ 只暴露角色工具 | shell 内工具数 > 角色白名单，存在越权孔 |
| B5 | `run_batch` 契约写错 | 方案 B 接入即失败 |

---

## 三、Major findings

### M1 价值前提未验证，缺 Phase 0

- **位置**: §4.4、§7.1、§9 Q1/Q2
- **问题**: SPEC 把 T1/T2 与 MCP client 能力写成候选，但没有定义“验证失败后怎么办”。H1 门禁放在 POC 内部，意味着要先把 executor 写出来才能验证入口，顺序反了。
- **建议**: 增加 **§0.1 Phase 0（可行性 spike，1–2 天）**，只做三件事：
  1. 找到并跑通一个 headless 结构化入口（T1/T2）；
  2. 让 Hermes 挂载一个只读 MCP 壳并完成一次 `recall`；
  3. 关闭 terminal/file/browser 后，验证仍能完成任务。
  任一项失败 → **终止方案**，回退 DSH，不进入实现。

### M2 安全约束与价值主张冲突

- **位置**: §4.5、§5.1、§1.3
- **问题**: SPEC 要求关闭 terminal/file/browser，只保留 MCP 只读工具。此时 Hermes 相对 DSH 的增量只剩“多轮推理 + 委派 + 记忆”，但 POC 又关闭跨任务记忆。**增益未被定义，也无法验收**。
- **建议**:
  - 明确“最小可用工具集” = 47 只读 MCP + 子 Agent 委派（无 terminal/browser/file）；
  - 明确预期增益来源（多轮纠错 / 任务分解 / 证据组织），并在 POC 指标中单独度量；
  - 若 Phase 0 显示增益 < 10pp，直接终止。

### M3 角色能力双事实源（53 vs 47）

- **位置**: §2.3 `allowed_shells`、§6.2
- **问题**: `research` 的工具跨 `l0.cognition` / `l0.semantic-39` / `l0.rea` 三个壳，`engineer` 跨两个壳（[mcp_capabilities.yaml L996-L1028](../../../47-MCP管理系统/registry/mcp_capabilities.yaml#L996-L1028)）。SPEC 在 53 里再写一份 `allowed_shells`，等于复制 47 的映射；两边一改就漂移。
- **建议**: 53 **只登记 runtime 级约束**（profile/版本/风险/禁止路径），`role → shell → tool` 一律以 47 为 SSoT；`check_whitelist.py --runtime` 交叉读取 47 做校验，不复制映射。

### M4 shell 级挂载 ≠ 工具级白名单

- **位置**: §4.5 ①
- **问题**: 一个 shell 暴露多个工具（如 `l0.cognition` 7 个、`l0.rea` 8 个），角色白名单只有 10 个。只挂 shell 无法阻止 Hermes 调用“同壳但不在角色白名单”的工具。仅靠事后审计不满足 ADR-4/ADR-9。
- **建议**（三选一，必须写死）:
  1. MCP 侧按角色发放 tool-level token / filter；
  2. 47 生成“按角色裁剪”的 shell profile（只注册白名单工具）；
  3. 本地上游加一个 role-gateway proxy（仍以 47 为 SSoT），Hermes 只连 proxy。
  推荐 2；1 作为增强；3 作为兜底。禁止只靠事后审计。

### M5 `run_batch` 契约写错

- **位置**: §4.1
- **问题**: SPEC 写 `run_batch(assignments) -> List[...]`；实际 launcher 期望 `{ticket_id: result}` 字典（[`_run_batch_with_timeout` L452-L473](../../../34-前端应用训练系统/core/worker_launcher.py#L452-L473)）。
- **建议**: 改为 `Dict[str, ExecutorResult]`；Phase 1 明确**不实现 `run_batch`**，只走单任务 `__call__`，避免把方案 B 的风险带进 POC。

### M6 幂等承诺不可实现

- **位置**: §4.1 E-5、§4.7
- **问题**: “重放 3 次结果一致”对 LLM 不成立。
- **建议**: 改为“同一 `ticket_id` 不产生重复副作用；结果允许不同；由 launcher 按 receipt 去重”。幂等键只约束“不重复执行”，不约束“输出一致”。

### M7 预算/超时无法硬保证

- **位置**: §4.6、§7.2 H7
- **问题**: `max_tokens` / `max_turns` 依赖 Hermes 内部实现；T2 RPC 场景下没有子进程可杀，SPEC 的“进程组 kill”不成立；launcher 自身也只是 `thread.join` 放弃等待（[L582-L599](../../../34-前端应用训练系统/core/worker_launcher.py#L582-L599)）。
- **建议**:
  - 为每个 transport 定义 `cancel()` 语义（进程 kill / RPC cancel / 连接断开）；
  - 增加外部 token 计量 + 超限强制终止；
  - 若无法硬限制，必须在 SPEC 中降级为“软预算”，并把它列为风险而非保证。

### M8 POC 统计功效不足

- **位置**: §7.1（20/类）、§7.4（+10pp）
- **问题**: n=20 时 10pp 约等于 2 个样本，二项分布 95% CI 半径约 ±20pp，无法区分真实增益与噪声。
- **建议**:
  - 冻结评估集（≥50/类，含 must-have facts 与 rubric）；
  - 采用配对比较（同任务 DSH vs Hermes）+ 95% CI 或 Bayesian；
  - 二元成功判定需双人标注，报告一致性（Cohen's κ ≥ 0.6）。

### M9 完成判定主体缺失

- **位置**: §4.2 `acceptance.must_include`、§7.5
- **问题**: 未说明 `must_include` 由谁判定。若由 executor 自检，违反 ADR-6（Worker 不自证）。
- **建议**: executor 只产出候选证据；判定归 **A 层 verify + 45 门禁**；SPEC 增加“验收判定不在 executor 内”的硬约束。

### M10 部署形态自相矛盾

- **位置**: §8（systemd 常驻服务）vs §4.4（per-task CLI）
- **问题**: 一边说 `dreambuddy-hermes-worker.service` 常驻，一边说 T1 每任务起子进程；没有定义服务的 API。
- **建议**: Phase 1 明确 **per-task 子进程**（可杀、简单、无 API 面），systemd 只托管 launcher；常驻服务留到 Phase 2，且必须先有请求-响应 API。

### M11 资源上限缺失

- **位置**: §5、§8
- **问题**: 云端 4 vCPU / 15GiB（[SERVICE_INVENTORY §1](../../../31-分布式计算部署/docs/SERVICE_INVENTORY.md#L8-L19)），未定义 Hermes 并发、内存水位、MCP 壳连接上限。
- **建议**: 增加 admission control（并发 ≤ 3、内存水位、超限排队/拒绝）；systemd 用 cgroup 限制；POC 记录峰值。

### M12 角色路由位置争议

- **位置**: §6.2（写进 47 `worker_roles`）
- **问题**: 47 是 L0 MCP 工具面 SSoT；把“运行时选择”写进 47 会让其同时承担工具治理与运行时路由，职责扩展未在 47 SPEC 中声明。
- **建议**: 优先放 launcher 配置（或新增 `worker_roster`），47 只保留 `tools/shells`；若坚持放 47，需同步更新 47 SPEC 的职责边界并过 47 域评审。

---

## 四、Minor findings

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| m1 | §5.2 H-1/H3 | “零写入”未界定；Hermes 自身会话 DB 必然写 HERMES_HOME | 限定为 repo/ticket/receipt/offset 零写入，HOME 内写入白名单 |
| m2 | §2.3 | 53 校验器没有执行点 | 定义 systemd `ExecStartPre` 或 CI 调用 `--runtime/--role` |
| m3 | §2.3 | `external_runtimes` 与 `entries` 的 `*trading*` 通配匹配关系未说明 | 明确两段独立匹配，runtime 不走 `entries` |
| m4 | §5.1 | 未防 Hermes 回退读 `~/.hermes/config.yaml`；现有配置 `terminal.backend=local` | 固定 `HOME`/`HERMES_HOME`/`--config`；增加“配置泄漏探针” |
| m5 | §5.3 | 现有 `hermes-gateway` unit 在云端处于 disabled | 新服务不复用其配置；给出运维基线 |
| m6 | §5.1 | 关闭 memory/curator 未给具体键 | 列出 `curator.enabled=false`、`memory.memory_enabled=false` 等 diff |
| m7 | §6.3 | 回退优先级未定义（env vs registry） | env kill switch 最高优先，registry 次之 |
| m8 | §7.3 T-03 | “注入越权”方法未定义 | 用测试 profile 额外挂一个白名单外只读工具 |
| m9 | §4.6 | `engineer` 的 REA submit/poll 可能超过 600s | 按工具设 timeout，或把 poll 改为 `paused + waiting_job` |
| m10 | §4.3 | trace 只写“可 join”，未定义 span schema | 规定必填字段与 join key（ticket_id/role/executor/tool/status） |
| m11 | §7.4 | `cost_usd` 可获取性未验证 | H7 增加“成本可观测”子门禁 |
| m12 | §7.6 | “2 周”未定义流量与最少样本 | 给出最少完成 ticket 数（如 ≥ 200） |
| m13 | §4.3 | 证据保留/脱敏未定义 | 定义留存期、脱敏规则、artifact 访问控制 |
| m14 | §8 | 版本只锁到 `0.20.x` | 锁到 patch + wheel hash + 离线包 |
| m15 | 全文 | 未写 Hermes 与 34 训练链 settle 的关系 | 明确 Hermes 不做 settle，沉淀仍归编排侧 |

---

## 五、与 53 对齐专项

| 检查项 | 结论 | 说明 |
|---|---|---|
| Hermes 是否 Cordis 插件 | ✅ 判断正确 | 不应进入 `cordis.patch.yml` |
| 是否新增分类 | ⚠️ 需细化 | `external_runtimes` 合理，但必须避免复制 47 角色映射（M3） |
| 是否遵守 deny-by-default | ✅ | 与 whitelist v1 一致 |
| 是否明确执行点 | ❌ | 校验器无调用点（m2） |
| 是否与 `*trading*` 冲突 | ⚠️ | 需说明 runtime 不走 `entries` 通配（m3） |
| 是否 sandbox 先行 | ✅ | `superagent` + sandbox 验证 |
| 是否复用 Feishu gateway | ✅ | 已要求物理隔离 |

**结论**: 53 对齐方向正确，但“登记”与“执行”之间缺一环；需补校验调用点与交叉引用规则。

---

## 六、与 3+3 对齐专项

| 检查项 | 结论 | 说明 |
|---|---|---|
| 层归属 | ✅ | L2-E 执行编排，不新增层 |
| L2 对 L1 只读 | ✅ | research/engineer 当前只挂 L0 壳，结构上满足 |
| 实盘永不 MCP | ✅ | 已禁止 live/order |
| 交易热路径隔离 | ✅ | 已禁止 `*trading*` |
| Worker 只读 | ✅ | 写工具禁止 |
| settle 归属 | ✅ | 归编排侧 |
| 45 门禁 | ⚠️ | 只提“过门禁”，未定义判定主体（M9） |
| 资源/预算 | ⚠️ | 有 budget 字段，但无硬保证（M7/M11） |

**结论**: 层边界无冲突；主要缺口在“判定主体”和“硬保证”。

---

## 七、POC 验收专项意见

1. **评估集必须先冻结**：60 条任务需给出任务 ID、输入、must-have facts、评分 rubric；否则成功率不可比。
2. **对照必须同任务配对**：同一任务分别走 DSH 与 Hermes，报告配对差值与 CI。
3. **门禁顺序要前移**：H1/H2 应在 Phase 0 完成，不应等到 POC 实现后。
4. **H3 的零写入探针**要排除 HERMES_HOME，否则必然失败。
5. **H7 需拆成两个子门禁**：预算可执行性 + 成本可观测性。
6. **回退演练必须真实执行**：不能只写“< 5 分钟”，要给出演练记录。

---

## 八、SPEC v0.2 修订清单

- [ ] 新增 §0.1 Phase 0 可行性 spike（含终止条件）
- [ ] 重写 §4.1 `run_batch` 契约为 `Dict[str, ExecutorResult]`，Phase 1 禁用
- [ ] 重写 §4.1 E-5 / §4.7 幂等语义（无重复副作用，不承诺结果一致）
- [ ] 删除 53 中的角色→shell 复制，改为 47 SSoT + 交叉校验
- [ ] 增加 tool-level 白名单方案（M4 三选一）
- [ ] 增加 per-transport `cancel()` 与外部 token 计量
- [ ] 增加执行判定主体（A 层 verify + 45）
- [ ] 统一部署形态（Phase 1 per-task 子进程）
- [ ] 增加资源 admission control
- [ ] 决定 executor 路由配置归属（launcher vs 47）
- [ ] 补 span schema、证据留存/脱敏、版本锁定
- [ ] 重写 §7 POC 指标（n≥50、配对比较、CI、rubric）

---

## 九、复审准入条件

满足以下全部条件后进入复审：

1. Phase 0 三项全部通过，有可复现日志；
2. SPEC v0.2 完成 §八 全部修订；
3. 53 与 47 的单一事实源关系在文档中无歧义；
4. POC 评估集与 rubric 已冻结；
5. 部署形态、资源上限、回退路径三者一致且可演练。

---

## 附录：代码核实记录

| 核实项 | 结论 | 证据 |
|---|---|---|
| launcher 单任务调用 | `executor(assignment)` 返回 dict | [L582-L599](../../../34-前端应用训练系统/core/worker_launcher.py#L582-L599) |
| launcher 批量调用 | `run_batch` 必须返回 `{ticket_id: result}` | [L452-L473](../../../34-前端应用训练系统/core/worker_launcher.py#L452-L473) |
| 线程超时 | `join(timeout)` 不终止线程 | [L582-L599](../../../34-前端应用训练系统/core/worker_launcher.py#L582-L599) |
| 角色工具集 | research 9 工具 / engineer 10 工具，跨 2–3 壳 | [mcp_capabilities.yaml L996-L1028](../../../47-MCP管理系统/registry/mcp_capabilities.yaml#L996-L1028) |
| 写工具禁用 | `WRITE_TOOLS` 硬编码 | [worker_roles.py L20-L28](../../../34-前端应用训练系统/core/worker_roles.py#L20-L28) |
| 53 校验器 | 只扫 profile 的 package.json + cordis.patch.yml | [check_whitelist.py L51-L128](../../../53-DSH插件模块/check_whitelist.py#L51-L128) |
