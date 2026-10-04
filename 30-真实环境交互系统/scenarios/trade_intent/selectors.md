# Trade 页 DOM 选择器参考

> 探查日期: 2026-10-04
> 目标页: http://localhost:3001/dashboard/trade
> 探查工具: agent-browser (CDP)

## 已验证选择器

### 1. ChatPanel 输入框
- **标签**: `<textarea placeholder="输入你的问题...">`
- **class**: `w-full resize-none bg-gray-800/50 border`
- **Playwright 选择器**: `textarea[placeholder="输入你的问题..."]`
- **注意**: React 受控组件，需通过原生 setter 触发 input 事件：
  ```js
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  setter.call(textarea, 'text');
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  ```

### 2. 发送按钮
- **标签**: `<button>发送</button>`
- **Playwright 选择器**: `button:has-text("发送")`
- **状态**: 输入框为空时 disabled

### 3. S 层感知意图徽章（核心断言目标）
- **位置**: 聊天面板头部 `div.flex.items-center.justify-between.mb-3` 右侧
- **结构**:
  ```html
  <div class="flex items-center gap-2">
    <span class="text-xs text-slate-500">感知层:</span>
    <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium border bg-gray-700/50 text-gray-300 border-gray-600/30">
      <span class="relative flex h-1.5 w-1.5">...</span>
      {intent_value}
    </span>
  </div>
  ```
- **Playwright 选择器**: 定位包含 "感知层:" 的容器，取最后一个 span 的文本
  - 文本断言: `div.flex.items-center.justify-between.mb-3 >> text=感知层:`
  - 意图值: 该容器内最后一个 `span.inline-flex` 的文本
- **示例值**: `market_query`（BTC 价格查询场景）

### 4. SteerPanel（实时干预）
- **标题**: `🛡️ 实时干预`
- **包含按钮**: recall, debate, jeval, supplement, 多, 空, 中性, 提交干预
- **状态显示**: "空闲" 或 task ID（如 "task_202..."）
- **选择器**: `text=🛡️ 实时干预` 定位标题，向上找 section

### 5. ChainTracker（链路追踪）
- **标题**: `链路追踪`
- **空状态**: "暂无活跃链路" + "发起对话后可查看执行链路追踪"
- **选择器**: `text=链路追踪`
- **活跃链路断言**: 验证文本不含 "暂无活跃链路"

### 6. CrossValidationPanel（交叉验证）
- **标题**: `交叉验证`
- **子标题**: `三链投票`
- **空状态**: "未启用" + "发起复杂任务后自动启用三链交叉验证"
- **选择器**: `text=交叉验证`

### 7. 消息响应
- **意图标签**: 响应中包含 "链路: {intent}"（如 "链路: market_query"）
- **置信度**: "置信度 85%"
- **状态**: "已完成"
- **选择器**: `text=链路:` 定位意图标签

## 网络 API
- **消息发送**: `POST /api/task/stream` (SSE，200)
- **意图识别**: 前端调用后端 /api/task/stream，后端转发 DreamOS
- **认知统计**: `GET /api/cognitive/stats`

## 注意事项
1. S 层徽章仅在任务执行后显示，市场查询类意图也会显示（如 market_query）
2. ChainTracker 在 market_query 场景下可能不显示活跃链路（仅策略类意图触发 C/A 链）
3. 发送按钮在输入为空时 disabled，需先正确填充 textarea
