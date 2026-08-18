# Product Hub Docs Hard Cleanup Design

> Date: 2026-05-22
> Scope: `7-产物中台/docs`
> Status: Ready for review

## 1. Goal

本设计用于正式定义 `7-产物中台/docs` 的强力清理方案。

这次清理的目标不是做“文档整理美化”，而是直接把 `docs` 收口成只服务当前中台主线的最小文档集合。

本轮要求明确为：

- 只保留当前主线文档
- 其他旧文档大幅删除
- 不继续让旧中台方案、旧规划文档、已被替代的实施计划占据主区
- 仅保留极少数治理文档和必要索引文档

## 2. Cleanup Principle

本轮采用：

- `强力清理`

这意味着：

- 不是把旧文档搬到复杂的归档层级里继续保留可见性
- 也不是继续维护一大批“也许以后还会看”的历史文档
- 而是直接让主区只保留当前有效主线

旧文档如需追溯，原则上依赖：

- `git` 历史

而不是继续长期占据当前主区。

## 3. Keep Set

本轮清理后，`7-产物中台/docs` 主区只保留以下文档。

### 3.1 Current Hub Mainline

保留当前中台主线的 4 份核心文档：

- `2026-05-22-ui-map-independent-hub-main-map-design.md`
- `2026-05-22-ui-map-independent-hub-main-map-implementation.md`
- `2026-05-22-product-hub-directory-migration-design.md`
- `2026-05-22-product-hub-directory-migration-implementation.md`

它们分别对应：

- `ui-map` 独立中台首页主图
- `ui-map` 当前实施路线
- 中台目录归位迁移设计
- 中台目录归位迁移实施计划

### 3.2 Governance Documents

保留顶层治理文档：

- `ENGINEERING_INDEX.md`
- `FAQ.md`

它们的职责是：

- 为当前中台主线提供工程索引
- 为当前中台主线提供 FAQ 入口

### 3.3 Conditional Keep

对于：

- `PROJECT_PLAN.md`

本轮不默认保留现状。

它只能二选一：

1. 如果内容已经改写为“当前中台主线总计划”，则保留
2. 如果内容仍然是旧中台口径，则删除

也就是说：

- `PROJECT_PLAN.md` 不是天然保留项
- 它是否保留取决于内容是否已经对齐当前主线

## 4. Remove Set

本轮建议从主区清除以下文档。

### 4.1 Replaced By Current Hub Direction

以下文档已被当前中台方向替代：

- `2026-05-22-dashboard-main-panel-prototype-implementation.md`
- `2026-05-22-artifact-hub-main-chain-acceptance-design.md`

原因：

- 它们建立在旧的 `artifact hub` 语义或 `dashboard` 主入口优先的方向上
- 当前已经被“`ui-map` 独立中台首页 + 中台目录归位”主线替代

### 4.2 All `legacy-hub-*` Documents

以下所有 `legacy-hub-*` 文档都应从主区移除：

- `2026-05-21-legacy-hub-data-foundation-design.md`
- `2026-05-21-legacy-hub-data-foundation-implementation.md`
- `2026-05-21-legacy-hub-feed-chain-relation-design.md`
- `2026-05-21-legacy-hub-feed-chain-relation-implementation.md`
- `2026-05-21-legacy-hub-realtime-skeleton-implementation.md`

原因：

- 它们属于旧中台阶段
- 文档命名本身已经表明其“legacy”属性
- 不适合作为当前主区文档继续存在

### 4.3 Old Trading-Phase Documents Outside Current Hub Scope

以下旧交易主线文档不再保留在当前中台主区：

- `2026-05-21-development-demo-user-fallback-design.md`
- `2026-05-21-development-demo-user-fallback-implementation.md`
- `2026-05-21-frontend-driven-strategy-task-order-design.md`
- `2026-05-21-frontend-driven-strategy-task-order-implementation.md`

原因：

- 它们并非完全无价值
- 但它们属于前一阶段交易专项实现
- 当前不再属于 `7-产物中台/docs` 的核心主区范围

## 5. Archive Strategy

本轮不建议保留一整套复杂 archive 目录。

推荐采用：

- `极简归档`

也就是只保留一个：

- `archive/README.md`

用于说明：

- 旧文档已从主区清除
- 如需追溯，请通过 `git` 历史查看

这意味着：

- 不再为旧文档建立大规模 archive 子目录
- 不继续给旧方案文档高可见度

## 6. Final Target State

强力清理完成后，主区应收口为：

### A. `docs/superpowers/specs`

仅保留：

- `2026-05-22-ui-map-independent-hub-main-map-design.md`
- `2026-05-22-product-hub-directory-migration-design.md`

### B. `docs/superpowers/plans`

仅保留：

- `2026-05-22-ui-map-independent-hub-main-map-implementation.md`
- `2026-05-22-product-hub-directory-migration-implementation.md`

### C. `docs` 顶层

保留：

- `ENGINEERING_INDEX.md`
- `FAQ.md`
- `PROJECT_PLAN.md`（仅当内容已更新为当前主线）

### D. `docs/archive`

最多保留：

- `README.md`

## 7. Why Hard Cleanup Is Better Here

当前中台刚完成目录归位：

- 总容器已明确
- 老中台已归位为 `系统研究索引体系`
- 新模块骨架已建立

此时如果还继续保留大量旧文档，会立刻出现新的治理问题：

- 当前主线不突出
- 旧文档继续干扰工程判断
- 新成员进入项目后很难分清哪些文档还有效
- 文档目录重新变成“历史堆积区”

因此，在这个时点做强力清理，收益最大，治理成本最低。

## 8. Constraints

本轮必须遵守以下约束：

- 不把“强力清理”变成“边删边改内容”
- 不在没有明确保留标准的情况下保留旧文档
- 不继续维护复杂 archive 层级
- 只有当前主线文档可以留在主区

## 9. Final Statement

本轮最终结论明确为：

- `7-产物中台/docs` 主区只保留当前中台主线文档
- 旧中台规划文档、旧实现方案、旧交易阶段专项文档全部从主区清走
- 顶层只保留 `ENGINEERING_INDEX.md`、`FAQ.md`，以及内容已对齐当前主线的 `PROJECT_PLAN.md`
- 旧文档追溯原则上依赖 `git` 历史
- 如需保留归档位，最多只保留一个 `archive/README.md`
