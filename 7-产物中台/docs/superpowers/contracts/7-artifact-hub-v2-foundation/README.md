# 7-ARTIFACT-HUB-V2 Foundation Contracts

**Status:** `L1 协作接口`
**Frozen At:** 2026-05-16

**Purpose:** 为双代理第一轮并行开发提供最小冻结读接口样例。

## Included Contracts

| 契约名 | 文件 | 级别 | Owner |
|--------|------|------|-------|
| health-summary.v1 | `health-summary.v1.json` | L1 | solo |
| trace-summary.v1 | `trace-summary.v1.json` | L1 | solo |
| route-decision-summary.v1 | `route-decision-summary.v1.json` | L1 | solo |
| workflow-summary.v1 | `workflow-summary.v1.json` | L1 | solo |

## Rules
- 当前只冻结最小读接口 shape
- 未写入本目录的字段，不默认开放给页面依赖
- 若需改动字段，先更新 spec 与任务板，再修改样例
- Claude Code 页面层只读消费，不得直接修改本目录文件
