# UI-Map Real Data Integration Contract

> Date: 2026-06-07
> Scope: `7-产物中台/系统研究索引体系/app/ui-map`
> Status: Ready for implementation

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

- 路由入口已存在：`系统研究索引体系/app/ui-map/page.tsx`
- 页面壳已存在：`系统研究索引体系/app/ui-map/UIMapShell.tsx`
- 客户端壳已存在：`系统研究索引体系/app/ui-map/UIMapClient.tsx`
- 壳层 view-model 已存在：`系统研究索引体系/app/ui-map/ui-map-shell-view-model.ts`
- 当前数据仍以场景 fixture 为主：`系统研究索引体系/app/ui-map/ui-map-scenarios.ts`

这意味着当前阶段属于：

- `Phase A`: 前端壳与语义结构已成型
- `Phase B`: 真实数据接入尚未正式落地

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

该模块已提供：

- `getArtifactsIndex()`
- `getArtifactsData()`
- `getArtifactRelations()`
- `getChainPhaseArtifacts()`

因此，本模块的正式职责是：

- 生成 `系统研究索引体系` 卡片所需摘要
- 生成 `系统研究链路` 的阶段关系与产物关系
- 为后续系统策略来源提供“真实研究结果存在性”证据

### 5.2 系统运营链路

这是第二批适合接入的真实数据。

当前可复用锚点：

- `系统研究索引体系/lib/realtime-hub.ts`

该模块已提供：

- `publish()`
- `subscribe()`
- `getRecentEvents()`

因此，本模块的正式职责是：

- 为 `系统运营链路` 提供最近事件、状态变化、通道快照
- 作为“前端进入 -> 策略收口 -> 执行 -> 结果入索引”这条透视链的实时事件来源

### 5.3 策略主线

`策略主线` 是业务核心，但当前仍缺统一的真实数据契约。

在正式接入前，必须先定义标准对象：

- `strategy_setting_result`
- `strategy_task_ticket`
- `execution_status`
- `result_artifact_reference`

在这些对象没有成型前，`策略主线` 仍允许暂时使用 view-model 层的固定语义。

### 5.4 用户上下文索引系统

该模块当前在设计层面是清楚的，但真实数据锚点尚不如系统研究索引稳定。

正式接入前至少需要明确：

- 用户配置数据从哪里读取
- 哪些字段可进入结构地图
- 哪些属于敏感信息不能直接展示

在这些字段未定前，只允许保留摘要级展示，不接真实敏感配置。

## 6. Server Adapter Boundary

`ui-map` 的真实数据接入必须新增或复用一个服务端 adapter 层。

推荐职责如下：

- 读取系统研究索引数据
- 读取实时事件数据
- 在可用时读取策略主线摘要
- 在可用时读取用户上下文摘要
- 统一生成 `UIMapShellViewModel` 所需真实数据版本

建议边界如下：

- `UIMapShell.tsx`
  - 只负责展示
- `UIMapClient.tsx`
  - 只负责场景切换、模式切换和客户端交互
- `ui-map-shell-view-model.ts`
  - 继续承接 view-model 生成，但应允许“fixture mode / real-data mode”双入口
- `lib/*`
  - 继续承接底层数据读取
- `app/ui-map/page.tsx`
  - 作为服务端装配入口

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

真实数据接入完成，不以“页面有数据”为完成标准，而以以下条件为准：

### 8.1 系统研究索引体系

- 页面卡片能展示真实系统研究摘要
- 页面能根据真实关系数据渲染研究链路摘要
- 不再完全依赖 fixture 才能展示该模块

### 8.2 系统运营链路

- 页面能展示最近事件或最近状态变化
- 实时数据源断开时，页面能降级而不是崩溃

### 8.3 策略主线

- 页面展示的主线状态来自真实对象摘要，而不是纯固定文案
- 若真实对象暂不可用，应显式标记为 `summary-only` 或 `fixture-backed`

### 8.4 用户上下文索引系统

- 只能展示经过脱敏和摘要化的上下文信息
- 不允许把敏感配置直接透出到 `ui-map`

## 9. Explicit Non-Goals

本契约明确不做以下事情：

- 不让 `ui-map` 直接承担用户操作入口职责
- 不把 `/dashboard` 的调试状态原样搬成 `ui-map` 的唯一数据源
- 不在客户端直接消费文件系统或多源中台数据
- 不在本阶段一次性打通所有模块真实数据

## 10. Recommended Phase B Order

后续真实数据接入按以下顺序推进：

1. `系统研究索引体系`
   - 复用 `content.server.ts`
2. `系统研究链路`
   - 复用 artifact relations / chain phase 数据
3. `系统运营链路`
   - 接 `realtime-hub.ts`
4. `策略主线`
   - 先定义标准对象，再接真实摘要
5. `用户上下文索引系统`
   - 先定义脱敏摘要，再接真实数据

## 11. Reader Shortcut

如果协作者只想快速知道“接哪里”，请直接记住：

- 壳继续在 `app/ui-map/`
- 真实研究数据先接 `lib/content.server.ts`
- 真实运营事件先接 `lib/realtime-hub.ts`
- `page.tsx` 负责服务端装配
- `UIMapShell.tsx` 不直接碰真实数据源
- `scenario` 不能删，只能作为降级模式继续存在
