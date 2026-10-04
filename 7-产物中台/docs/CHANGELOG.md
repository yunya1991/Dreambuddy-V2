# 7-产物中台 — 变更记录

> **文档版本**: v1.0  
> **更新日期**: 2026-09-30

---

## v1.0.0 — 2026-09-30

### 文档补齐
- 新建 [`README.md`](../README.md)：模块概述、目录结构、快速开始、核心功能表格、配置说明、相关文档
- 新建 [`docs/API_SPEC.md`](./API_SPEC.md)：HTTP API 接口签名、参数表、响应示例、错误码
- 新建 `docs/CHANGELOG.md`（本文件）

### 不变更
- 代码层面无修改，仅补建标准文档

---

## v0.2.0 — 2026-08-02

> 来源：[`package.json`](../系统研究索引体系/package.json) 版本 `0.2.0` 与 [`docs/TECHNICAL_DESIGN.md`](./TECHNICAL_DESIGN.md) v1.0

### 技术设计文档
- 补建 `docs/TECHNICAL_DESIGN.md` v1.0，对齐代码实现
- 标注 4 个 ui-map adapter（研究链路/运营链路/策略主线/用户上下文）为规划中
- 补全 API 路由清单与标准对象契约

### ui-map Phase B 真实数据接入
- 系统研究索引、研究链路、运营链路、策略主线、用户上下文索引五个模块接入真实数据
- 每个模块均具备 fixture 降级模式
- 策略主线支持 `StrategyFullView` 视图，小写 phase 标签归一化（a9→A9）
- 用户上下文索引支持 `UserContextFullView` 视图，敏感信息不透出

---

## v0.1.0 — 2026-06-11

> 来源：[`docs/ENGINEERING_INDEX.md`](./ENGINEERING_INDEX.md) ui-map 模块状态记录

### ui-map Phase A（壳层）
- 路由 `/ui-map`、`UIMapShell`、场景切换、语义分层验证通过
- `ui-map-shell-view-model.test.ts` 14 个测试通过

### ui-map Phase B（真实数据接入启动）
- 系统研究索引 adapter `buildSystemResearchUIMapOverride` 基于 `content.server.ts` 产物索引生成
- 真实数据注入与降级行为测试 `lib/ui-map-real-data.test.ts` 18 个测试通过

---

## v0.0.1 — 2026-05-14

> 来源：[`prisma/schema.prisma`](../系统研究索引体系/prisma/schema.prisma) 头部版本记录

### 初始实现
- 建立 Prisma Schema v1.0（基于 `USER_SYSTEM_DESIGN.md` v1.0）
- 核心数据模型：`User` / `UserProfile` / `ApiConfig` / `TradingParams` / `Strategy` / `ChannelConfig` / `CreditsAccount` / `CreditsTransaction` / `Order` / `VerificationCode` / `Session`
- 推荐引擎数据模型：`StrategyTask` / `StrategyTaskOrder` / `StrategyExecutionRun` / `StrategyBacktestRecord` / `RecommendationEngineLog`
- 数据源 `SQLite`，通过 `DATABASE_URL` 环境变量配置
