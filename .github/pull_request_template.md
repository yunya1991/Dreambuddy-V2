## [协作 PR]（lease-guard 必填）

> `lease-guard` 会校验下列字段，且分支名须包含 `@<端>`（例：`feat/T-XXX@local`）。
> 改动模块须持有对应租约（`44-三端协作架构系统/shared/tools/lease.py claim`）。
> 仅改租约文件、`hotfix/*` 分支可豁免；紧急情况可加 `lease-waiver` 标签。
> `会话` 仅评审/测试角色需要（同端评审必须用独立会话）；dev 角色请留空。

Task ID: <task_id>
端: local
角色: dev
模块: <module1, module2>
会话:

## Task Card
Task Card: <link or inline summary>

## Execution Mode
Execution Mode: <STANDARD | PHASE_BROADCAST | STRONG_SYNC>
Direct Takeover: <no | allowed | active>
Governance Agent: <agent>
Task Type: <parallel | serial | shared-sync>
Dependency Gate: <planned | accepted | ledgered | none>
Next Required Action: <who does what next>
Next Sync Checkpoint: <design | implementation | closeout>

## Design Review
Design Review Comment: <comment url>

## Implementation Plan
Implementation Plan: <plan link>

## Test Report
Test Report: <comment url or artifact path>

## Collaboration Ledger
Source Type: <assigned | derived | exploratory>
Validator Agent: <agent>
Claim Pointer: <comment url>
Delivery Pointer: <comment url>

## Collaboration Protocol
- [ ] 已发 `STARTED`
- [ ] 范围变化时已发 `UPDATED`
- [ ] 阻塞时已发 `BLOCKED`
- [ ] 完成后将发 `DONE`
- [ ] 仅在关键节点广播，不为每个微小提交重复评论

## Owner Agent
Owner Agent: <SOLO | Claude Code | other>

## Shared Files Declaration
Shared Files Declared: <yes | no>

---

## 📋 文档同步检查（dream-doc-sync-gate）

> 根据变更内容勾选已更新的文档。**🔴 高优先级项未勾选不允许合并。**
> 如无需文档更新，勾选第一项并说明原因。

- [ ] **无需文档更新**（仅 bug fix / 测试 / 产物文件 / memory 文件，无结构变化）

**结构性变更（按实际勾选）：**

- [ ] 🔴 `DOC_INDEX.md` — 新增/删除 SKILL 或文档时必须更新
- [ ] 🔴 `CODE_STRUCTURE.md` — SKILL 计数/脚本版本变更时必须更新
- [ ] 🔴 `ARTIFACT_STORAGE_GUIDE.md` — `sessions/_template/` 结构变更时必须更新
- [ ] 🔴 `TRADING_SYSTEM.md` — 马丁策略核心参数/A系逻辑变更时必须更新
- [ ] 🟡 `README.md` — 目录结构变化时建议更新
- [ ] 🟡 `API_CONFIG_GUIDE.md` — 凭证/OKX接口方案变更时建议更新
- [ ] 🟡 `A_SERIES_DETAIL.md` — A系 SKILL 职责/输出变更时建议更新
- [ ] 🟡 `dream-systematic-trading/docs/third-screen.md` — Screen 3 SKILL 逻辑变更时建议更新

**门禁说明：**
如跳过门禁，请填写原因：`<跳过原因或 N/A>`
