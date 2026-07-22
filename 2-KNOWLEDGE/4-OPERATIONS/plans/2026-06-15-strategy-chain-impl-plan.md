# 策略思维链实现计划

**版本**: v1.0
**日期**: 2026-06-15
**基于设计**: docs/superpowers/specs/2026-06-15-strategy-chain-design.md

---

## Phase 1: 核心基础设施

### 1.1 创建类型定义文件

**文件**: `src/lib/strategy/types.ts`

**任务**:
- [ ] 定义 `StrategyStepStatus` 类型
- [ ] 定义 `STRATEGY_STEPS` 常量数组
- [ ] 定义 `StrategyStep` 接口
- [ ] 定义 `StrategyChainState` 接口
- [ ] 定义 `StrategyComplexity` 类型
- [ ] 定义 `StrategyTask` 接口
- [ ] 定义 `StrategyStepAction` 类型

**验证**:
```bash
npm run typecheck
```

---

### 1.2 创建路由引擎

**文件**: `src/lib/strategy/route.ts`

**任务**:
- [ ] 创建 `STRATEGY_STEP_DEFINITIONS` 配置
- [ ] 创建 `STRATEGY_ROUTE_MAP` 路由映射
- [ ] 创建 `STRATEGY_COMMAND_ROUTE_MAP` 命令映射
- [ ] 实现 `routeToStrategyChain()` 函数
- [ ] 实现 `getStrategyComplexity()` 函数
- [ ] 导出所有公共函数和类型

**验证**:
```bash
npm run typecheck
```

---

### 1.3 集成到智能路由

**文件**: `src/lib/intent/smart-router.ts`

**任务**:
- [ ] 导入新的策略路由
- [ ] 修改 `routeIntent()` 支持策略意图
- [ ] 更新命令路由映射，区分策略命令
- [ ] 添加测试用例验证路由

**验证**:
```bash
npm run typecheck
npm run test
```

---

## Phase 2: 步骤实现

### 2.1 S1_调研 步骤

**文件**: `src/lib/strategy/steps/research.ts`

**任务**:
- [ ] 定义 `ResearchInput` 接口
- [ ] 定义 `ResearchOutput` 接口
- [ ] 实现 `executeS1Research()` 函数
- [ ] 实现 `formatResearchResult()` 格式化函数
- [ ] 集成市场数据获取
- [ ] 集成新闻/情绪分析

**输出格式**:
```markdown
## S1_调研结果

### 市场现状
- 标的: [symbol]
- 当前价格: [price]
- 24h变化: [change%]

### 技术指标
- 支撑位: [support]
- 阻力位: [resistance]
- RSI: [value]
- MACD: [signal]

### 情绪指标
- 恐慌贪婪指数: [value]
- 合约持仓: [data]

### 调研结论
[summary]
```

**验证**:
```bash
npm run typecheck
```

---

### 2.2 S2_分析 步骤

**文件**: `src/lib/strategy/steps/analysis.ts`

**任务**:
- [ ] 定义 `AnalysisInput` 接口（S1输出）
- [ ] 定义 `AnalysisOutput` 接口
- [ ] 实现 `executeS2Analysis()` 函数
- [ ] 实现多维度分析逻辑
- [ ] 实现 `formatAnalysisResult()` 格式化函数

**输出格式**:
```markdown
## S2_分析结论

### 趋势判断
- 短期: [bullish/bearish/neutral]
- 中期: [bullish/bearish/neutral]
- 长期: [bullish/bearish/neutral]

### 关键价位
- 入场区间: [range]
- 止损位: [stop_loss]
- 止盈位: [take_profit]

### 风险因素
- [risk_1]
- [risk_2]

### 分析置信度
[confidence]%
```

**验证**:
```bash
npm run typecheck
```

---

### 2.3 S3_设计 步骤

**文件**: `src/lib/strategy/steps/design.ts`

**任务**:
- [ ] 定义 `DesignInput` 接口（S2输出）
- [ ] 定义 `DesignOutput` 接口
- [ ] 实现 `executeS3Design()` 函数
- [ ] 实现策略方案生成
- [ ] 实现情景推演
- [ ] 实现 `formatDesignResult()` 格式化函数

**输出格式**:
```markdown
## S3_策略方案

### 策略名称
[strategy_name]

### 入场计划
- 入场点: [entry_point]
- 仓位: [position_size]%
- 加仓规则: [rules]

### 风险管理
- 止损位: [stop_loss]
- 止盈位: [take_profit]
- 盈亏比: [ratio]

### 情景推演
**乐观情景** ([prob]%): [outcome]
**中性情景** ([prob]%): [outcome]
**悲观情景** ([prob]%): [outcome]

### 策略置信度
[confidence]%
```

**验证**:
```bash
npm run typecheck
```

---

### 2.4 S4_验证 步骤

**文件**: `src/lib/strategy/steps/validate.ts`

**任务**:
- [ ] 定义 `ValidateInput` 接口（S3输出）
- [ ] 定义 `ValidateOutput` 接口
- [ ] 实现 `executeS4Validate()` 函数
- [ ] 集成回测逻辑
- [ ] 实现风险评估
- [ ] 实现 `formatValidateResult()` 格式化函数

**输出格式**:
```markdown
## S4_验证报告

### 回测摘要
- 测试周期: [period]
- 胜率: [win_rate]%
- 盈亏比: [profit_factor]
- 最大回撤: [max_drawdown]%
- 夏普比率: [sharpe_ratio]

### 风险评估
- VaR(95%): [value]
- 最大单日亏损: [value]
- 连续亏损次数: [count]

### 验证结论
[verdict]

### 是否建议执行
[recommend] / [not_recommend]
```

**验证**:
```bash
npm run typecheck
```

---

### 2.5 S5_执行 步骤

**文件**: `src/lib/strategy/steps/execute.ts`

**任务**:
- [ ] 定义 `ExecuteInput` 接口（S4输出）
- [ ] 定义 `ExecuteOutput` 接口
- [ ] 实现 `executeS5Execute()` 函数
- [ ] 实现执行清单生成
- [ ] 实现跟踪提醒
- [ ] 实现 `formatExecuteResult()` 格式化函数

**输出格式**:
```markdown
## S5_执行计划

### 执行清单
- [ ] 检查账户余额
- [ ] 设置止损单
- [ ] 买入 [amount] @ [price]
- [ ] 设置止盈单
- [ ] 记录交易日志

### 跟踪提醒
- 每4小时检查一次价格
- 若跌破 [alert_price] 需警惕
- 若达到 [milestone] 考虑加仓

### 风险提示
[warning]
```

**验证**:
```bash
npm run typecheck
```

---

### 2.6 步骤导出

**文件**: `src/lib/strategy/steps/index.ts`

**任务**:
- [ ] 导出所有步骤
- [ ] 创建步骤执行工厂函数

---

## Phase 3: 控制器与集成

### 3.1 链状态机控制器

**文件**: `src/lib/strategy/chain-controller.ts`

**任务**:
- [ ] 定义 `ChainController` 类
- [ ] 实现 `initChain()` 初始化链
- [ ] 实现 `getCurrentStep()` 获取当前步骤
- [ ] 实现 `executeStep()` 执行步骤
- [ ] 实现 `confirmStep()` 确认步骤
- [ ] 实现 `skipStep()` 跳过步骤
- [ ] 实现 `pauseChain()` 暂停链
- [ ] 实现 `resumeChain()` 恢复链
- [ ] 实现 `getChainState()` 获取链状态

**验证**:
```bash
npm run typecheck
```

---

### 3.2 策略笔记本集成

**文件**: `src/lib/notebook/types.ts`

**任务**:
- [ ] 添加 `StrategyChainState` 类型
- [ ] 修改 `NotebookTask` 支持策略链
- [ ] 更新 `NotebookStep` 支持策略步骤

**文件**: `src/lib/notebook/step-controller.ts`

**任务**:
- [ ] 添加策略链处理逻辑
- [ ] 实现策略步骤的UI状态同步

---

### 3.3 Chat API集成

**文件**: `src/app/api/chat/route.ts`

**任务**:
- [ ] 导入策略链控制器
- [ ] 修改聊天处理逻辑，识别策略意图
- [ ] 实现策略链的执行流程
- [ ] 添加策略链状态的响应

**验证**:
```bash
npm run build
```

---

## Phase 4: 测试与优化

### 4.1 单元测试

**文件**: `src/lib/strategy/__tests__/`

**任务**:
- [ ] 测试 `route.ts` 路由逻辑
- [ ] 测试 `chain-controller.ts` 状态机
- [ ] 测试各步骤执行逻辑

**验证**:
```bash
npm run test
```

---

### 4.2 集成测试

**文件**: `src/app/api/chat/__tests__/`

**任务**:
- [ ] 测试策略意图识别
- [ ] 测试完整策略链执行
- [ ] 测试步骤跳过和暂停

**验证**:
```bash
npm run test
```

---

### 4.3 前端集成

**文件**: `src/app/dashboard/page.tsx`

**任务**:
- [ ] 更新notebook组件显示策略链状态
- [ ] 添加策略步骤确认UI
- [ ] 实现步骤跳过/暂停按钮

**验证**:
- [ ] 页面可正常访问
- [ ] 策略链状态正确显示
- [ ] 用户可进行步骤确认操作

---

## Phase 5: 文档与部署

### 5.1 更新文档

**任务**:
- [ ] 更新 README.md 说明新功能
- [ ] 添加使用示例
- [ ] 添加架构图

### 5.2 Git提交

**提交信息**:
```
feat: 实现策略思维链 S1-S5

- 新增策略路由引擎
- 实现S1调研、S2分析、S3设计、S4验证、S5执行步骤
- 集成到chat API
- 更新前端notebook界面
```

---

## 优先级排序

1. **Phase 1** (核心基础设施) - 必须先完成
2. **Phase 2** (步骤实现) - 核心功能
3. **Phase 3** (控制器与集成) - 连通前后端
4. **Phase 4** (测试与优化) - 质量保障
5. **Phase 5** (文档与部署) - 收尾工作

---

## 风险与依赖

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 现有D-Z-E链冲突 | 高 | 独立文件隔离，通过路由区分 |
| 回测性能 | 中 | 使用缓存，控制回测周期 |
| 前端状态同步 | 中 | 使用现有notebook模式扩展 |

---

## 里程碑

| 里程碑 | 完成标准 |
|--------|----------|
| M1: 核心类型和路由 | 类型检查通过，路由逻辑正确 |
| M2: S1-S3可用 | 用户可完成调研→分析→设计 |
| M3: 完整S1-S5 | 所有步骤可用，状态正确 |
| M4: 前后端集成 | UI可交互，状态同步 |
| M5: 测试通过 | 单元测试和集成测试通过 |

