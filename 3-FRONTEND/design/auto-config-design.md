# 自动化配置设计文档

> 版本: v1.0 | 日期: 2026-05-15 | 状态: 已确认，待实现
> 位置: 左侧边栏 > 设置 > 🚀 自动化配置

---

## 1. 功能概述

在左侧边栏「⚙️ 设置」折叠组内新增「🚀 自动化配置」入口，用户点击后在 **聊天区域** 以 Claude 风格对话流依次引导配置 4 个核心模块，实现一键部署。

**配置队列（4步，不含大模型配置）**：

| 步骤 | 配置项 | 图标 | 对应 API |
|------|--------|------|---------|
| Step 1 | API配置 | ⚙️ | `/api/config/api-keys` |
| Step 2 | 交易设置 | 💰 | `/api/config/trading-params` |
| Step 3 | 策略设置 | 🎯 | `/api/config/strategies` |
| Step 4 | 通信渠道 | 📡 | `/api/config/channels` |

---

## 2. 入口设计

- **位置**：左侧边栏 `设置` 折叠组内，最后一个子项
- **代码位置**：`dashboard/page.tsx` 约第 3586 行，`📡 通信渠道` 之后新增
- **样式**：蓝色高亮 `#378ADD`，圆角 6px，与普通设置项区分
- **图标**：🚀

```tsx
// 新增行（在通信渠道之后）
<div className="collapsible-item" onClick={handleStartAutoConfig} style={{color:'#0066ff', fontWeight:600}}>
  🚀 自动化配置
</div>
```

---

## 3. 对话状态机

### 3.1 状态流转

```
[开始] → Step1(提问) → (是→输入框→保存) / (否→skipCount++)
                                  ↓
       skipCount < 2 → 下一步
       skipCount ≥ 2 → 退出确认
                          ├─ 是 → [结束]
                          └─ 否 → skipCount=0 → 下一步
                                  ↓
       Step2(提问) → ... → Step4(提问) → [完成摘要]
```

### 3.2 状态定义

```typescript
type AutoConfigPhase =
  | 'idle'           // 未激活
  | 'asking'         // AI提问：是否配置XXX？
  | 'inputting'      // 用户选"是"，等待填写输入框
  | 'exit_confirm'   // 连续2次否，询问是否退出
  | 'completed';     // 全部完成，展示摘要

interface AutoConfigState {
  phase: AutoConfigPhase;
  currentStep: number;        // 0-3 (4步)
  skipCount: number;          // 连续否计数
  results: AutoConfigResult[];// 每步结果
}

interface AutoConfigResult {
  step: number;
  key: string;                // 'api' | 'trading' | 'strategy' | 'channels'
  status: 'configured' | 'skipped' | 'error';
  data?: Record<string, unknown>;
  error?: string;
}
```

---

## 4. UI 交互设计

### 4.1 状态一：AI 提问

```
┌──────────────────────────────────┐
│ Dream Gateway                     │
│                                   │
│ 是否帮您配置「⚙️ API配置」？      │
└──────────────────────────────────┘
  [是]  [否]          ← 内联药丸按钮
```

- AI 消息：深色气泡 `#2C2C2A`，圆角 10px
- 「是」按钮：绿色药丸 `#1D9E75`，白色文字
- 「否」按钮：描边药丸，`#888780` 边框

### 4.2 状态二：配置输入框（用户选「是」后）

```
┌──────────────────────────────────────────┐
│ Dream Gateway                             │
│                                           │
│ 请填写 API 配置信息：                      │
│                                           │
│ Exchange Provider    [OKX ▼]              │
│ API Key              [sk-xxxxx...    ]    │
│ API Secret           [xxxxx...       ]    │
│ Passphrase           [xxxxx...       ]    │
│ 环境                 (●) Demo  ( ) Live   │
│                                           │
│                              [确认]        │
└──────────────────────────────────────────┘
```

- 表单嵌入 AI 气泡内部
- 输入框：深色背景 `#444441`，`#5F5E5A` 边框
- **确认按钮状态**：
  - 未填写时：灰色 `#444441`，文字 `#5F5E5A`
  - 有内容后：蓝色高亮 `#378ADD`，白色文字

### 4.3 状态三：退出确认（连续 2 次否）

```
用户: [否]
用户: [否]

┌──────────────────────────────────────┐
│ 是否帮您退出自动化配置？  (红色气泡)    │
└──────────────────────────────────────┘
  [是]  [否]
```

- 气泡背景：`#A32D2D`（红色告警）
- 选「是」→ 结束流程，展示已完成的摘要
- 选「否」→ skipCount 重置为 0，继续下一个配置项

---

## 5. 各步骤配置字段

### Step 1: ⚙️ API配置

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| provider | select | 是 | OKX |
| apiKey | input | 是 | API Key |
| apiSecret | input | 是 | API Secret |
| passphrase | input | 是 | Passphrase |
| environment | radio | 是 | Demo / Live |
| verify | button | - | 一键验证连接 |

保存 API: `POST /api/config/api-keys`
验证 API: `POST /api/config/api-keys/test`

### Step 2: 💰 交易设置

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| availableCapital | number | 否 | 可用资金 (USDT) |
| tradeType | radio | 是 | 现货 / 永续合约 |
| tradeMode | select | 是 | SPOT/SWAP/FUTURES/OPTIONS |
| leverageMax | range | 是 | 1x - 20x |
| dailyLossLimit | number | 是 | 每日亏损限制 (%) |
| riskTolerance | select | 是 | 保守 / 稳健 / 激进 |

保存 API: `PUT /api/config/trading-params`

### Step 3: 🎯 策略设置

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| strategyTemplate | select | 是 | 默认策略模板 |
| executionFrequency | radio | 是 | 1h / 4h / 1d |
| riskTolerance | select | 是 | 保守 / 稳健 / 激进 |
| allowedSymbols | multi-select | 否 | BTC, ETH, SOL... |

保存 API: `POST /api/config/strategies`

### Step 4: 📡 通信渠道

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| channelType | select | 是 | Telegram / 企微 / Email |
| botToken | input | 是 | Bot Token 或 Webhook URL |
| pushTypes | checkbox-group | 是 | 交易信号/风险告警/情报更新/每日报告 |
| silentStart | time | 否 | 静默开始时间 |
| silentEnd | time | 否 | 静默结束时间 |

保存 API: `POST /api/config/channels`
测试 API: `POST /api/config/channels/[id]/test`

---

## 6. 完成摘要卡片

全部 4 步完成（或退出）后展示：

```
┌─────────────────────────────────────────┐
│ 配置完成摘要                              │
│─────────────────────────────────────────│
│ ┌─────────────┐  ┌─────────────┐        │
│ │⚙️ API配置   │  │💰 交易设置  │        │
│ │[已配置]      │  │[已跳过]     │        │
│ │OKX|Demo     │  │默认参数      │        │
│ └─────────────┘  └─────────────┘        │
│ ┌─────────────┐  ┌─────────────┐        │
│ │🎯 策略设置  │  │📡 通信渠道  │        │
│ │[已配置]      │  │[已配置]     │        │
│ │保守|4h      │  │TG|信号+告警 │        │
│ └─────────────┘  └─────────────┘        │
│                                          │
│         完成度 3/4 (75%)                  │
│                                          │
│  [进入Dashboard]     [稍后配置]           │
└─────────────────────────────────────────┘
```

- 已配置项：绿色标签 `#1D9E75`
- 已跳过项：黄色标签 `#BA7517`
- 错误项：红色标签 `#A32D2D`
- 完成度进度条：绿色 `#1D9E75`

---

## 7. 技术实现

### 7.1 状态管理（Zustand Store）

新增 `auto-config-store.ts`：

```typescript
// /src/stores/auto-config-store.ts
import { create } from "zustand";

const CONFIG_STEPS = [
  { key: 'api',      label: 'API配置',   icon: '⚙️', panel: 'api' },
  { key: 'trading',  label: '交易设置',  icon: '💰', panel: 'trading' },
  { key: 'strategy', label: '策略设置',  icon: '🎯', panel: 'strategy' },
  { key: 'channels', label: '通信渠道',  icon: '📡', panel: 'communication' },
] as const;

type StepKey = typeof CONFIG_STEPS[number]['key'];

interface AutoConfigResult {
  step: number;
  key: StepKey;
  status: 'configured' | 'skipped' | 'error';
  data?: Record<string, unknown>;
  error?: string;
}

type AutoConfigPhase = 'idle' | 'asking' | 'inputting' | 'exit_confirm' | 'completed';

interface AutoConfigState {
  phase: AutoConfigPhase;
  currentStep: number;
  skipCount: number;
  results: AutoConfigResult[];
  isActive: boolean;

  start: () => void;
  handleYes: () => void;
  handleNo: () => void;
  handleSubmit: (data: Record<string, unknown>) => void;
  handleExitYes: () => void;
  handleExitNo: () => void;
  reset: () => void;
}
```

### 7.2 UI 组件

新增 `AutoConfigBubble` 组件：

```
src/components/chat/AutoConfigBubble.tsx
```

组件职责：
- 根据 `phase` 渲染不同内容（提问/输入框/退出确认）
- 内联快速回复按钮（是/否）
- 表单输入（动态字段，根据 currentStep 切换）
- 确认按钮高亮逻辑

### 7.3 进度指示器

在聊天区域顶部显示步骤进度：

```
① API配置 → ② 交易设置 → ③ 策略设置 → ④ 通信渠道
●            ○              ○              ○
```

- 当前步骤：蓝色圆点 `#378ADD`
- 已完成：绿色圆点 `#1D9E75`
- 已跳过：灰色圆点 `#888780`

### 7.4 集成点

1. **侧边栏入口**：`dashboard/page.tsx` 第 3586 行后新增点击事件
2. **聊天消息流**：`AutoConfigBubble` 作为特殊消息类型插入聊天区
3. **数据保存**：复用现有 `/api/config/*` 接口，无需新建后端
4. **进度恢复**：`localStorage` 暂存未完成的配置进度

---

## 8. 边界情况

| 场景 | 处理方式 |
|------|---------|
| 已有配置值 | 预填到输入框，显示「已配置」标签 |
| API 验证失败 | 内联红色提示，允许重新填写 |
| 用户中途关闭页面 | localStorage 暂存，下次恢复提示 |
| 全部跳过 | 摘要 0/4，引导进入设置页手动配置 |
| 网络错误 | Toast 提示「保存失败，请重试」 |
| 重复进入 | 检测已有结果，提示「已配置X项，是否重新配置？」 |

---

## 9. UI 规范

| 元素 | 样式 |
|------|------|
| AI 消息气泡 | bg `#2C2C2A`, radius `10px`, padding `12px 16px` |
| 用户回复气泡 | bg `#378ADD`, radius `10px`, white text |
| 药丸按钮-是 | bg `#1D9E75`, radius `15px`, white text |
| 药丸按钮-否 | border `#888780`, transparent bg, gray text |
| 输入框 | bg `#444441`, border `#5F5E5A`, radius `4px` |
| 确认按钮-禁用 | bg `#444441`, text `#5F5E5A` |
| 确认按钮-启用 | bg `#378ADD`, white text |
| 告警气泡 | bg `#A32D2D`, white text |
| 进度条完成 | bg `#1D9E75` |
| 进度条当前 | bg `#378ADD` |
| 进度条未到 | bg `#888780` |
