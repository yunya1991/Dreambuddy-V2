---
name: evolution-system-sync
description: Dream-Agent 协作网络 / DZE 开发链定时同步与审计（3-EVOLUTION 进化系统）。触发词：Dream-Agent 每小时同步、DZE 每日审计、dream-agent-bridge、dze-bridge、账本、区块高度、DREAM 奖励、Validator 队列、进化系统状态、DreamAgent-Sync-Hourly、DZEChain-Audit-Daily。
---

# Evolution System Sync（3-EVOLUTION 协作网络同步/审计）

## 适用场景

- Cron「Dream-Agent 协作网络每小时同步」（DreamAgent-Sync-Hourly）：检查注册任务、账本、Validator 队列、超时升级、区块高度、总奖励，并与进化系统同步。
- Cron「DZE 开发链每日审计」（DZEChain-Audit-Daily）：审计 DZE 链状态、门禁、Gate1/Gate2、停滞链。
- 任何询问 dream-agent-bridge / dze-bridge / EvolutionOrchestrator 状态、账本、DREAM 奖励的任务。

## 关键事实：桥接器状态是纯内存态，无持久化

- `3-EVOLUTION/*.ts`（DreamAgentBridge / DZEBridge / ApprovalBridge / EvolutionEngine）的状态全部存于 TS 类内的 Map/数组。**没有序列化层**：repo 中不存在 `evolution_data/` 目录，磁盘上没有任何任务/账本 JSON 或 DB。
- 稳态（没有 node/tsx 进程在跑 EvolutionOrchestrator）= 注册任务 0、账本条目 0、Validator 队列为空、block_height 0、total_dream_rewarded 0。
- 结论：**每小时同步 cron 在稳态下应输出 `[SILENT]`**。不要每次都全仓库探索去找不存在的状态文件。

## 快速同步流程（全部廉价、限定目录）

1. 进程检查：`ps aux | grep -iE 'tsx|node.*evolution|dream-agent' | grep -v grep` — 无进程即无活跃网络状态。
2. 状态文件检查：`ls 3-EVOLUTION/*.json`（只有 health_dashboard.json，且是 2026-06 的过期数据）；`ls -d evolution_data`（不存在）。
3. 兄弟系统检查（可选）：`1-ARCHITECTURE/dreamos/data/automation_reports/dreamos_evolution_<date>*.json` — 那是 Python DreamOS 调度器的进化引擎产物，与 TS 3-EVOLUTION 是两套系统，不要混为一谈。
4. 全空 → 输出 `[SILENT]`。若发现活跃进程或新状态文件 → 按桥接器 API 跑完整清单（getAllTasks / getLedger / getTasksByStatus('in_progress') 查待验证 / 检查超时 / getBlockHeight / getTotalRewards）。

## Pitfalls

- **禁止全仓库 `grep -r` / `find .`**：repo 巨大，多次实测 60–120s 超时。必须限定子目录并 prune `.git`，或用 search_files 指定 path（注意 1-ARCHITECTURE 上 search_files 也会超时，改用更窄的子目录）。
- cron 模式下 `execute_code` 会被审批机制拦截，直接用 terminal / search_files / read_file。
- `3-EVOLUTION/health_dashboard.json` 停留在 2026-06-15，不能当作当前健康数据引用。
- 若用户要求带历史的真实同步：桥接器缺持久化是架构缺口（需在每次状态变更时把 DreamAgentNetworkState 序列化落盘）。首次发现时向用户报告一次即可，不要每小时重复上报。
- 3-EVOLUTION README 自述「实验状态，未集成到主线」——不要假设它已接入交易系统。

## 桥接器机制（存在活跃状态时使用）

- 任务生命周期：registered → claimed → in_progress → validated → ledgered（validate 失败退回 claimed）。
- 奖励分配：developer 60% / validator 20% / governance 20% × reward_estimate（small=100、medium=500、large=2000 DREAM）。
- block_height 在 finalizeTask 时 +1；total_dream_rewarded 累加所有发放。
- 超时升级：审批单走 ApprovalBridge.autoApproveIfEligible（默认 approval_timeout_minutes=30），orchestrator.processApprovalTimeout 触发，design 过 Gate1、kickoff 过 Gate2 并注册 Dream-Agent 任务。
- 编排链路：passGate2(approved) → registerDreamAgentTask → evolution 进入 collaboration 阶段；completeDreamAgentTask → finalizeTask → DZE completeChain → evolution completed。

## 仓库地图

详见 `references/3-evolution-architecture.md`（文件职责表、9 阶段流水线、触发源、DreamOS Python 生态对照、协作监督规则位置）。
