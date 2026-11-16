# Trae Harness 机制卡（R1）— v0.1

> 生成方式：`trae/run_pilot.py`；证据分级沿用 33-REA（observation / derivation / inference / unknown）。

## M1 `agent_type × model → skill bundle`

**Observation**：内置 manifest 按 agent_type 与 model 两层组织 skills。

| agent_type | models | skills_min | skills_max |
|---|---|---|---|
| trae | 6 | 1 | 7 |
| code | 6 | 1 | 6 |
| design | 4 | 1 | 6 |
| work | 10 | 1 | 14 |

**Derivation**：技能面按模型能力裁剪，而不是全局暴露；`work` 的技能数最多（产物型任务），`trae` 居中。

**Evidence**：`~/.trae-cn/builtin/baseline/manifests/{trae,solo,global}.json`。

**对应 56**：能力聚合/路由（capability catalog）；建议映射到 `CapabilityCard` 与 L2 路线选择。

**Gap**：manifest 是声明，运行时是否按会话再次裁剪未知。

## M2 `session × mode → tool_set 快照`

**Observation**：25 个会话目录下物化了 mode 级工具 JSON。

| mode | tool_count |
|---|---|
| Explore | 16 |
| Plan | 16 |
| browser_use | 32 |
| computer_use | 17 |
| general_purpose_task | 20 |
| search | 31 |
| solo_agent | 32 |
| solo_agent_lite | 37 |
| solo_design_lite | 20 |
| solo_work_lite | 37 |

**Observation**：内置物化面 = browser 20 + code_mode 1（Exec）+ default 4；原生 chat 工具（如 `runSubagent`）不物化。

**Derivation**：工具可见性来自「会话+mode」快照，具备可审计/可回放潜力。

**对应 56**：IF-7 `tool_set.schema.json`、G-L2-11。

**Gap**：缺少同一会话内多次 tool_set 变更的版本记录；原生工具是黑盒。

## M3 `command → sandbox envelope`

**Observation**：命令信封 1006 条；status={'exited': 998, 'stopped': 6, 'running': 2}；target={'sandbox': 1006}；耗时 median/p90/max = 4944/27384/1148503 ms。

**Observation**：Top cwd = [('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2', 685), ('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND', 91), ('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE', 67), ('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/54-L1架构能力聚合层', 65), ('/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/56-L2架构能力聚合层', 32)]。

**Derivation**：每条命令都有 ownerHash/requestDigest/退出码/终止原因/受限路径，可作为回归证据。

**对应 56**：L2Envelope.trace、span、G-L2-8 回归门禁。

**Gap**：信封不含 session_id，无法直接归因到某次对话。

## M4 `session → checkpoint`

**Observation**：19 个会话快照目录，其中 19 个是 git 仓库。

**Derivation**：快照提供断点续跑与变更回溯的物理载体。

**对应 56**：Ticket 可续、ADR-10 可逆性。

**Gap**：未验证快照与 Ticket 状态的绑定关系。

## M5 `session → summary memory`

**Observation**：试点 50 个会话 / 627 条记录；动作条目分布={'read_analyze': 322, 'other': 621, 'test_verify': 598, 'coordinate': 155, 'doc_config': 248, 'edit_write': 816, 'run_deploy': 279}；outcome_rate=1.0。

**Derivation**：交互可压缩为 `intent → actions → outcome → learned`，适合做案例检索与训练。

**对应 56**：G 层四分流、33 训练案例库。

**Gap**：摘要是模型生成，必须与命令/快照交叉验证；原始对话在加密库。

## Bundle 取证（辅助）

**Observation**：

- `/Applications/Trae CN.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js`：16499954 B，toolId 候选 2 个，mode 命中 5 类。

- `/Applications/Trae CN.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.solo-lite-slim.js`：11940440 B，toolId 候选 2 个，mode 命中 5 类。

- `/Applications/Trae CN.app/Contents/Resources/app/extensions/ai-completion/dist/extension.js`：3793772 B，toolId 候选 0 个，mode 命中 1 类。

**Unknown**：压缩 bundle 无法建立模块/调用图；不得据此断言架构。
