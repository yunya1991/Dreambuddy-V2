# 实施计划 (Implementation Plan)

> **版本**: v1.0
> **日期**: 2026-06-21
> **前置依赖**: SPEC.md 中定义的所有规范

---

## 一、总体路线图

```
阶段 1 (v0.1): 基础设施搭建
  ├─ P0: 技能注册表 (skills-registry)
  ├─ P0: 核心类型定义 (types)
  └─ P0: 基础 API 路由

阶段 2 (v0.2): AI 推理规划器
  ├─ P0: 主规划器 (planner)
  ├─ P0: 动态技能选择 (skill-selector)
  ├─ P1: 置信度评估 (confidence-evaluator)
  └─ P1: 迭代管理 (iteration-manager)

阶段 3 (v0.3): 思维链框架
  ├─ P1: S 链薄包装
  ├─ P2: C 链框架
  └─ P2: F 链框架 (空壳)

阶段 4 (v0.4): 交叉验证
  ├─ P1: 投票计算器
  └─ P1: 交叉验证节点集成

阶段 5 (v0.5): 图架构扩展
  ├─ P1: Architecture 层扩展
  └─ P2: 推理引擎增强

阶段 6 (v1.0): 集成与优化
  └─ P0: 与主前端集成
```

---

## 二、阶段详解

### 阶段 1 (v0.1): 基础设施搭建

#### P0: 核心类型定义

**文件**: `planner/types.ts`

```typescript
// 导出所有核心类型
export * from './skill-types';
export * from './step-types';
export * from './planner-types';
export * from './cross-validation-types';
```

**任务**:
- [ ] 创建 `skill-types.ts` - SkillCapability, SkillResult, ExecutionContext
- [ ] 创建 `step-types.ts` - ThinkingStepDefinition, StepExecutionResult
- [ ] 创建 `planner-types.ts` - PlannerContext, ExecutionPlan, PlannedStep
- [ ] 创建 `cross-validation-types.ts` - CrossValidationNode, VotingConfig
- [ ] 创建 `types.ts` - 统一导出

**验收标准**:
- [ ] 所有类型定义与 SPEC.md 一致
- [ ] 有完整的 JSDoc 注释
- [ ] 类型检查通过

---

#### P0: 技能注册表

**文件**: `planner/skills-registry.ts`

**任务**:
- [ ] 实现 SkillsRegistry 类
  - [ ] `register(skill)` - 注册技能
  - [ ] `get(skillId)` - 获取单个技能
  - [ ] `query(params)` - 条件查询
  - [ ] `recommend(context)` - 推荐技能
  - [ ] `getManifest()` - 获取元信息摘要
- [ ] 实现 A 系列技能注册
  - [ ] 从现有 SKILL.md 文件读取元信息
  - [ ] 填充 estimatedTokens, estimatedLatencyMs, confidenceRange
  - [ ] 关联 applicableIntents, applicableStages
- [ ] 实现 C 系列技能注册
  - [ ] 从 classic-system-client.ts 读取 API 端点
  - [ ] 定义 C1-C5 对应的 API 调用能力
- [ ] 实现 F 系列技能注册
  - [ ] 创建空壳注册（placeholder）

**验收标准**:
- [ ] SkillsRegistry 可以注册和查询技能
- [ ] 推荐算法能基于上下文返回合适的技能列表
- [ ] 所有 A 系列技能的元信息已注册

**关键代码片段**:

```typescript
export class SkillsRegistry {
  private skills: Map<string, SkillCapability> = new Map();

  register(skill: SkillCapability): void {
    if (this.skills.has(skill.metadata.id)) {
      console.warn(`Skill ${skill.metadata.id} already registered, overwriting`);
    }
    this.skills.set(skill.metadata.id, skill);
  }

  query(params: QueryParams): SkillCapability[] {
    let results = Array.from(this.skills.values());

    if (params.chain) {
      const chains = Array.isArray(params.chain) ? params.chain : [params.chain];
      results = results.filter(s => chains.includes(s.metadata.chain));
    }

    if (params.category) {
      const categories = Array.isArray(params.category) ? params.category : [params.category];
      results = results.filter(s => categories.includes(s.metadata.category));
    }

    if (params.stage) {
      const stages = Array.isArray(params.stage) ? params.stage : [params.stage];
      results = results.filter(s =>
        s.metadata.applicableStages.some(st => stages.includes(st))
      );
    }

    // ... 更多过滤逻辑

    return results;
  }

  recommend(context: ExecutionContext): SkillRecommendation[] {
    // 1. 匹配适用阶段和意图
    let candidates = this.query({
      stage: getStageForIntent(context.intent),
      intent: context.intent,
    });

    // 2. 成本过滤
    if (context.budgetTokens) {
      candidates = candidates.filter(s =>
        s.metadata.estimatedTokens <= context.budgetTokens
      );
    }

    // 3. 评分排序
    return candidates.map(skill => ({
      skill,
      score: calculateRecommendationScore(skill, context),
      reason: getRecommendationReason(skill, context),
    })).sort((a, b) => b.score - a.score);
  }
}
```

---

### 阶段 2 (v0.2): AI 推理规划器

#### P0: 主规划器

**文件**: `planner/planner.ts`

**任务**:
- [ ] 实现 `createPlan(context)` - 基于上下文创建执行计划
  - [ ] 识别意图 → 确定思维链
  - [ ] 查询技能注册表 → 获取候选技能
  - [ ] 评估成本约束 → 修剪路径
  - [ ] 生成步骤序列 + 交叉验证节点
- [ ] 实现 `executePlan(plan, context)` - 执行计划
  - [ ] 对每个步骤调用 `executeStep()`
  - [ ] 收集结果
  - [ ] 在交叉验证节点执行投票
  - [ ] 处理分支决策（继续/迭代/跳过/警告）
- [ ] 实现 `executeStep(step, context)` - 执行单个步骤
  - [ ] 调用 skill-selector 选择技能
  - [ ] 执行技能调用
  - [ ] 评估置信度
  - [ ] 返回 StepExecutionResult

**验收标准**:
- [ ] 能基于用户请求生成合理的执行计划
- [ ] 能正确执行计划的每个步骤
- [ ] 能处理技能超时/失败/降级
- [ ] 置信度评估逻辑正确

**关键代码片段**:

```typescript
export class ExecutionPlanner {
  private registry: SkillsRegistry;

  constructor(registry: SkillsRegistry) {
    this.registry = registry;
  }

  async executeStep(
    stepDef: ThinkingStepDefinition,
    context: ExecutionContext
  ): Promise<StepExecutionResult> {
    // 1. 动态选择技能
    const selectedSkills = await this.skillSelector.select(stepDef, context);

    // 2. 执行技能 (并行无依赖的)
    const skillResults = await this.executeSkillsParallel(selectedSkills, context);

    // 3. 置信度评估
    const confidenceEval = this.confidenceEvaluator.evaluate(
      skillResults,
      stepDef,
      context
    );

    // 4. 分支决策
    const decision = this.makeDecision(confidenceEval, stepDef);

    // 5. 如果需要迭代
    if (decision === 'iterate' && stepDef.allowIteration) {
      return this.executeIteration(stepDef, context, skillResults, confidenceEval);
    }

    // 6. 写入图架构
    const node = this.createArchitectureNode(stepDef, skillResults, confidenceEval, decision);

    return {
      stepId: stepDef.id,
      stage: stepDef.stage,
      chain: stepDef.chain,
      status: decision === 'skip' ? 'skipped' : 'completed',
      coreQuestion: stepDef.coreQuestion,
      answer: this.generateAnswer(skillResults, confidenceEval),
      skillsCalled: selectedSkills.map((s, i) => ({
        skillId: s.metadata.id,
        skillName: s.metadata.name,
        result: skillResults[i],
        invocationIndex: 1,
      })),
      confidence: confidenceEval.overallScore,
      confidenceDimensions: confidenceEval.dimensions,
      gaps: confidenceEval.gaps,
      decision,
      decisionReason: this.getDecisionReason(decision, confidenceEval),
      architectureNode: node,
    };
  }

  private async executeIteration(
    stepDef: ThinkingStepDefinition,
    context: ExecutionContext,
    priorResults: SkillResult[],
    priorEval: ConfidenceEvaluation
  ): Promise<StepExecutionResult> {
    let iteration = 1;
    let results = [...priorResults];
    let eval = priorEval;

    while (iteration < stepDef.maxIterations && eval.overallScore < stepDef.confidenceThresholds.high) {
      // 识别缺口
      const gapSkill = this.selectGapFillingSkill(stepDef, context, eval.gaps);

      if (!gapSkill) break; // 无法填补缺口

      // 补充调用
      const gapResult = await gapSkill.execute({}, context);
      results.push(gapResult);

      // 重新评估
      eval = this.confidenceEvaluator.evaluate(results, stepDef, context);
      iteration++;
    }

    return {
      // ... 返回带迭代记录的结果
      iterations: iteration,
      iterationReason: `迭代 ${iteration} 次后置信度达到 ${eval.overallScore}`,
    };
  }
}
```

---

#### P1: 置信度评估器

**文件**: `planner/confidence-evaluator.ts`

**任务**:
- [ ] 实现 `calculateDataCompleteness()` - 数据完整性评分
- [ ] 实现 `calculateLogicalConsistency()` - 逻辑一致性评分
- [ ] 实现 `calculateCrossValidation()` - 跨源印证评分
- [ ] 实现 `calculateHistoricalAccuracy()` - 历史准确率
- [ ] 实现 `identifyGaps()` - 识别信息缺口
- [ ] 实现 `makeRecommendation()` - 决策建议

**验收标准**:
- [ ] 评分算法与 SPEC.md 一致
- [ ] 能正确识别各种类型的缺口
- [ ] 决策建议合理

---

#### P1: 动态技能选择器

**文件**: `planner/skill-selector.ts`

**任务**:
- [ ] 实现 `select(stepDef, context)` - 基于步骤和上下文选择技能
  - [ ] 调用 `registry.recommend()`
  - [ ] 考虑并行能力
  - [ ] 考虑成本约束
  - [ ] 返回排序后的技能列表
- [ ] 实现 `selectGapFillingSkill()` - 选择填补缺口的技能

**验收标准**:
- [ ] 推荐逻辑合理
- [ ] 能正确识别可并行的技能
- [ ] 成本过滤正确

---

#### P1: 迭代管理器

**文件**: `planner/iteration-manager.ts`

**任务**:
- [ ] 实现 `shouldIterate()` - 判断是否应该迭代
- [ ] 实现 `selectNextSkills()` - 选择下一次迭代调用的技能
- [ ] 实现 `evaluateIterationValue()` - 评估迭代的价值

**验收标准**:
- [ ] 迭代决策合理（不过度迭代，也不过早放弃）
- [ ] 能选择合适的补充技能

---

### 阶段 3 (v0.3): 思维链框架

#### P1: S 链薄包装

**文件**: `chains/s-chain/steps.ts` + `chains/s-chain/step-wrappers.ts`

**任务**:
- [ ] 将 `6-TRADING/skills/dream-screen1-first/SKILL.md` 解析为 SkillCapability
- [ ] 将 `dream-screen2-second`, `dream-screen3-third` 解析
- [ ] 将所有 A 系列技能注册到注册表
- [ ] 重构现有的 `strategy/steps/analysis.ts` 为薄包装
  - [ ] 保留原有的步骤顺序定义
  - [ ] 内部委托给 ExecutionPlanner
  - [ ] 保留降级通道（如果 planner 不可用）

**验收标准**:
- [ ] 现有 S 链功能不受影响
- [ ] 新架构能正确调用 A 系列技能
- [ ] 有降级通道

---

#### P2: C 链框架

**文件**: `chains/c-chain/steps.ts` + `chains/c-chain/step-wrappers.ts`

**任务**:
- [ ] 定义 C1-C5 步骤 (对应 SPEC.md 5.2)
- [ ] 实现 C 链薄包装
  - [ ] 调用 classic-system-client.ts 的 API
  - [ ] 映射为 SkillResult 格式
- [ ] 与主前端集成
  - [ ] 扩展 trading-mode.ts 支持 `mode: 'classic'`

**验收标准**:
- [ ] C 链能正确调用经典指标系统 API
- [ ] 能与 S 链进行交叉验证

---

#### P2: F 链框架 (空壳)

**文件**: `chains/f-chain/steps.ts` + `chains/f-chain/step-wrappers.ts`

**任务**:
- [ ] 定义 F1-F5 步骤 (对应 SPEC.md 5.3)
- [ ] 实现空壳步骤 (调用时返回 `{ success: false }`)
- [ ] 记录待接入的数据源
- [ ] 扩展 trading-mode.ts 支持 `mode: 'hybrid'`

**验收标准**:
- [ ] F 链框架完整
- [ ] 空壳步骤正确返回降级信号
- [ ] 文档清晰说明如何接入真实数据源

---

### 阶段 4 (v0.4): 交叉验证

#### P1: 投票计算器

**文件**: `planner/voting-calculator.ts`

**任务**:
- [ ] 实现 `calculateWeightedVote()` - 加权投票
- [ ] 实现 `detectConflicts()` - 冲突检测
- [ ] 实现 `resolveConflicts()` - 冲突解决
- [ ] 实现 `getVotingConfig()` - 获取投票配置

**验收标准**:
- [ ] 投票算法与 SPEC.md 一致
- [ ] 能正确检测方向冲突和置信度差异
- [ ] 冲突解决逻辑合理

---

#### P1: 交叉验证节点集成

**文件**: `planner/cross-validator.ts`

**任务**:
- [ ] 实现 `createCrossValidationNode()` - 创建交叉验证节点
- [ ] 实现 `executeCrossValidation()` - 执行交叉验证
- [ ] 实现 `getDeepDivePlan()` - 生成深入分析计划
- [ ] 与 ExecutionPlanner 集成
  - [ ] 在计划的交叉验证节点调用 cross-validator

**验收标准**:
- [ ] 能正确执行三链投票
- [ ] 能生成合理的深入分析计划
- [ ] 能写入图架构

---

### 阶段 5 (v0.5): 图架构扩展

#### P1: Architecture 层扩展

**文件**: `enhanced-compressor.ts`

**任务**:
- [ ] 扩展 SerializedNode 类型 (添加 chain, stage, skillsInvoked 等)
- [ ] 扩展 GraphData 类型 (添加三链节点数组, 交叉验证节点)
- [ ] 实现 `createExtendedNode()` - 创建扩展节点
- [ ] 实现 `mergeChainResults()` - 合并三链结果
- [ ] 更新压缩算法支持新字段

**验收标准**:
- [ ] 压缩结果包含完整的三链信息
- [ ] 能正确写入和读取扩展字段

---

#### P2: 推理引擎增强

**文件**: `inference/enhanced-inference.ts`

**任务**:
- [ ] 实现 `generateStepSummaries()` - 生成步骤摘要
- [ ] 实现 `analyzeCrossChainConsistency()` - 分析跨链一致性
- [ ] 实现 `traceDecisionPath()` - 回溯决策路径
- [ ] 实现 `generateNextSteps()` - 生成下一步建议
- [ ] 实现 `createVisualizationData()` - 生成可视化数据

**验收标准**:
- [ ] 能生成完整的推理引擎报告
- [ ] 可视化数据能被前端正确渲染

---

### 阶段 6 (v1.0): 集成与优化

#### P0: 与主前端集成

**文件**: `3-FRONTEND/dream-universal-gateway/src/app/api/orchestrate/route.ts`

**任务**:
- [ ] 创建 `/api/orchestrate` 路由
- [ ] 集成 ExecutionPlanner
- [ ] 实现请求验证和错误处理
- [ ] 与图架构压缩模块集成
- [ ] 与现有 chat/route.ts 集成
  - [ ] `trading_mode: 'hybrid'` 时使用新编排器
  - [ ] 保留 `ai_skill` 和 `classic` 作为降级

**验收标准**:
- [ ] 新路由能正确处理编排请求
- [ ] 与现有功能兼容
- [ ] 有完整的错误处理

---

## 三、任务优先级矩阵

| 任务 | 阶段 | 优先级 | 预估工作量 | 依赖 |
|------|------|--------|-----------|------|
| 核心类型定义 | 1 | P0 | 1天 | - |
| 技能注册表基础 | 1 | P0 | 2天 | 类型定义 |
| 主规划器 | 2 | P0 | 3天 | 注册表 |
| S 链薄包装 | 3 | P1 | 2天 | 规划器 |
| 置信度评估器 | 2 | P1 | 2天 | 规划器 |
| 动态技能选择器 | 2 | P1 | 1天 | 注册表 |
| 迭代管理器 | 2 | P1 | 1天 | 置信度评估 |
| 投票计算器 | 4 | P1 | 1天 | 类型定义 |
| 交叉验证节点集成 | 4 | P1 | 2天 | 投票计算器 |
| C 链框架 | 3 | P2 | 2天 | 注册表 |
| F 链空壳框架 | 3 | P2 | 1天 | 注册表 |
| Architecture 扩展 | 5 | P1 | 2天 | 类型定义 |
| 推理引擎增强 | 5 | P2 | 2天 | Architecture扩展 |
| 主前端集成 | 6 | P0 | 3天 | 所有前期任务 |

---

## 四、测试计划

### 4.1 单元测试

| 模块 | 测试内容 | 验收标准 |
|------|---------|---------|
| skills-registry | 注册、查询、推荐逻辑 | 覆盖率 > 80% |
| confidence-evaluator | 评分算法、缺口识别 | 边界条件覆盖 |
| voting-calculator | 投票算法、冲突检测 | 所有场景 |
| planner | 计划生成、执行、迭代 | Mock 所有技能调用 |

### 4.2 集成测试

| 测试 | 描述 | 验收标准 |
|------|-----|---------|
| 端到端编排 | 用户请求 → 执行计划 → 结果 | 结果合理、置信度评估准确 |
| 三链交叉验证 | S/C/F 三链结果 → 投票 → 决策 | 投票结果与预期一致 |
| 降级通道 | 技能失败 → 降级执行 | 系统不崩溃，结果合理 |
| 图架构压缩 | 执行结果 → 压缩 → 恢复 | 数据完整性 |

### 4.3 演示脚本

| 脚本 | 描述 |
|------|------|
| `demo/orchestrator-demo.ts` | 演示完整的编排流程 |
| `demo/cross-validation-demo.ts` | 演示三链投票 |
| `demo/skill-selector-demo.ts` | 演示技能推荐 |

---

## 五、部署计划

### 5.1 环境准备

```bash
# 1. 安装依赖
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/6-图结构上下文压缩
npm install

# 2. 初始化 TypeScript 配置
npx tsc --init

# 3. 配置路径别名 (tsconfig.json)
{
  "compilerOptions": {
    "paths": {
      "@/*": ["./*"]
    }
  }
}
```

### 5.2 开发环境

```bash
# 启动开发服务器
npm run dev

# 运行测试
npm test

# 类型检查
npm run typecheck
```

### 5.3 与主前端集成

```typescript
// 3-FRONTEND/dream-universal-gateway/src/lib/trading-mode.ts
export type TradingMode = "ai_skill" | "classic" | "hybrid";

// 3-FRONTEND/dream-universal-gateway/src/app/api/orchestrate/route.ts
// 新路由文件
```

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 技能调用超时 | 用户体验差 | 设置合理的超时 + 降级通道 |
| 置信度评估不准确 | 决策错误 | 持续优化评估算法 + 用户反馈 |
| 交叉验证冲突频繁 | 系统不稳定 | 动态调整权重 + 用户确认 |
| 性能问题 | 延迟高 | 并行执行 + 成本预算控制 |
| 现有功能回归 | 功能破坏 | 保留降级通道 + 渐进迁移 |

---

## 七、关键里程碑

| 里程碑 | 完成条件 | 预计日期 |
|--------|---------|---------|
| M1: 类型定义完成 | 所有类型定义 + JSDoc | Day 1 |
| M2: 技能注册表可用 | A 系列技能注册完成 + 查询正常 | Day 3 |
| M3: 规划器可执行 | 能生成计划 + 执行步骤 | Day 6 |
| M4: S 链薄包装完成 | 现有 S 链功能迁移完成 | Day 8 |
| M5: 交叉验证可用 | 三链投票功能完成 | Day 11 |
| M6: v0.5 发布 | 图架构扩展 + 推理引擎增强 | Day 13 |
| M7: v1.0 发布 | 主前端集成 + 完整功能 | Day 16 |

---

## 八、后续优化方向

### v1.1: 动态权重学习
- 基于历史执行记录学习各技能的可靠性
- 根据市场状态自动调整链权重
- 用户可手动覆盖权重

### v1.2: 增量规划
- 支持在已有图架构基础上增量执行
- 快速恢复会话上下文
- 支持多轮对话中的增量推理

### v2.0: 多代理协作
- 支持多个 AI 代理并行推理
- 代理间消息传递和协调
- 共识机制和投票升级

---

*本文档与 SPEC.md 配套使用，定义具体的实现步骤和验收标准。*
