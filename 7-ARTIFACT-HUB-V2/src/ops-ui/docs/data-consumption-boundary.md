# ops-ui 数据消费边界文档

本文档定义 ops-ui 三类卡片（Health / Trace / Workflow）的数据消费明确边界，包括字段消费清单、空态规则、错误态规则及 mock→real 切换路径。

## 概述

| 卡片类型 | Contract | ViewModel | 字段消费数 | 全字段消费率 |
|---------|----------|-----------|----------|-----------|
| Health | HealthContractV1 | HealthViewModel | 3 | 100% |
| Trace | TraceContractV1 | TraceViewModel | 8 | 100% + 计算字段 |
| Workflow | WorkflowContractV1 | WorkflowViewModel | 5 | 100% |

---

## 1. Health 卡片

### Contract → ViewModel 映射

| Contract 字段 | ViewModel 字段 | 消费状态 | 说明 |
|-------------|---------------|--------|------|
| `service` | `service` | ✅ 已消费 | 服务名称，直接透传 |
| `status` | `status` | ✅ 已消费 | 健康状态（ok/degraded/error），直接透传 |
| `timestamp` | `timestamp` | ✅ 已消费 | 健康检查时间戳，直接透传 |
| `dependencies` | `dependencyList` | ✅ 已消费 | 依赖项对象 → 数组转换 |

### ViewModel 页面消费清单

| 字段 | 类型 | 使用场景 | 渲染规则 |
|-----|-----|--------|--------|
| `service` | string | 卡片标题 | 必填，无值时显示 "Unknown Service" |
| `status` | enum | 卡片状态指示器 | 色值映射：ok→绿，degraded→黄，error→红 |
| `timestamp` | string | 更新时间显示 | 格式化为本地时间 |
| `dependencyList` | Array | 依赖项列表 | 循环渲染，每个依赖显示名称+状态 |

### 不消费的字段

**ContractV1 中无额外未消费字段** — 所有字段均已被 ViewModel 消费。

### 空态规则

| 字段 | 空值情况 | 页面展示 |
|-----|--------|--------|
| `service` | null/undefined | "Unknown Service" |
| `status` | null/undefined | "unknown"（新增状态值） |
| `timestamp` | null/undefined | "——"（占位符） |
| `dependencyList` | []（空数组） | "无依赖信息"（占位符） |
| 依赖项 `status` | "unknown" | 灰色圆点 + "Unknown" 标签 |

### 错误态规则

| 错误场景 | 显示内容 | 备注 |
|--------|--------|------|
| API 返回错误 | 显示上次成功的缓存数据（如有）+ "数据可能已过期" 提示 | 容错策略 |
| 无缓存 + API 失败 | "服务暂不可用" | 明确错误状态 |
| 部分依赖失败 | 成功项正常显示，失败项显示 "unknown" | 容错粒度 |

### mock → real 切换路径

```
页面层（health-card.vue / health-card.tsx）
  ↓ 依赖注入（adapter pattern）
  ↓
当前: mockHealthAdapter → 返回模拟 HealthViewModel
未来: realHealthAdapter  → 调用 API 返回真实 HealthViewModel
  ↓
HealthViewModel（不变）
  ↓
页面层展示逻辑（不变）
```

**替换步骤：**
1. 在环境配置中添加 `HEALTH_DATA_SOURCE: "mock" | "real"`
2. 根据配置动态选择 adapter（mockHealthAdapter vs. realHealthAdapter）
3. realHealthAdapter 实现 HTTP GET `/api/health` 调用
4. 转换响应为 HealthContractV1，再通过 `toHealthViewModel()` 转换
5. 本地测试通过后，将配置切为 "real" 即可全量灰度

---

## 2. Trace 卡片

### Contract → ViewModel 映射

| Contract 字段 | ViewModel 字段 | 消费状态 | 说明 |
|-------------|---------------|--------|------|
| `trace_id` | `traceId` | ✅ 已消费 | 链路 ID，驼峰转换 |
| `status` | `status` | ✅ 已消费 | 链路状态，直接透传 |
| `workflow_id` | `workflowId` | ✅ 已消费 | 工作流 ID，驼峰转换 |
| `workflow_type` | `workflowType` | ✅ 已消费 | 工作流类型，驼峰转换 |
| `department` | `department` | ✅ 已消费 | 部门，直接透传 |
| `started_at` | `startedAt` | ✅ 已消费 | 启动时间，驼峰转换 |
| `finished_at` | `finishedAt` | ✅ 已消费 | 完成时间，驼峰转换 |
| （计算字段） | `durationMs` | ✅ 已消费 | **在 adapter 中计算**：`finished_at - started_at` |

### ViewModel 页面消费清单

| 字段 | 类型 | 使用场景 | 渲染规则 |
|-----|-----|--------|--------|
| `traceId` | string | 链路标识 / 链接跳转 | 必填，可点击跳转到详情 |
| `status` | enum | 链路状态指示 | 色值映射：running→蓝，completed→绿，failed→红 |
| `workflowType` | string | 工作流类型标签 | 显示为 badge |
| `department` | string | 部门归属 | 小字体显示 |
| `startedAt` | string | 创建时间 | 格式化为相对时间（如 "2小时前"） |
| `durationMs` | number \| null | 耗时显示 | 仅当 `status === "completed"` 时显示（单位 ms→秒） |
| `workflowId` | string | 关联工作流（可选） | 点击可跳转到工作流卡片 |
| `finishedAt` | string \| null | 完成时间戳 | 一般不直接展示，用于计算 `durationMs` |

### 不消费的字段

**ContractV1 中无额外未消费字段** — 所有字段均已被 ViewModel 消费或用于计算。

### 空态规则

| 字段 | 空值情况 | 页面展示 |
|-----|--------|--------|
| `traceId` | null/undefined | "——"（占位符） |
| `status` | null/undefined | "unknown" |
| `workflowType` | null/undefined | "——" |
| `department` | null/undefined | "——" |
| `startedAt` | null/undefined | "——" |
| `finishedAt` | null/undefined | 不显示 |
| `durationMs` | null | 不显示（对应 `status !== "completed"`） |

### 错误态规则

| 错误场景 | 显示内容 | 备注 |
|--------|--------|------|
| API 返回错误 | 显示缓存数据 + "数据可能已过期" 提示 | 如无缓存显示 "链路加载失败" |
| 时间计算异常（finished_at < started_at） | `durationMs = null`，不显示耗时 | 页面容错 |
| 日期格式不符 ISO 8601 | `durationMs = null`，不显示耗时 | adapter 捕获异常，返回 null |

### mock → real 切换路径

```
页面层（trace-card.vue / trace-card.tsx）
  ↓ 依赖注入
  ↓
当前: mockTraceAdapter → 返回模拟 TraceViewModel（含计算 durationMs）
未来: realTraceAdapter  → 调用 API 返回真实 TraceViewModel
  ↓
TraceViewModel（包含计算字段 durationMs）
  ↓
页面层展示逻辑（不变）
```

**替换步骤：**
1. 在环境配置中添加 `TRACE_DATA_SOURCE: "mock" | "real"`
2. 根据配置动态选择 adapter（mockTraceAdapter vs. realTraceAdapter）
3. realTraceAdapter 实现 HTTP GET `/api/traces/{id}` 调用
4. 转换响应为 TraceContractV1，通过 `toTraceViewModel()` 计算 `durationMs`
5. 关键点：adapter 层负责时间差计算，页面层无需感知计算逻辑
6. 本地测试通过后切换配置为 "real"

---

## 3. Workflow 卡片

### Contract → ViewModel 映射

| Contract 字段 | ViewModel 字段 | 消费状态 | 说明 |
|-------------|---------------|--------|------|
| `workflow_id` | `workflowId` | ✅ 已消费 | 工作流 ID，驼峰转换 |
| `workflow_type` | `workflowType` | ✅ 已消费 | 工作流类型，驼峰转换 |
| `chain_phase` | `chainPhase` | ✅ 已消费 | 链阶段（A0-A9），驼峰转换 |
| `status` | `status` | ✅ 已消费 | 工作流状态，直接透传 |
| `latest_trace_id` | `latestTraceId` | ✅ 已消费 | 最新链路 ID，驼峰转换 |

### ViewModel 页面消费清单

| 字段 | 类型 | 使用场景 | 渲染规则 |
|-----|-----|--------|--------|
| `workflowId` | string | 工作流标识 / 链接跳转 | 必填，可点击跳转到详情 |
| `workflowType` | string | 工作流类型标签 | 显示为 badge |
| `chainPhase` | string (A0-A9) | 链进度指示器 | 10 个步骤进度条 |
| `status` | enum | 工作流状态 | 色值映射：pending→灰，running→蓝，completed→绿，failed→红 |
| `latestTraceId` | string \| null | 最新执行链接 | 可点击跳转到 Trace 卡片详情 |

### 不消费的字段

**ContractV1 中无额外未消费字段** — 所有字段均已被 ViewModel 消费。

### 空态规则

| 字段 | 空值情况 | 页面展示 |
|-----|--------|--------|
| `workflowId` | null/undefined | "——"（占位符） |
| `workflowType` | null/undefined | "——" |
| `chainPhase` | null/undefined | "——" 或归档为 "unknown" |
| `status` | null/undefined | "unknown"（新增状态值） |
| `latestTraceId` | null | 不显示"最新链路"链接 |

### 错误态规则

| 错误场景 | 显示内容 | 备注 |
|--------|--------|------|
| API 返回错误 | 显示缓存数据 + "数据可能已过期" 提示 | 如无缓存显示 "工作流加载失败" |
| `chainPhase` 值超出 A0-A9 范围 | 显示 "unknown" 或 "invalid" | adapter 校验 |
| `latestTraceId` 指向已删除的链路 | 显示 "无最新链路" | 页面容错 |

### mock → real 切换路径

```
页面层（workflow-card.vue / workflow-card.tsx）
  ↓ 依赖注入
  ↓
当前: mockWorkflowAdapter → 返回模拟 WorkflowViewModel
未来: realWorkflowAdapter  → 调用 API 返回真实 WorkflowViewModel
  ↓
WorkflowViewModel（不变）
  ↓
页面层展示逻辑（不变）
```

**替换步骤：**
1. 在环境配置中添加 `WORKFLOW_DATA_SOURCE: "mock" | "real"`
2. 根据配置动态选择 adapter（mockWorkflowAdapter vs. realWorkflowAdapter）
3. realWorkflowAdapter 实现 HTTP GET `/api/workflows/{id}` 调用
4. 转换响应为 WorkflowContractV1，通过 `toWorkflowViewModel()` 转换
5. 本地测试通过后切换配置为 "real"

---

## 总结

### 关键原则

1. **字段消费 100% 完整性**
   - 三类卡片的 Contract 中所有字段均已在 ViewModel 中被消费或用于计算
   - 无"冗余字段"现象

2. **适配器职责**
   - 类型转换（snake_case → camelCase）
   - 计算字段生成（如 Trace 的 `durationMs`）
   - 空值/错误处理（adapter 层应返回合法 ViewModel）

3. **页面层无感知**
   - 页面层只需关注 ViewModel 字段
   - mock/real 切换对页面逻辑完全透明

4. **容错策略**
   - 空值显示占位符或默认值
   - API 失败时展示缓存数据 + 过期提示
   - 计算异常返回 null 而非抛错

5. **mock→real 迁移路径**
   - 环境配置驱动 adapter 选择
   - 逻辑完全隔离在 adapter 层
   - 页面层、Contract、ViewModel 无需改动

---

**文档版本:** 1.0  
**最后更新:** 2026-05-17  
**维护方:** Claude Code (sub-agent C3)
