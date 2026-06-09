# Ops UI `/ui-map` 落地设计（Artifact Hub V2）

## 1. 背景与目标

目标：在 [/src/ops-ui/ui-map.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/ui-map.ts) 的现有视觉风格基础上，把 `GET /ui-map` 从“静态说明页”升级为“可用的治理信息架构地图页”，用于对齐 V2 产物中台页面结构，并作为后续治理控制台页面的导航与说明入口。

约束：

- 不引入前端框架与额外依赖（当前 ops-ui 依赖仅 express）。
- 继续采用服务端输出 HTML 字符串 + 少量原生 JS 的模式。
- 先落地 `/ui-map`（MVP），其它 ops 页面后续逐步实现。

## 2. 运行入口与端口

- 服务归属：`dreambuddy-v2/7-ARTIFACT-HUB-V2` 内的 `ops-ui` 子服务。
- 页面入口：`GET /ui-map`（在 ops-ui 路由中已有）。
- 默认端口：对齐需求使用 `3457` 作为 ops-ui 默认端口，支持通过 `OPS_UI_PORT` 覆盖。

涉及文件：

- [/src/ops-ui/server.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/server.ts)
- [/src/ops-ui/routes/index.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-ARTIFACT-HUB-V2/src/ops-ui/routes/index.ts)

## 3. 信息架构（确认结果）

### 3.1 页面总结构：方案 C（Tab 分区）

`/ui-map` 顶部提供三组 Tab：

- `Map`：页面层级总览（Feed/Ops/Query/Hub/Data 五节点画布）
- `Prototypes`：原型预览（沿用现有 wireframe + 子 Tab：Feed 首页/详情页/Ops 首页）
- `Docs`：文档与接口说明（包含 1/2/3/4 全部内容）

### 3.2 节点点击交互：右侧抽屉（Drawer）

在 `Map` Tab 内：

- 点击任意节点（Feed/Ops/Query/Hub/Data）打开右侧抽屉
- 抽屉不遮挡画布，可随时关闭
- 抽屉内容随节点切换动态更新

## 4. UI 组成（页面内区块）

### 4.1 顶部导航（全局）

在 `/ui-map` 页面顶部（hero 或 header 区）提供快捷导航与链接：

- `/`（Ops Home，如果当前实现未完整，先链接到现有页面或占位提示）
- `/ui-map`（当前页）
- `/health`
- `/api/ops/queues`
- `/api/ops/strategy-library`

### 4.2 Map Tab

复用现有“页面层级总览”画布节点布局（node + connector-layer）。

新增：

- 每个节点具备可点击区域（整块 node 可点）
- 节点 hover/active 样式（保持现有风格，增强可交互感）
- 右侧抽屉（drawer）组件：
  - 标题：节点名称
  - 描述：节点职责（短文）
  - Links：相关页面入口（如果存在）
  - APIs：关键 API 列表 + 示例请求（以代码块形式）
  - Status：`implemented / planned` 标签
  - Close：关闭按钮（Esc 关闭可选）

### 4.3 Prototypes Tab（选择 A：沿用现有 wireframe + 子 Tab）

复用现有“页面原型预览”区块：

- 子 Tab：Feed 首页 / 详情页 / Ops 首页
- 内容：wireframe 栅格（现有结构即可）

### 4.4 Docs Tab（选择 1/2/3/4 全部）

Docs Tab 必须包含：

1) 文档链接

- README / OPS_UI_README / 关键设计文档（以“文件路径 + 标题”形式展示；浏览器无法可靠打开 `file://` 时，优先展示路径供复制）

2) 页面路由清单

- `/`、`/ui-map`、`/health`、`/api/ops/*` 列表
- 每项包含：用途说明 + 实现状态（implemented/planned）

3) 环境变量

- `OPS_UI_PORT` / `OPS_UI_HOST`
- `HUB_URL` / `GATEWAY_URL`
- `OPS_ADMIN_TOKEN`（仅展示是否设置，不展示具体值）

4) 实现状态

- 明确标注：哪些入口已实现、哪些规划中（对齐 OPS_UI_README 的“规划中”口径）

## 5. 数据与状态来源（本阶段）

本阶段 `/ui-map` 主要是“信息架构地图页”，数据来源以静态说明为主：

- 节点抽屉中的 API 链接为“入口说明 + 示例”，不要求真实调用成功
- `/api/ops/*` 若当前已存在实现（queues/strategy-library），可在 Docs 中标注为 implemented，并提供示例响应片段（可选）

## 6. 可访问性与安全约束

- 不在页面上输出任何 secret 的真实值（如 `OPS_ADMIN_TOKEN` 只显示 `set/unset`）。
- Drawer 支持键盘关闭（Esc）属于增强项，可后置。

## 7. 验收标准（MVP）

- `GET /ui-map` 返回 200 且可在浏览器访问
- 页面存在 Map/Prototypes/Docs 三个 Tab，切换无刷新
- Map Tab：五大节点均可点击，点击后右侧抽屉打开且内容切换正确
- Prototypes Tab：展示 wireframe 子 Tab（Feed 首页/详情页/Ops 首页）
- Docs Tab：包含 文档链接 / 路由清单 / 环境变量 / 实现状态 四块内容
- ops-ui 默认端口与需求一致（默认 3457，可用环境变量覆盖）

