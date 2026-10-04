# Changelog

本文件记录 DreamBuddy V2 的版本演进与能力变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [v0.2.0] — 2026-10-04 — 能力回归修复 + 版本管理基线

### 能力回归修复（用户反馈的 4 项）

- **报告生成**: 新增 `POST /api/reports/generate` 路由（读 task result → 组装 markdown → 写入 `~/.workbuddy/artifacts/trading/` → 更新 `index.json`）；[ReportsScreen.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/features/reports/ReportsScreen.tsx) 加"生成报告"按钮 + 状态提示
- **交易榜单**: 侧边栏加 `/dashboard/ranking` 入口（页面已存在 [page.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/app/dashboard/ranking/page.tsx)，仅缺导航）
- **人工审批**: 侧边栏加 `/board/approval` 入口（页面已存在，仅缺导航）
- **人工干预**: `/dashboard/trade` 接入 [SteerPanel.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/features/chat/SteerPanel.tsx) 实时干预面板（跳过步骤 / 强制方向 / 覆盖置信度）

### 核心 Bug 修复

- **EPERM mkdir 越界写**: [task-manager.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/task-manager.ts) 的 `resolveRepoRoot()` 改用项目根特征（同时存在 `3.1-FRONTEND` + `1-ARCHITECTURE`）识别，`ARTIFACTS_DIR` 固定为 `REPO_ROOT/artifacts`；之前 fallback 跳到 `~/WorkBuddy` 触发沙箱 EPERM。同步修复 [dream-universal-gateway/src/lib/task-manager.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3-FRONTEND/dream-universal-gateway/src/lib/task-manager.ts)
- **market_query 误判为复杂趋势分析**: [fallback-engine.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/intent/fallback-engine.ts) 插入 Step 1.5 规则预过滤（confidence ≥ 0.85 直接返回，跳过 LLM）；[task-manager.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/task-manager.ts) 在 `ExecutionPlanner` 调用前插入 `market_query` 快速路径直接返回价格卡片（从 `CLARIFY_INTENTS` 移除 market_query）
- **Markdown 渲染倒退**: [MessageItem.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/features/chat/MessageItem.tsx) 引入 `ReactMarkdown`，assistant 消息走 markdown 渲染；之前用 `<span>{content}</span>` 平铺导致被压成单行（package.json 装了 `react-markdown@10.1.0` 但代码从未 import）

### 测试基建

- 新增 [jest.config.js](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/jest.config.js)（preset `ts-jest` + `moduleNameMapper` `@/`）
- [package.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/package.json) 加 `jest@^29` / `ts-jest@^29` / `@types/jest@^29` devDeps + `test` / `test:watch` / `test:intent` scripts
- 已有 `intent-multiround.test.ts` 39/39 通过（用 `npx tsx` 运行，非 jest 风格）

### 监控类型扩展

- [monitor-bus.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/monitor-bus.ts) `MonitorPhase` 加 `'rule_prefilter'` 和 `'jev_evaluated'`

### 版本管理梳理

- 13 个孤儿文件 `git add`（`board/` 全套页面 + API、`SteerPanel.tsx`）— 这些文件早已实现但从未 git commit
- 本 CHANGELOG.md 作为版本基线
- 打 `v0.2.0` tag（不 push）

### 类型兼容性

- TaskFile.updated_at 字段类型为 `string`，相关赋值改为 `new Date().toISOString()`（之前误用 `Date.now()` 数值）

## [v0.1.0] — 历史

- `df2b8b9373` feat(frontend): 修复 three-screens 回退 + 接入 api/mapper/charts
- `2c2895f0ba` fix(frontend): 接入 24 个孤儿组件，消除"组件存在但 page.tsx 未 import"问题
- `254d84e2a2` fix(fundamental): 接入 7 个 tab 真实数据，消除占位符
- `91901c4a82` feat: 代码层面全面对齐 — 交易引擎/认知系统/dream-harness-bridge
- `4998106532` feat: 非线性多阶段最优路径6机制联动 + 数据采集中心P0-P2 + 自进化架构升级
- `8cebe6b8e2` feat: 四层闭环进化架构 + 易经战略层增强 + BDSM/BCRM 协同 + 基本面7引擎 + 执行引擎中心
