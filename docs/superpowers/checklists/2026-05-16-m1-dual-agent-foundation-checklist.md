# M1 Dual-Agent Foundation Checklist

**Milestone:** `M1 dual-agent-collaboration-foundation`

**Purpose:** 用 checklist 跟踪双代理协作底座是否已具备启动条件。

## K1 协作底座已写完
- [ ] 协作 spec 已存在
- [ ] 实施计划已存在
- [ ] 用户确认协作模式为"双代理分域自治"

## K2 最小契约已冻结
- [x] `health-summary.v1.json` 已创建
- [x] `trace-summary.v1.json` 已创建
- [x] `route-decision-summary.v1.json` 已创建
- [x] `workflow-summary.v1.json` 已创建
- [ ] 契约状态达到 `L1 协作接口`

## K3 双代理已完成第一次并行且无覆盖冲突
- [ ] SOLO 首批任务已明确
- [ ] Claude Code 首批任务已明确
- [ ] 默认执行模式已明确为 `PHASE_BROADCAST`
- [ ] 共享边界与强同步触发条件已写入任务板
- [ ] 白名单直接接管规则已写入任务板
- [ ] 至少完成一次 mock 联调准备

## K4 第一个功能里程碑准备启动
- [ ] 已建立 `milestone/dual-agent-foundation`
- [ ] 已确定下一功能优先级
- [ ] 已确认是否进入 `ops-ui` / `/feed` / `/chain`
- [ ] 当前任务卡或 PR 评论已声明 `Execution Mode`
- [ ] 若涉及接力修复，已声明 `Direct Takeover`
