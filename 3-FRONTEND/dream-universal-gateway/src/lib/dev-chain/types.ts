/**
 * S5 执行引擎 - 类型系统
 *
 * 定位：主前端的 S5_EXECUTE 内部执行引擎
 *   - S5 = E1 任务执行 → E2 测试验证 → E3 部署交付
 *   - 仅服务于"策略代码开发"这一个场景
 *   - 与后端 (6-Trading) 的完整 D-Z-E 链不冲突，互为补充
 *
 * 对外暴露：
 *   - S5Executor：S5_EXECUTE 的内部执行器
 *   - 由上层 S 系列（S3/S4）调用，不作为独立思维链暴露
 */

// -------- S5 内部步骤（即完整 E 链）--------
export type S5StepId =
  | 'E1_TASK_EXECUTE'   // E1 任务执行：生成策略代码
  | 'E2_TEST_VALIDATE'  // E2 测试验证：运行测试验证代码正确性
  | 'E3_DEPLOY_DELIVER'; // E3 部署交付：部署到运行环境

// -------- 步骤状态 --------
export type S5StepStatus =
  | 'pending'
  | 'active'
  | 'done'
  | 'skipped'
  | 'failed';

// -------- 步骤运行时状态 --------
export interface S5StepRuntime {
  id: S5StepId;
  status: S5StepStatus;
  output: string;
  artifacts: string[];       // 产出：代码文件、日志、测试报告等
  startedAt?: string;
  completedAt?: string;
  duration_ms?: number;
}

// -------- 链整体状态 --------
export interface S5ChainState {
  taskId: string;
  sessionId: string;
  scopeDescription: string;   // 策略描述
  currentStepId: S5StepId | null;
  currentStepIndex: number;
  steps: S5StepRuntime[];
  plannedStepIds: S5StepId[];
  createdAt: string;
  modifiedAt: string;
  totalDurationMs: number;
  // 策略参数（从 S3 阶段产物提取）
  strategyParams?: {
    symbol?: string;
    timeframe?: string;
    entryRule?: string;
    stopLoss?: string;
    takeProfit?: string;
    positionSize?: string;
  };
}

// -------- 步骤定义 --------
export interface S5StepDefinition {
  id: S5StepId;
  label: string;
  icon: string;
  description: string;
  estimatedTimeMs: number;
  estimatedCredits: number;
  requiresUserConfirmation: boolean;  // E 链无需确认，连续执行
  requiresWorkBuddy: boolean;          // 是否需要触发后端 WorkBuddy
}

// -------- 执行上下文 --------
export interface S5ExecutionContext {
  taskId: string;
  sessionId: string;
  userMessage: string;
  thinkingMode: 'quick' | 'deep';
  lang: 'zh' | 'en';
  strategyParams?: {
    symbol?: string;
    timeframe?: string;
    entryRule?: string;
    stopLoss?: string;
    takeProfit?: string;
    positionSize?: string;
  };
}

// -------- 步骤执行结果 --------
export interface S5StepExecutionResult {
  stepId: S5StepId;
  status: 'done' | 'skipped' | 'failed';
  output: string;
  artifacts: string[];
  durationMs: number;
  shouldTriggerWorkBuddy: boolean;
  workBuddyCommand?: string;
}

// -------- executeS5 返回结果（在 chain-controller.ts 中导出） --------
export interface S5ExecutionResult {
  content: string;
  allStepsForDisplay: Array<{
    id: S5StepId;
    label: string;
    icon: string;
    status: string;
  }>;
  shouldTriggerWorkBuddy: boolean;
  estimatedMs: number;
  isComplete: boolean;
  scopeDescription: string;
}
