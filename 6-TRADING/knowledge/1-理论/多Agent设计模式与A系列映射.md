# 多Agent设计模式与A系列管道映射

> **来源**: Google's Eight Essential Multi-Agent Design Patterns (InfoQ, 2026-01-05)
> **日期**: 2026-06-15 | **搜索关键词**: `multi-agent design patterns google ADK 2026`
> **评估分**: 相关性5 + 新颖性3 + 实践性4 = **12/15**

---

## 核心理念

> "Creating complex, scalable agentic applications requires the same disciplined approach used for other software systems... Reliability comes from decentralization and specialization. Multi-Agent Systems (MAS) allow you to build the AI equivalent of a microservices architecture."
> — Google ADK Team

**关键原则**: 为每个Agent分配特定角色（解析器/批评者/调度器）→ 系统变得更模块化、可测试、可靠。

---

## Google八大设计模式与6-TRADING A系列映射

### 1. Sequential Pipeline (顺序管道)
> Agent像流水线一样排列，每个Agent将输出传给下一个。线性、确定性、易于调试。

**映射**: **A1→A2→A3→A4→A5→A9** 主交易链
- A1 战略调研 → A2 第一性原理 → A3 策略设计 → A4 战术验证 → A5 执行 → A9 离场
- ✅ 已采用：A系列 cron 任务链严格按序执行
- ⚠️ 需改进：当前缺少中间产物格式标准（应统一为结构化JSON，非自由Markdown）

### 2. Coordinator/Dispatcher (协调器/调度器)
> 一个Agent做决策者，接收请求→分派给下游专业Agent。

**映射**: **A6 情报监控触发器**
- A6 接收市场事件 → 判定是否需要触发A系列重计算 → 调度A2/A3/A4
- ✅ 已采用：a6-monitor-trigger 模式
- ⚠️ 需改进：调度逻辑目前为规则驱动，可考虑引入LLM-based判断

### 3. Parallel Fan-Out/Gather (并行扇出/聚合)
> 多个Agent同时运作，各自独立职责。输出汇总到合成Agent。

**映射**: **代码审查工作流** (code-review-workflow)
- PR-reviewer / Critical Code Reviewer / Security Audit / Clean Code → 并行分析 → 汇总报告
- ✅ 已采用：code-review-workflow SKILL 的6步串联
- ⚠️ 需改进：当前为串联而非真并行，可考虑 delegate_task 并行化

### 4. Hierarchical Decomposition (层级分解)
> 高层Agent将复杂目标分解为子任务，委派给其他Agent。

**映射**: **三屏交易体系**
- Screen1(战略/周线) → Screen2(战术/日线) → Screen3(执行/小时线)
- ✅ 已采用：三屏层级结构

### 5. Generator and Critic (生成器与批评者)
> 一个Agent创建，另一个验证。可选反馈循环迭代优化。

**映射**: **A3(策略设计) + A4(战术验证)**
- A3 生成策略 → A4 批判性验证 → 反馈修正
- ✅ 已采用：A4 的验证门禁
- ⚠️ 需改进：缺少迭代循环（A4不通过时A3自动修正再验证）

### 6. Iterative Refinement (迭代精炼)
> Generator + Critique + Refiner 三个Agent循环工作。

**映射**: **贝叶斯优化循环**
- 参数生成 → 回测验证 → 参数精炼 → 循环
- ✅ 已采用：dream-bayesian-opt SKILL
- ⚠️ 需改进：当前缺少Critique Agent（独立批判参数选择的合理性）

### 7. Human in the Loop (人类在环)
> 用于不可逆或高后果决策：金融交易执行、代码生产部署、敏感数据操作。

**映射**: **飞书审批流**
- 策略变更 → 飞书审批 → 人工确认 → 执行
- ✅ 已采用：trading-evolution 审批 + approval-timeout-check
- ✅ 超时30分钟自动批准机制（降级路径）

### 8. Composite Pattern (组合模式)
> 组合使用以上多种模式。

**映射**: **全系统编排**
- Coordinator (A6路由) + Sequential (A1-A5) + Generator-Critic (A3-A4) + Human-in-Loop (审批)
- ⚠️ 需改进：当前模式为隐式组合，缺少显式架构文档

---

## 对6-TRADING的具体启示

### 立即可做
1. **A系列产物标准化**: A1-A5输出应为结构化JSON + Markdown双格式，确保下游可解析
2. **A4→A3反馈循环**: A4不通过时，A3应收到信号自动修正而非等待下一轮cron
3. **A6调度器升级**: 当前基于规则，可引入轻量LLM判断是否触发重计算（节省Token）

### 中期规划
4. **并行化代码审查**: code-review-workflow改为真并行（delegate_task）
5. **Generator-Critic模式扩展**: 将A3-A4关系显式化为Generator-Critic，增加迭代次数

### 长期愿景
6. **全系统Composite模式文档**: 绘制完整的Agent交互图（类似微服务架构图）

---

## 参考

- Google ADK Multi-Agent Guide: https://google.github.io/adk-docs/agents/multi-agents/
- InfoQ原文: https://www.infoq.com/news/2026/01/multi-agent-design-patterns
- 收录日期: 2026-06-15
