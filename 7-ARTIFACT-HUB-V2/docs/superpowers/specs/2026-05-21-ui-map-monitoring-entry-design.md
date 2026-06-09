# UI Map Monitoring Entry Design

> Date: 2026-05-21
> Scope: `7-ARTIFACT-HUB-V2`
> Status: Ready for review

## 1. Goal

将 `http://127.0.0.1:3457/ui-map?node=feed` 固定为中游治理层的“监控地图入口”，让用户以稳定心智从 `3457` 进入 `3456` 上的真实监控页，而不是把真实内容继续塞回 `ops-ui`。

本次设计只解决一件事：

- `3457 /ui-map` 是入口地图
- `3456 /feed` 是真实内容监控页
- `3456 /chain` 是真实链路监控页

## 2. Product Positioning

### 2.1 `3457 /ui-map`

`/ui-map` 的职责是：

- 展示治理节点与页面关系
- 提供稳定、明确的监控入口
- 解释当前节点对应的真实监控目标
- 提供状态说明与上下文提示

`/ui-map` 不再承担以下职责：

- 渲染 `/feed` 的真实内容
- 渲染 `/chain` 的真实内容
- 代理真实内容页并伪装成同一服务

### 2.2 `3456 /feed`

`/feed` 是真实内容监控页，负责：

- 浏览产物
- 理解部门、阶段、类型、标签等分类语义
- 从内容视角进入治理上下文

### 2.3 `3456 /chain`

`/chain` 是真实链路监控页，负责：

- 观察 workflow / chain phase
- 查看 trace / task / result 的执行链路
- 从流程视角返回关联产物

### 2.4 两层心智

本设计明确固定两层用户心智：

- `3457 = 监控地图入口`
- `3456 = 真实监控页面`

如果用户要“看地图与入口”，去 `3457`。
如果用户要“看真实内容或真实链路”，去 `3456`。

## 3. Architecture Decision

选择方案 A 作为唯一方案：

- `3457 /ui-map` 继续做监控地图
- `feed` 节点主链接固定跳 `3456 /feed`
- `chain` 节点主链接固定跳 `3456 /chain`
- `ops-ui` 只负责入口、状态说明和上下文，不承载真实内容

### 3.1 边界冻结

边界必须冻结为：

- `ops-ui` 是入口层
- Hub 是真实内容与监控页承载层

因此以下方案明确不采用：

- 在 `3457` 上新增真实 `/feed` 内容镜像
- 在 `3457` 上新增真实 `/chain` 内容镜像
- 在 `ops-ui` 中通过代理把 Hub 内容伪装为本地页面

### 3.2 地址生成规则

`ui-map` 中所有真实监控入口统一基于 `HUB_URL` 生成。

默认规则：

- `HUB_URL = http://127.0.0.1:3456`
- `feed` 节点主入口 = `${HUB_URL}/feed`
- `chain` 节点主入口 = `${HUB_URL}/chain`

如果未来 Hub 地址变化，允许通过环境变量覆盖，但页面职责不变。

## 4. UX Design

### 4.1 入口语义

当用户打开 `http://127.0.0.1:3457/ui-map?node=feed` 时：

- 页面默认定位在地图视图
- `feed` 节点 Drawer 自动展开
- Drawer 首要动作是“进入 Feed 监控页”
- 点击后直接跳转到 `http://127.0.0.1:3456/feed`

当用户打开 `chain` 节点时：

- `chain` 节点 Drawer 自动展开
- Drawer 首要动作是“进入 Chain 监控页”
- 点击后直接跳转到 `http://127.0.0.1:3456/chain`

### 4.2 Drawer 内容结构

`feed` 与 `chain` 的 Drawer 统一收口为三部分：

1. 节点说明
2. 真实监控入口
3. 运行说明或状态提示

优先级从高到低如下：

- 主入口按钮
- 节点职责简述
- 当前目标地址
- 补充说明

### 4.3 文案原则

文案统一采用监控入口语义：

- “进入 Feed 监控页”
- “进入 Chain 监控页”
- “目标监控页当前不可达”
- “请检查 Hub 3456 是否已启动”

以下语义需要弱化或移除为主入口：

- `planned`
- `coming soon`
- `/feed/[category]`
- `/feed/[category]/[artifactId]`

这些内容如果仍保留，只能作为辅助说明，不能压过真实监控入口。

## 5. Code Structure

### 5.1 主要涉及文件

本设计主要落在以下文件：

- `src/ops-ui/ui-map.ts`
- `src/ops-ui/routes/index.ts`
- `OPS_UI_README.md`

### 5.2 `src/ops-ui/ui-map.ts`

需要完成的收口：

- 调整 `feed` 节点 Drawer 的主链接结构
- 调整 `chain` 节点 Drawer 的主链接结构
- 将节点描述从“原型展示”改成“监控入口说明”
- 降低 `planned` 路由在 `feed` 与 `chain` 节点中的视觉权重

### 5.3 `src/ops-ui/routes/index.ts`

保持当前职责，不新增内容代理逻辑：

- 读取 `HUB_URL`
- 生成 `feedBaseUrl`
- 将真实 Hub 地址传给 `renderUiMapHtml()`
- 输出 `/ui-map` 页面

此文件不应：

- 转发 `/feed` 内容
- 转发 `/chain` 内容
- 在 `ops-ui` 层拼接真实监控页 HTML

### 5.4 `OPS_UI_README.md`

文档需要显式写清：

- `3457` 是监控地图入口
- `3456` 是真实监控页服务
- `ui-map` 只负责进入真实页面，不替代真实页面

## 6. Runtime Rules

### 6.1 默认运行约定

默认本地约定如下：

- `ops-ui` 监听 `127.0.0.1:3457`
- Hub 监听 `127.0.0.1:3456`
- `ui-map` 中的真实监控入口指向 Hub

### 6.2 环境变量规则

优先使用：

- `HUB_URL`

仅在确有必要时才保留：

- `OPS_UI_FEED_BASE_URL`

但无论是否保留该变量，产品语义都不能变化：

- `ops-ui` 仍然只是入口层
- Hub 仍然是内容与监控承载层

## 7. Error Handling

### 7.1 `HUB_URL` 缺失或非法

当 `HUB_URL` 缺失或非法时：

- `/ui-map` 页面仍应可打开
- Drawer 不应生成错误的伪链接
- 页面应展示明确错误提示

### 7.2 Hub 未启动

当 `3456` 未启动时：

- `3457` 仍然保留“地图入口页”语义
- 可展示“目标监控页当前不可达”的提示
- 不尝试在 `3457` 本地接管内容渲染

### 7.3 问题定位原则

问题定位要保持清晰：

- 打不开地图，看 `3457`
- 打不开真实监控页，看 `3456`
- 不把入口问题和内容问题混在一起

## 8. Acceptance Criteria

以下条件同时满足时，视为本设计通过：

- 打开 `http://127.0.0.1:3457/ui-map?node=feed` 时，默认展开 `feed` Drawer
- `feed` Drawer 的首要动作一跳进入 `http://127.0.0.1:3456/feed`
- `chain` Drawer 的首要动作一跳进入 `http://127.0.0.1:3456/chain`
- 用户能明确理解 `3457 = 地图入口`、`3456 = 真实监控页`
- `ops-ui` 页面与文档中不再暗示其承载真实 `/feed` 或 `/chain` 内容
- `planned` 类型入口不再作为 `feed` 与 `chain` 的主导航

## 9. Out Of Scope

本次设计不包含：

- 重写 `/feed` 或 `/chain` 真实页面本身
- 为 `ops-ui` 增加 `/feed` 或 `/chain` 内容代理
- 扩展 board / market / approval 等其它业务入口
- 新增前端框架或 SPA 结构

## 10. One-Sentence Conclusion

本设计将 `3457 /ui-map` 冻结为“监控地图入口”，并把 `3456 /feed` 与 `3456 /chain` 冻结为真实监控页，从而让中游治理入口与真实监控承载层形成清晰、稳定、可解释的两层结构。
