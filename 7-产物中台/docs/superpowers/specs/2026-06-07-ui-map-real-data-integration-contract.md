# UI-Map Real Data Integration Contract

> Date: 2026-06-07
> Updated: 2026-06-10（补充策略主线 summary-only 接入状态）
> Scope: `7-产物中台/系统研究索引体系/app/ui-map`
> Status: In progress — Phase B 真实数据接入已覆盖系统研究索引、研究链路、运营链路、策略主线（summary-only）

## 1. Goal

本文档用于补齐 `ui-map` 从“前端壳”进入“真实中台数据接入”阶段时的正式边界约束。

本契约要回答的问题不是“ui-map 长什么样”，而是：

- 现在的 `ui-map` 壳能接哪些真实数据
- 这些真实数据应该从哪里接入
- 哪些数据必须走服务端聚合，不能在客户端直接读取
- `ui-map` 与 `/chat`、`/dashboard` 的职责边界是什么
- 当真实数据暂时不齐时，壳与真实数据如何共存

## 2. Product Boundary

先明确三个页面/系统的边界：

- `/chat`
  - 用户主入口
  - 后续正式能力承接以对话窗为主
- `/dashboard`
  - 内部调试/展示页
  - 用于中台能力联调、状态观察、研发验收
- `/ui-map`
  - 中台结构地图
  - 用于表达能力关系、数据来源、统一主线、索引底座和透视链路

因此，`ui-map` 的真实数据接入目标不是替代 `/chat`，也不是演变成对外首页，而是：

- 把中台结构从静态语义图推进到“有真实数据支撑的结构地图”
- 为研发和中台建设提供可验证的结构视图

## 3. Current State

当前 `ui-map` 已经具备以下能力：

- 路由入口已存在：`系统研究索引体系/app/ui-map/page.tsx`（服务端装配入口，调用三个真实数据 adapter）
- 页面壳已存在：`系统研究索引体系/app/ui-map/UIMapShell.tsx`
- 客户端壳已存在：`系统研究索引体系/app/ui-map/UIMapClient.tsx`
- 壳层 view-model 已存在：`系统研究索引体系/app/ui-map/ui-map-shell-view-model.ts`（支持 fixture / real-data 双入口）
- 场景 fixture 已存在：`系统研究索引体系/app/ui-map/ui-map-scenarios.ts`（继续承担降级模式）
- 真实数据 adapter 已存在：`系统研究索引体系/lib/ui-map-real-data.ts`（三个 adapter：系统研究索引、研究链路、运营链路）

这意味着当前阶段属于：

- `Phase A`: 前端壳与语义结构已稳定
- `Phase B`: 真实数据接入已部分落地（系统研究索引、研究链路、运营链路）
- `Phase B 待落地`: 策略主线（summary-only）已上线；用户上下文索引系统仍待定义

## 4. Integration Principle

真实数据接入必须遵守以下原则：

### 4.1 壳层继续纯展示

`UIMapShell.tsx` 继续保持纯展示职责：

- 不直接读取文件系统
- 不直接发起中台数据请求
- 不承担跨模块聚合逻辑

它只消费已经整理好的 view-model。

### 4.2 聚合逻辑必须在服务端

`ui-map` 所需的真实数据来自多个来源，因此聚合必须在服务端完成。

不允许：

- 在客户端直接读取 `artifacts` 文件系统
- 在客户端直接拼装“系统研究 + 实时事件 + 用户上下文”多源数据
- 在组件内部硬编码真实数据源路径

### 4.3 Scenario 继续保留为降级模式

即便进入真实数据接入阶段，也不能删除当前场景 fixture。

场景数据继续承担：

- 本地无数据时的降级模式
- 设计回归与语义测试
- 多场景模拟与压力测试

### 4.4 先接稳定数据，再接高波动数据

真实接入顺序必须是：

1. `系统研究索引体系`
2. `系统运营链路`
3. `策略主线`
4. `用户上下文索引系统`

原因是前两者已有更明确的现有锚点，后两者仍需要额外中台契约。

## 5. Source Of Truth Mapping

### 5.1 系统研究索引体系

这是 `ui-map` 第一批最适合接入的真实数据。

当前可复用锚点：

- `系统研究索引体系/lib/content.server.ts`
- `系统研究索引体系/lib/ui-map-real-data.ts` → `buildSystemResearchUIMapOverride()`

该模块已提供：

- `getArtifactsIndex()`
- `getArtifactsData()`
- `getArtifactRelations()`
- `getChainPhaseArtifacts()`

已实现能力：

- 生成 `系统研究索引体系` 卡片所需摘要（产物数、部门数、阶段数）
- 生成系统研究链路的阶段关系与产物关系
- 无数据时自动降级为 Phase A 壳层语义

本模块的正式职责是：

- 生成 `系统研究索引体系` 卡片所需摘要
- 生成 `系统研究链路` 的阶段关系与产物关系
- 为后续系统策略来源提供“真实研究结果存在性”证据

### 5.2 系统研究链路（透视层）

这是 `系统研究索引体系` 的透视延伸模块，已在 Phase B 中与系统研究索引一起落地。

当前可复用锚点：

- `系统研究索引体系/lib/ui-map-real-data.ts` → `buildResearchChainUIMapOverride()`
- 底层数据来自 `content.server.ts` 的 `getArtifactRelations()` + `getChainPhaseArtifacts()`

已实现能力：

- 按阶段分组展示研究产物关系
- 展示阶段覆盖与每个阶段的产物数量
- 无关系数据时降级为空壳卡片

### 5.3 系统运营链路

这是第二批适合接入的真实数据，已在 Phase B 中落地。

当前可复用锚点：

- `系统研究索引体系/lib/realtime-hub.ts`
- `系统研究索引体系/lib/ui-map-real-data.ts` → `buildOperationsUIMapOverride()`

该模块已提供：

- `publish()`
- `subscribe()`
- `getRecentEvents()`

已实现能力：

- 从 `realtime-hub` 读取最近事件
- 按通道（dream-agent / meeting / system）汇总事件数量与最近时间戳
- 无事件时自动降级为空壳卡片
- 作为“前端进入 -> 策略收口 -> 执行 -> 结果入索引”这条透视链的实时事件来源

### 5.4 策略主线

`策略主线` 是业务核心，当前已提供 **summary-only** 级的真实数据接入。

- 当前可复用锚点：
  - `系统研究索引体系/lib/ui-map-real-data.ts` → `buildStrategyUIMapOverride()`
  - 底层数据来自 `content.server.ts` → `getArtifactsData()` 的 `statistics.by_type["strategy"]` 统计

- 已实现能力：
  - 基于 artifacts 索引的 `type=strategy` 统计汇总产物数量与状态分布
  - 显式标记为 `summary-only`，不透出敏感配置或执行状态
  - 无策略类型产物时自动降级为 view-model 层固定语义

- 待完善（不阻塞当前阶段）：
  - 标准对象定义：`strategy_setting_result` / `strategy_task_ticket` / `execution_status` / `result_artifact_reference`
  - 待上述标准对象成型后，可升级为完整的策略主线接入

### 5.5 用户上下文索引系统

该模块当前在设计层面是清楚的，但真实数据锚点尚不如系统研究索引稳定。

正式接入前至少需要明确：

- 用户配置数据从哪里读取
- 哪些字段可进入结构地图
- 哪些属于敏感信息不能直接展示

在这些字段未定前，只允许保留摘要级展示，不接真实敏感配置。

## 6. Server Adapter Boundary

`ui-map` 的真实数据接入通过一个集中的服务端 adapter 层完成。该层已在 `系统研究索引体系/lib/ui-map-real-data.ts` 中落地，包含四个 adapter：

- `buildSystemResearchUIMapOverride()` → 系统研究索引摘要
- `buildResearchChainUIMapOverride()` → 研究链路阶段与关系摘要
- `buildOperationsUIMapOverride()` → 运营事件通道摘要
- `buildStrategyUIMapOverride()` → 策略主线 summary-only 摘要（基于 artifacts 索引 `type=strategy`）

adapters 职责如下：

- 从 `content.server.ts` 读取系统研究索引与关系数据（已实现）
- 从 `realtime-hub.ts` 读取实时事件数据（已实现）
- 从 `content.server.ts` 读取策略主线摘要（已实现，summary-only）
- 在可用时读取用户上下文摘要（待实现）
- 统一生成 `UIMapShellViewModel` 所需的 override 对象（null 表示“降级为 fixture”）

固定边界（代码现状已对齐，遵循以下约束）：

- `UIMapShell.tsx`
  - 只负责展示，不直接碰数据
- `UIMapClient.tsx`
  - 只负责场景切换和客户端交互
- `ui-map-shell-view-model.ts`
  - 继续承接 view-model 生成，已实现“fixture mode / real-data mode”双入口（通过 `overrides` 对象）
- `lib/ui-map-real-data.ts`
  - 承接真实数据聚合与降级判断
- `app/ui-map/page.tsx`
  - 作为服务端装配入口，负责调用四个 adapter 并传入 view-model

## 7. Real Data Mode Contract

建议后续把 `ui-map` 的数据模式显式分成两种：

### 7.1 Fixture Mode

用于：

- 本地开发
- 无数据环境
- 设计回归
- 场景模拟

输出来源：

- `ui-map-scenarios.ts`

### 7.2 Real Data Mode

用于：

- 中台真实联调
- 数据接入验证
- 关系透视验收

输出来源：

- `content.server.ts`
- `realtime-hub.ts`
- 后续策略主线服务
- 后续用户上下文摘要服务

## 8. Acceptance Boundary

真实数据接入完成，不以“页面有数据”为完成标准，而以以下条件为准。当前已达成部分已标注 ✅，未达成部分标注 ⏳。

### 8.1 系统研究索引体系 ✅

- 页面卡片能展示真实系统研究摘要
- 页面能根据真实关系数据渲染研究链路摘要
- 不再完全依赖 fixture 才能展示该模块

### 8.2 系统研究链路（透视层）✅

- 页面能根据真实关系数据渲染阶段分组摘要
- 能展示阶段覆盖与每阶段产物数量
- 无关系数据时能降级为空壳卡片而不崩溃

### 8.3 系统运营链路 ✅

- 页面能展示最近事件或最近状态变化
- 按通道（dream-agent / meeting / system）汇总事件数量与最近时间戳
- 实时数据源断开时，页面能降级而不是崩溃

### 8.4 策略主线 ✅（summary-only，基于 artifacts 索引）

- 页面展示的主线状态来自 artifacts 索引的 `type=strategy` 统计（摘要级）
- 显式标记为 `summary-only`；敏感配置与执行状态未透出
- 统一标准对象（`strategy_setting_result` / `strategy_task_ticket` / `execution_status` / `result_artifact_reference`）仍待后续正式契约落地
- 真实数据 adapter：`buildStrategyUIMapOverride()`（`ui-map-real-data.ts`）
- 降级行为：无 `type=strategy` 产物时自动回退为 view-model 层固定语义

### 8.5 用户上下文索引系统 ⏳

- 只能展示经过脱敏和摘要化的上下文信息
- 不允许把敏感配置直接透出到 `ui-map`
- 需先明确用户配置读取路径与可暴露字段边界

## 9. Explicit Non-Goals

本契约明确不做以下事情：

- 不让 `ui-map` 直接承担用户操作入口职责
- 不把 `/dashboard` 的调试状态原样搬成 `ui-map` 的唯一数据源
- 不在客户端直接消费文件系统或多源中台数据
- 不在本阶段一次性打通所有模块真实数据

## 10. Recommended Phase B Order

真实数据接入按以下顺序推进：

1. `系统研究索引体系` ✅
   - 复用 `content.server.ts`，由 `buildSystemResearchUIMapOverride()` 提供
2. `系统研究链路` ✅
   - 复用 artifact relations / chain phase 数据，由 `buildResearchChainUIMapOverride()` 提供
3. `系统运营链路` ✅
   - 接 `realtime-hub.ts`，由 `buildOperationsUIMapOverride()` 提供
4. `策略主线` ✅（summary-only）
   - 接 artifacts 索引的 `type=strategy` 统计，由 `buildStrategyUIMapOverride()` 提供
   - 敏感配置、执行状态等尚未透出，仅作为摘要级接入
5. `用户上下文索引系统` ⏳
   - 先定义脱敏摘要与敏感字段边界，再接真实数据

## 11. Reader Shortcut

如果协作者只想快速知道“接哪里”，请直接记住：

- 壳继续在 `app/ui-map/`
- 真实研究数据先接 `lib/content.server.ts`
- 真实运营事件先接 `lib/realtime-hub.ts`
- 真实数据聚合由 `lib/ui-map-real-data.ts` 中四个 adapter 完成
  - `buildSystemResearchUIMapOverride()` → 系统研究索引摘要
  - `buildResearchChainUIMapOverride()` → 研究链路阶段与关系摘要
  - `buildOperationsUIMapOverride()` → 运营事件通道摘要
  - `buildStrategyUIMapOverride()` → 策略主线 summary-only 摘要（基于 `type=strategy` 统计）
- `page.tsx` 负责服务端装配（调用四个 adapter 并传入 view-model）
- `ui-map-shell-view-model.ts` 支持 fixture / real-data 双入口（通过 `overrides` 对象，null 表示降级）
- `UIMapShell.tsx` 不直接碰真实数据源
- `scenario` 不能删，只能作为降级模式继续存在
