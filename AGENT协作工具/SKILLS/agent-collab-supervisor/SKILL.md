---
name: agent-collab-supervisor
description: 协作监督 SKILL。核验任务卡、评审记录、评论协议、测试证据与分支合规性。触发词：流程监督、监督检查、collab supervisor
version: "1.0"
created: "2026-05-17"
status: "draft"
---

# Agent Collaboration Supervisor

## 监督目标

- verify task card exists
- verify design review exists
- verify STARTED and DONE comments exist
- verify non-owner review exists
- verify test evidence exists
- verify branch policy is respected

## 输出结论

- SUPERVISION_PASS
- SUPERVISION_REWORK
- SUPERVISION_BLOCK
