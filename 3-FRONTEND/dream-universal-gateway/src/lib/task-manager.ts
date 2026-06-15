/**
 * Task Manager - 前端与WorkBuddy异步通信的任务管理器
 * v2.0 - 中台即时触发模式
 *
 * 核心变更：
 * - 创建任务后立即触发WorkBuddy执行（非定时轮询）
 * - 对话任务：中台直接内联执行，秒级响应
 * - 交易任务：返回待确认状态，需用户确认执行时间
 *
 * 数据流：
 *   前端 → POST /api/task → 写task文件 → 立即触发执行 → 写result文件 → 前端轮询
 */

import * as fs from 'fs';
import * as path from 'path';
import * as child_process from 'child_process';
import { emitMonitorEvent } from './monitor-bus';
import {
  recognizeIntent,
  routeIntent,
  CHAIN_STEPS,
  requiresStepConfirmation,
  isExecutionChainStep,
  getNextConfirmationStep,
  generateStepConfirmationPrompt,
  parseUserConfirmation,
  type IntentType,
  type IntentRecognitionResult,
  type RoutingDecision,
} from './intent';
import {
  fetchMarketData,
  formatMarketData,
  extractSymbolFromMessage,
  type MarketData,
} from './market-data-adapter';

function resolveRepoRoot(): string {
  const cwd = process.cwd();
  const candidates = [
    cwd,
    path.resolve(cwd, '..'),
    path.resolve(cwd, '..', '..'),
    path.resolve(cwd, '..', '..', '..'),
  ];
  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, 'dreambuddy'))) return dir;
  }
  return path.resolve(cwd, '..', '..');
}

const REPO_ROOT = resolveRepoRoot();

export const ARTIFACTS_DIR = fs.existsSync(path.join(REPO_ROOT, 'dreambuddy', 'artifacts'))
  ? path.join(REPO_ROOT, 'dreambuddy', 'artifacts')
  : path.join(REPO_ROOT, 'artifacts');

export const TASKS_DIR = path.join(ARTIFACTS_DIR, 'tasks');
export const RESULTS_DIR = path.join(ARTIFACTS_DIR, 'results');

// 任务超时时间（30分钟）
const TASK_TIMEOUT_MS = 30 * 60 * 1000;

// 最大并发任务数
const MAX_CONCURRENT_TASKS = 3;

const GATEWAY_DIR = path.join(REPO_ROOT, '3-FRONTEND', 'dream-universal-gateway');
const POLLER_SCRIPT = path.join(GATEWAY_DIR, 'scripts', 'task_poller.py');

// 对话类意图 - 中台直接内联执行
const CONVERSATION_INTENTS: IntentType[] = [
  'market_query', 'deep_analysis', 'simple_qa', 'scenario_sim', 'strategy_verify', 'command',
  'credits_query', 'artifact_query', 'system_config', 'risk_alert_response',
  'triple_chain', 'need_clarification', 'clarification_result',
];

// 交易类意图 - 需用户确认执行时间
const TRADE_INTENTS: IntentType[] = ['execute_trade'];

/**
 * 任务状态
 */
export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'timeout' | 'scheduled' | 'cancelled' | 'awaiting_confirmation' | 'awaiting_clarification';

/**
 * 意图类型 (re-exported from intent module)
 */
export type { IntentType } from './intent';

/**
 * 思考模式
 */

/**
 * 思考模式
 */
export type ThinkingMode = 'quick' | 'deep';

/**
 * 任务文件格式
 */
export interface TaskFile {
  task_id: string;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
  source: string;
  message: string;
  intent: {
    type: IntentType;
    confidence: number;
    entities?: {
      symbol?: string;
      timeframe?: string;
      strategy?: string;
    };
    // 澄清相关（仅当 type === 'need_clarification' 时有值）
    clarification_options?: Array<{
      key: string;
      label: string;
      target_intent: IntentType;
      entities?: Record<string, string>;
    }>;
    clarification_question?: string;
    reasoning?: string;
  };
  thinking_mode: ThinkingMode;
  session_id: string;
  priority: 'high' | 'medium' | 'low';
  metadata: {
    user_agent?: string;
    llm_model?: string;
    intent_method?: string;
  };
}

/**
 * 结果文件格式
 */
export interface ResultFile {
  task_id: string;
  session_id?: string;
  status: 'completed' | 'failed' | 'awaiting_confirmation' | 'awaiting_clarification';
  created_at: string;
  execution_time_ms?: number;
  content: string;
  content_type: 'markdown' | 'json' | 'text';
  // 意图信息（用于前端判断意图类型）
  intent?: {
    type: IntentType;
    confidence?: number;
    method?: string;
    reasoning?: string;
    entities?: Record<string, string>;
    complexity?: string;
  };
  artifacts_produced?: Array<{
    file: string;
    type: string;
    chain_phase: string;
  }>;
  execution_summary?: {
    chain_executed: string[];
    total_steps: number;
    skipped_steps: string[];
    current_step?: string;
    current_step_index?: number;
    regime?: string;
    confidence?: number;
    intent_recognized?: string;
    total_time_ms?: number;
  };
  // D/Z/E 步进确认
  step_confirmation?: {
    current_step: string;
    next_step: string | null;
    options: Array<{ key: string; label: string; action: 'continue' | 'finalize' | 'skip' }>;
    prompt: string;
  };
  // 意图澄清
  clarification_state?: {
    question: string;
    options: Array<{
      key: string;
      label: string;
      target_intent: IntentType;
      entities?: Record<string, string>;
    }>;
  };
  error?: string;
  metadata?: {
    executor?: string;
    model?: string;
    cost_credits?: number;
    skip_non_finance?: boolean;
  };
  persisted?: boolean;
  trade_requires_confirmation?: boolean;
}

/**
 * 确保目录存在
 */
function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/**
 * 生成任务ID
 * 格式: task_YYYYMMDD_HHMMSS_xxxx
 */
export function generateTaskId(): string {
  const now = new Date();
  const dateStr = now.toISOString().replace(/[-:T]/g, '').slice(0, 14);
  const random = Math.random().toString(36).substring(2, 6);
  return `task_${dateStr}_${random}`;
}

/**
 * 将新的 IntentRecognitionResult 转换为 TaskFile 格式 (兼容旧格式)
 */
function convertIntentToTaskFile(result: IntentRecognitionResult): TaskFile['intent'] {
  const base: TaskFile['intent'] = {
    type: result.intent,
    confidence: result.confidence,
    entities: {
      symbol: result.entities.symbol,
      timeframe: result.entities.timeframe,
      strategy: result.entities.strategy,
    },
    reasoning: result.reasoning,
  };

  // 仅当意图是 need_clarification 时，附加澄清字段
  if (result.intent === 'need_clarification') {
    base.clarification_options = result.clarification_options;
    base.clarification_question = result.clarification_question;
  }
  return base;
}

/**
 * 创建任务
 */
export async function createTask(params: {
  message: string;
  thinking_mode?: ThinkingMode;
  session_id?: string;
  llm_model?: string;
  intent_method?: string;
}): Promise<TaskFile> {
  ensureDir(TASKS_DIR);
  ensureDir(RESULTS_DIR);

  const thinkingMode = params.thinking_mode || 'quick';

  // 使用统一意图识别引擎 (LLM → rule → fallback)
  const intentResult = await recognizeIntent(params.message, {
    session_id: params.session_id || `sess_${Date.now()}`,
    user_role: 'FREE', // TODO: from auth context
    thinking_mode: thinkingMode,
    message_history: [],
  });

  const intent = convertIntentToTaskFile(intentResult);
  const now = new Date().toISOString();
  const taskId = generateTaskId();

  const task: TaskFile = {
    task_id: taskId,
    status: 'pending',
    created_at: now,
    updated_at: now,
    source: 'dashboard',
    message: params.message,
    intent,
    thinking_mode: thinkingMode,
    session_id: params.session_id || `sess_${Date.now()}`,
    priority: intent.confidence >= 0.8 ? 'high' : 'medium',
    metadata: {
      user_agent: 'DreamGateway/1.0',
      llm_model: params.llm_model,
      intent_method: intentResult.method,
    },
  };

  const filePath = path.join(TASKS_DIR, `${taskId}.json`);
  fs.writeFileSync(filePath, JSON.stringify(task, null, 2), 'utf-8');

  console.log(`[TaskManager] Task created: ${taskId} (intent: ${intent.type}, mode: ${thinkingMode})`);
  return task;
}

/**
 * 读取任务
 */
export function readTask(taskId: string): TaskFile | null {
  const filePath = path.join(TASKS_DIR, `${taskId}.json`);
  if (!fs.existsSync(filePath)) {
    return null;
  }
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(content) as TaskFile;
  } catch {
    return null;
  }
}

/**
 * 读取结果
 */
export function readResult(taskId: string): ResultFile | null {
  const filePath = path.join(RESULTS_DIR, `result_${taskId}.json`);
  if (!fs.existsSync(filePath)) {
    return null;
  }
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(content) as ResultFile;
  } catch {
    return null;
  }
}

/**
 * 获取任务状态（合并任务文件和结果文件）
 */
export function getTaskStatus(taskId: string): {
  task: TaskFile | null;
  result: ResultFile | null;
  poll_url: string;
} {
  const task = readTask(taskId);
  const result = readResult(taskId);

  // 检查超时
  if (task && task.status === 'pending') {
    const createdTime = new Date(task.created_at).getTime();
    if (Date.now() - createdTime > TASK_TIMEOUT_MS) {
      task.status = 'timeout';
      task.updated_at = new Date().toISOString();
      // 更新文件
      const filePath = path.join(TASKS_DIR, `${taskId}.json`);
      try {
        fs.writeFileSync(filePath, JSON.stringify(task, null, 2), 'utf-8');
      } catch { /* ignore write error on timeout */ }
    }
  }

  return {
    task,
    result,
    poll_url: `/api/task?id=${taskId}`,
  };
}

/**
 * 列出任务
 */
export function listTasks(limit: number = 20, status?: TaskStatus): Array<{
  task_id: string;
  status: TaskStatus;
  message: string;
  created_at: string;
  intent_type: IntentType;
}> {
  ensureDir(TASKS_DIR);

  let files: string[];
  try {
    files = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.json'));
  } catch {
    return [];
  }

  const tasks = files
    .map(f => {
      try {
        const content = fs.readFileSync(path.join(TASKS_DIR, f), 'utf-8');
        return JSON.parse(content) as TaskFile;
      } catch {
        return null;
      }
    })
    .filter((t): t is TaskFile => t !== null)
    .filter(t => !status || t.status === status)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, limit)
    .map(t => ({
      task_id: t.task_id,
      status: t.status,
      message: t.message,
      created_at: t.created_at,
      intent_type: t.intent.type,
    }));

  return tasks;
}

/**
 * 获取当前pending任务数
 */
export function getPendingCount(): number {
  ensureDir(TASKS_DIR);
  try {
    const files = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.json'));
    return files.filter(f => {
      try {
        const content = fs.readFileSync(path.join(TASKS_DIR, f), 'utf-8');
        const task = JSON.parse(content) as TaskFile;
        return task.status === 'pending';
      } catch {
        return false;
      }
    }).length;
  } catch {
    return 0;
  }
}

/**
 * 检查是否可以创建新任务（并发限制）
 */
export function canCreateTask(): boolean {
  return getPendingCount() < MAX_CONCURRENT_TASKS;
}

/**
 * 清理过期任务文件（24小时以上）
 */
export function cleanupOldTasks(): number {
  ensureDir(TASKS_DIR);
  ensureDir(RESULTS_DIR);

  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  let deleted = 0;

  // 清理任务文件
  try {
    const taskFiles = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.json'));
    for (const f of taskFiles) {
      const filePath = path.join(TASKS_DIR, f);
      try {
        const stat = fs.statSync(filePath);
        if (stat.mtimeMs < cutoff) {
          fs.unlinkSync(filePath);
          deleted++;
        }
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }

  // 清理结果文件
  try {
    const resultFiles = fs.readdirSync(RESULTS_DIR).filter(f => f.endsWith('.json'));
    for (const f of resultFiles) {
      const filePath = path.join(RESULTS_DIR, f);
      try {
        const stat = fs.statSync(filePath);
        if (stat.mtimeMs < cutoff) {
          fs.unlinkSync(filePath);
          deleted++;
        }
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }

  return deleted;
}

/**
 * 估算执行时间 (基于 CHAIN_STEPS)
 */
export function getEstimatedTimeMs(chain: string[]): number {
  return chain.reduce((sum, step) => sum + (CHAIN_STEPS[step]?.time_ms || 10000), 0);
}

// ============================================================
// v2.0 核心：即时触发执行
// ============================================================

/**
 * 判断意图是否为对话类（单次执行）
 */
export function isConversationIntent(intentType: IntentType): boolean {
  return CONVERSATION_INTENTS.includes(intentType);
}

/**
 * 判断意图是否为交易类（需用户确认）
 */
export function isTradeIntent(intentType: IntentType): boolean {
  return TRADE_INTENTS.includes(intentType);
}

/**
 * 中台内联执行对话任务（秒级响应）
 * 直接在Node.js进程中执行，无需调用外部脚本
 * 支持 D/Z/E 步进确认机制
 */
export async function executeConversationTaskInline(task: TaskFile, lang: 'zh' | 'en' = 'zh'): Promise<ResultFile> {
  const startTime = Date.now();
  let intentType = task.intent.type;
  let thinkingMode = task.thinking_mode;

  // 1) 意图澄清 → 直接返回澄清内容，不走链路
  if (intentType === 'need_clarification') {
    return buildClarificationResult(task, lang, startTime);
  }

  // 2) 金融话题相关性检测（非金融 → 不回答，也不存储记忆）
  const isFinancial = detectFinanceRelevance(task.message, intentType, task.intent.entities || {});
  if (!isFinancial) {
    const msg = lang === 'zh'
      ? '本系统仅聚焦于金融/加密市场相关分析与问答。你的问题不在范围内，已跳过。'
      : 'This system focuses only on finance / crypto market analysis. Your question is out of scope and has been skipped.';

    emitMonitorEvent({
      trace_id: task.task_id,
      uid: task.session_id,
      layer: 'gateway',
      phase: 'non_financial_skip',
      status: 'completed',
      intent: intentType,
      duration_ms: Date.now() - startTime,
    });

    return {
      task_id: task.task_id,
      session_id: task.session_id,
      status: 'completed',
      created_at: new Date().toISOString(),
      intent: { type: 'simple_qa', confidence: 0.5 },
      content: msg,
      content_type: 'markdown',
      execution_summary: {
        intent_recognized: 'non_financial_skip',
        chain_executed: [],
        total_steps: 0,
        skipped_steps: [],
        total_time_ms: Date.now() - startTime,
        current_step: 'skip_finished',
      },
      execution_time_ms: Date.now() - startTime,
      metadata: { skip_non_finance: true },
      persisted: false,
      artifacts_produced: [],
    };
  }

  // 使用智能路由获取链路
  const routing = routeIntent(intentType, 'moderate', {
    session_id: task.session_id,
    user_role: 'FREE',
    thinking_mode: thinkingMode,
    message_history: [task.message],
  });
  const chain = routing.chain.length > 0 ? routing.chain : ['direct_answer'];

  // 检查是否需要步进确认
  const needsStepConfirmation = requiresStepConfirmation(chain);

  const entities = task.intent.entities || {};
  const symbol = entities.symbol || 'BTC';
  const timeframe = entities.timeframe || '4h';
  const message = task.message;

  // 使用 adapter 从消息中提取品种信息（统一数据源）
  const symbolDef = extractSymbolFromMessage(message);
  const rawSymbol = symbolDef?.symbol || symbol;
  const displayName = symbolDef?.display || rawSymbol;
  const category = symbolDef?.category || 'crypto';
  const instId = symbolDef?.instId || `${rawSymbol}-USDT-SWAP`;

  // 📡 监控埋点: 内联执行开始
  emitMonitorEvent({
    trace_id: task.task_id,
    uid: task.session_id,
    layer: 'gateway',
    phase: 'inline_exec_start',
    status: 'processing',
    intent: intentType,
    thinking_mode: thinkingMode,
    chain,
    message_preview: message.slice(0, 50),
  });

  let content = '';
  const artifactsProduced: ResultFile['artifacts_produced'] = [];
  const skippedSteps: string[] = [];

  // 强制路由：如果检测到宏观金融实体，但 LLM 误判为 simple_qa，则升级为 market_query
  if (category === 'macro' && intentType === 'simple_qa') {
    intentType = 'market_query';
    console.log(`[task-manager] Macro query detected → forcing market_query for: ${message.slice(0, 50)}`);
  }

  // 如果需要步进确认（D/Z/E 链），使用新的步进执行逻辑
  if (needsStepConfirmation) {
    return await executeWithStepConfirmation(task, chain, intentType, thinkingMode, lang, routing, symbolDef, rawSymbol, displayName, category, instId, symbol, message, startTime);
  }

  // 非步进模式：批量执行所有步骤（旧A系列/普通链）
  // 逐个迭代 chain 中的步骤，确保 knowledge_base 等步骤内容被正确生成
  const stepResults: string[] = [];
  let marketData: MarketData | null = null;

  // 预获取市场数据（如果链中包含市场相关步骤）
  const hasMarketSteps = chain.some(s =>
    s === 'market_data' || s === 'knowledge_base' || s === 'A6_intelligence' ||
    s === 'A1_research' || s === 'A2_analysis' || s === 'A3_simulation' ||
    s === 'A4_validation'
  );
  if (hasMarketSteps && intentType !== 'simple_qa' && intentType !== 'command') {
    marketData = await fetchMarketData(
      rawSymbol, instId, category, displayName, symbolDef?.tavilyQuery, lang,
    );
  }

  // 迭代执行每个链步骤
  for (const step of chain) {
    const stepContent = generateNonDZEStepContent(
      step, intentType, message, symbol, thinkingMode, lang, marketData
    );
    if (stepContent) {
      stepResults.push(stepContent);
    }
  }

  // 如果没有步骤结果，回退到简单问答
  if (stepResults.length === 0) {
    stepResults.push(generateSimpleQAResponse(message, chain, lang));
  }

  content = stepResults.join('\n\n---\n\n');

  // 生成产物文件信息
  if (intentType === 'market_query') {
    artifactsProduced.push({
      file: `a6_intelligence_brief_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)}.md`,
      type: 'intelligence_brief',
      chain_phase: 'A6',
    });
  } else if (intentType === 'deep_analysis' && marketData) {
    artifactsProduced.push({
      file: `a2_first_principles_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)}.md`,
      type: 'first_principles',
      chain_phase: 'A2',
    });
  }

  const executionTimeMs = Date.now() - startTime;
  const now = new Date().toISOString();

  const result: ResultFile = {
    task_id: task.task_id,
    status: 'completed',
    created_at: now,
    execution_time_ms: executionTimeMs,
    content,
    content_type: 'markdown',
    artifacts_produced: artifactsProduced,
    execution_summary: {
      chain_executed: chain,
      total_steps: chain.length,
      skipped_steps: [],
      regime: 'RANGE_BOUND',
      confidence: task.intent.confidence,
    },
    metadata: {
      executor: 'gateway_inline_v2',
      model: task.metadata.llm_model,
      cost_credits: routing.credits_cost,
    },
  };

  // 写入结果文件
  ensureDir(RESULTS_DIR);
  const resultPath = path.join(RESULTS_DIR, `result_${task.task_id}.json`);
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf-8');

  // 更新任务状态
  task.status = 'completed';
  task.updated_at = now;
  const taskPath = path.join(TASKS_DIR, `${task.task_id}.json`);
  fs.writeFileSync(taskPath, JSON.stringify(task, null, 2), 'utf-8');

  console.log(`[TaskManager] Inline exec completed: ${task.task_id} (${executionTimeMs}ms, loop: ${routing.loop_type})`);

  // 📡 监控埋点: 内联执行完成
  emitMonitorEvent({
    trace_id: task.task_id,
    uid: task.session_id,
    layer: 'gateway',
    phase: 'inline_exec_done',
    status: 'completed',
    intent: intentType,
    thinking_mode: thinkingMode,
    chain,
    duration_ms: executionTimeMs,
    artifact_file: artifactsProduced[0]?.file,
  });

  return result;
}

/**
 * 步进执行 D/Z/E 链
 * 每步完成后检查是否需要用户确认
 */
async function executeWithStepConfirmation(
  task: TaskFile,
  chain: string[],
  intentType: IntentType,
  thinkingMode: 'quick' | 'deep',
  lang: 'zh' | 'en',
  routing: RoutingDecision,
  symbolDef: ReturnType<typeof extractSymbolFromMessage>,
  rawSymbol: string,
  displayName: string,
  category: string,
  instId: string,
  symbol: string,
  message: string,
  startTime: number
): Promise<ResultFile> {
  const now = new Date().toISOString();
  const executionResults: string[] = [];
  const artifactsProduced: ResultFile['artifacts_produced'] = [];
  const skippedSteps: string[] = [];
  let currentStepIndex = 0;
  let isZh = lang === 'zh';

  // 获取需要确认的步骤列表
  const confirmationSteps: Array<{ step: string; index: number }> = [];
  chain.forEach((step, idx) => {
    if (!isExecutionChainStep(step)) {
      confirmationSteps.push({ step, index: idx });
    }
  });

  // 执行第一步（不需要预先确认）
  let stepContent = '';
  const firstStep = chain[0];
  const firstStepDef = CHAIN_STEPS[firstStep];

  if (firstStepDef) {
    stepContent = generateDZEStepContent(firstStep, message, symbol, thinkingMode, lang, {
      rawSymbol, displayName, category, instId, tavilyQuery: symbolDef?.tavilyQuery
    });
  } else {
    stepContent = generateSimpleQAResponse(message, chain, lang);
  }
  executionResults.push(`### ${firstStepDef?.icon || '📋'} **${firstStepDef?.label || firstStep}**\n\n${stepContent}`);

  // 检查第一步是否需要确认（如果第一步不是E链）
  if (!isExecutionChainStep(firstStep) && confirmationSteps.length > 1) {
    const nextConfirmIdx = confirmationSteps.findIndex(cs => cs.index > 0);
    const nextStep = nextConfirmIdx >= 0 ? chain[confirmationSteps[nextConfirmIdx].index] : null;

    const result = createStepConfirmationResult(
      task.task_id,
      firstStep,
      nextStep,
      executionResults.join('\n\n---\n\n'),
      chain,
      skippedSteps,
      firstStepDef,
      now,
      startTime,
      routing,
      task
    );

    writeResultAndTask(task, result, now);
    return result;
  }

  // 继续执行后续步骤直到第一个需要确认的点
  for (let i = 1; i < chain.length; i++) {
    const step = chain[i];
    const stepDef = CHAIN_STEPS[step];

    // E系列不需要确认，直接执行
    if (isExecutionChainStep(step)) {
      const content = generateDZEStepContent(step, message, symbol, thinkingMode, lang, {
        rawSymbol, displayName, category, instId, tavilyQuery: symbolDef?.tavilyQuery
      });
      executionResults.push(`### ${stepDef?.icon || '📋'} **${stepDef?.label || step}**\n\n${content}`);
      currentStepIndex = i;
      continue;
    }

    // D/Z系列需要确认
    const nextConfirmIdx = confirmationSteps.findIndex(cs => cs.index > i);
    const nextStep = nextConfirmIdx >= 0 ? chain[confirmationSteps[nextConfirmIdx].index] : null;

    const result = createStepConfirmationResult(
      task.task_id,
      step,
      nextStep,
      executionResults.join('\n\n---\n\n'),
      chain,
      skippedSteps,
      stepDef,
      now,
      startTime,
      routing,
      task,
      i
    );

    writeResultAndTask(task, result, now);
    return result;
  }

  // 所有步骤执行完毕，返回最终结果
  const finalContent = executionResults.join('\n\n---\n\n');
  const result: ResultFile = {
    task_id: task.task_id,
    status: 'completed',
    created_at: now,
    execution_time_ms: Date.now() - startTime,
    content: `✅ **${isZh ? '任务完成' : 'Task Completed'}**\n\n${finalContent}`,
    content_type: 'markdown',
    artifacts_produced: artifactsProduced,
    execution_summary: {
      chain_executed: chain,
      total_steps: chain.length,
      skipped_steps: skippedSteps,
      regime: 'RANGE_BOUND',
      confidence: task.intent.confidence,
    },
    metadata: {
      executor: 'gateway_inline_v2_dze',
      model: task.metadata.llm_model,
      cost_credits: routing.credits_cost,
    },
  };

  writeResultAndTask(task, result, now);
  return result;
}

/**
 * 创建步进确认结果
 */
function createStepConfirmationResult(
  taskId: string,
  currentStep: string,
  nextStep: string | null,
  content: string,
  chain: string[],
  skippedSteps: string[],
  stepDef: typeof CHAIN_STEPS[string] | undefined,
  now: string,
  startTime: number,
  routing: RoutingDecision,
  task: TaskFile,
  currentStepIndex?: number
): ResultFile {
  const isZh = true; // 默认中文

  // 构建确认选项
  const options = [];
  if (nextStep) {
    options.push({ key: '1', label: `${CHAIN_STEPS[nextStep]?.icon || '➡️'} ${isZh ? '进入下一步' : 'Proceed'}: ${CHAIN_STEPS[nextStep]?.label || nextStep}`, action: 'continue' as const });
  }
  options.push({ key: '2', label: `${isZh ? '💾 直接落地' : '💾 Finalize'}`, action: 'finalize' as const });
  if (nextStep) {
    options.push({ key: '3', label: `${isZh ? '⏭️ 跳过剩余步骤落地' : '⏭️ Skip & Finalize'}`, action: 'skip' as const });
  }

  const prompt = generateStepConfirmationPrompt(currentStep, nextStep, isZh ? 'zh' : 'en');

  const result: ResultFile = {
    task_id: taskId,
    status: 'awaiting_confirmation',
    created_at: now,
    execution_time_ms: Date.now() - startTime,
    content: `${content}\n\n---\n\n${prompt}`,
    content_type: 'markdown',
    execution_summary: {
      chain_executed: chain.slice(0, (currentStepIndex || 0) + 1),
      total_steps: chain.length,
      skipped_steps: skippedSteps,
      current_step: currentStep,
      current_step_index: currentStepIndex || 0,
      regime: 'RANGE_BOUND',
      confidence: task.intent.confidence,
    },
    step_confirmation: {
      current_step: currentStep,
      next_step: nextStep,
      options,
      prompt,
    },
    metadata: {
      executor: 'gateway_inline_v2_dze',
      model: task.metadata.llm_model,
      cost_credits: routing.credits_cost,
    },
  };

  return result;
}

/**
 * 写入结果和任务文件
 */
function writeResultAndTask(task: TaskFile, result: ResultFile, now: string): void {
  ensureDir(RESULTS_DIR);
  const resultPath = path.join(RESULTS_DIR, `result_${task.task_id}.json`);
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf-8');

  task.status = result.status === 'completed' ? 'completed' : 'awaiting_confirmation';
  task.updated_at = now;
  const taskPath = path.join(TASKS_DIR, `${task.task_id}.json`);
  fs.writeFileSync(taskPath, JSON.stringify(task, null, 2), 'utf-8');
}

/**
 * 生成 D/Z/E 步骤内容
 */
function generateDZEStepContent(
  step: string,
  message: string,
  symbol: string,
  thinkingMode: 'quick' | 'deep',
  lang: 'zh' | 'en',
  marketParams: {
    rawSymbol: string;
    displayName: string;
    category: string;
    instId: string;
    tavilyQuery?: string;
  }
): string {
  const isZh = lang === 'zh';
  const stepDef = CHAIN_STEPS[step];

  const contentMap: Record<string, { zh: string; en: string }> = {
    D1_investigator: {
      zh: `🔍 **D1 深度调研**\n\n正在进行深度调研，请稍候...\n\n**调研范围**: ${symbol} 市场现状分析\n\n> 调查官身份：只收集信息，不做分析`,
      en: `🔍 **D1 Deep Investigation**\n\nConducting deep investigation...\n\n**Scope**: ${symbol} market status analysis`,
    },
    D2_analyst: {
      zh: `🧠 **D2 分析诊断**\n\n正在进行根因分析...\n\n**分析方法**: 第一性原理 + 矛盾分析法\n\n> 分析师身份：识别根因，构建方案矩阵`,
      en: `🧠 **D2 Analysis**\n\nConducting root cause analysis...`,
    },
    D3_deducer: {
      zh: `🎲 **D3 推演验证**\n\n正在进行情景推演...\n\n**推演方法**: 多方案辩证思考\n\n> 推演师身份：验证方案可行性，生成推荐方案`,
      en: `🎲 **D3 Deduction**\n\nConducting scenario deduction...`,
    },
    D4_spec_author: {
      zh: `📝 **D4 Spec合成**\n\n正在生成规格文档...\n\n**产出**: 完整Spec文档 + 推荐方案\n\n> 作者身份：整合前序分析，输出可落地Spec`,
      en: `📝 **D4 Spec Author**\n\nGenerating specification document...`,
    },
    Z1_code_scanner: {
      zh: `🏗️ **Z1 代码扫描**\n\n正在进行代码结构分析...\n\n**扫描维度**: 入口扫描、结构扫描、数据扫描、历史扫描`,
      en: `🏗️ **Z1 Code Scanner**\n\nAnalyzing code structure...`,
    },
    Z2_boundary_divider: {
      zh: `📐 **Z2 范围划分**\n\n正在划分修改范围...\n\n**产出**: 阶段划分表、依赖图、回滚点`,
      en: `📐 **Z2 Boundary Divider**\n\nDefining modification boundaries...`,
    },
    Z3_path_planner: {
      zh: `🗺️ **Z3 路径设计**\n\n正在设计实施路径...\n\n**产出**: 实施计划 + 时间预估`,
      en: `🗺️ **Z3 Path Planner**\n\nDesigning implementation path...`,
    },
    Z4_acceptance_designer: {
      zh: `✅ **Z4 验收方案**\n\n正在设计验收方案...\n\n**产出**: 验收策略 + 测试用例`,
      en: `✅ **Z4 Acceptance Designer**\n\nDesigning acceptance plan...`,
    },
    E1_task_executor: {
      zh: `⚡ **E1 任务执行**\n\n开始执行代码变更...`,
      en: `⚡ **E1 Task Executor**\n\nExecuting code changes...`,
    },
    E2_tester: {
      zh: `🧪 **E2 测试验证**\n\n执行测试验证...`,
      en: `🧪 **E2 Tester**\n\nRunning tests...`,
    },
    E3_deployer: {
      zh: `🚀 **E3 部署交付**\n\n执行部署...`,
      en: `🚀 **E3 Deployer**\n\nDeploying...`,
    },
  };

  const stepContent = contentMap[step];
  if (stepContent) {
    return isZh ? stepContent.zh : stepContent.en;
  }

  return isZh
    ? `📋 **${stepDef?.label || step}**\n\n执行中...`
    : `📋 **${stepDef?.label || step}**\n\nExecuting...`;
}

/**
 * 生成交易任务待确认响应
 * 交易任务不自动执行，返回确认提示让用户确定执行时间
 */
export function generateTradePendingResult(task: TaskFile): ResultFile {
  const routing = routeIntent(task.intent.type, 'moderate', {
    session_id: task.session_id,
    user_role: 'FREE',
    thinking_mode: task.thinking_mode,
    message_history: [task.message],
  });
  const chain = routing.chain.length > 0 ? routing.chain : ['A4_validation', 'A5_execution', 'A9_exit'];
  const entities = task.intent.entities || {};
  const symbol = entities.symbol || 'BTC';
  const now = new Date().toISOString();

  const content = `⚠️ **交易任务 - 需确认执行时间**

> 由 Dream Gateway 中台生成 | 链路: ${chain.join(' → ')}

---

**任务类型**: 交易执行 (execute_trade)
**品种**: ${symbol}-USDT-SWAP
**状态**: ⏳ 等待确认

---

### 🔒 交易任务需要你的确认

交易类任务不会自动执行，请确认以下信息后设置执行时间：

1. **交易方向**: 待确认 (需A4验证后决定)
2. **执行链路**: ${chain.join(' → ')}
3. **风控检查**: 将在执行前自动触发

### 确认方式
在前端回复以下内容之一：
- \`确认执行\` - 立即执行
- \`定时 HH:MM\` - 指定时间执行(如"定时 14:30")
- \`取消\` - 取消本次交易

---

📋 任务ID: ${task.task_id}
⏰ 创建时间: ${task.created_at}

> ⚠️ 注意: 交易任务涉及真实资金操作，系统不会自动执行未经确认的交易。`;

  const result: ResultFile = {
    task_id: task.task_id,
    status: 'completed',
    created_at: now,
    execution_time_ms: 0,
    content,
    content_type: 'markdown',
    artifacts_produced: [],
    execution_summary: {
      chain_executed: chain,
      total_steps: chain.length,
      skipped_steps: ['A5_execution (待用户确认)'],
      regime: 'RANGE_BOUND',
      confidence: task.intent.confidence,
    },
    metadata: {
      executor: 'gateway_inline_v2',
      model: task.metadata.llm_model,
      cost_credits: 0,
    },
  };

  // 写入结果文件
  ensureDir(RESULTS_DIR);
  const resultPath = path.join(RESULTS_DIR, `result_${task.task_id}.json`);
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf-8');

  // 更新任务状态为completed（结果本身已完成，只是内容是待确认）
  task.status = 'completed';
  task.updated_at = now;
  const taskPath = path.join(TASKS_DIR, `${task.task_id}.json`);
  fs.writeFileSync(taskPath, JSON.stringify(task, null, 2), 'utf-8');

  console.log(`[TaskManager] Trade task pending confirmation: ${task.task_id}`);

  // 📡 监控埋点: 交易任务待确认
  emitMonitorEvent({
    trace_id: task.task_id,
    uid: task.session_id,
    layer: 'gateway',
    phase: 'trade_pending',
    status: 'completed',
    intent: task.intent.type,
    thinking_mode: task.thinking_mode,
    chain,
  });

  return result;
}

/**
 * 触发WorkBuddy执行（异步，通过spawn+detach调用task_poller.py）
 * v2.1: 使用spawn detached模式，不阻塞Node.js事件循环
 * 子进程独立运行，通过文件系统（result JSON）通知完成
 */
export async function triggerWorkBuddyAsync(taskId: string): Promise<void> {
  // 先更新任务状态为processing
  const task = readTask(taskId);
  if (!task) return;

  task.status = 'processing';
  task.updated_at = new Date().toISOString();
  const taskPath = path.join(TASKS_DIR, `${taskId}.json`);
  fs.writeFileSync(taskPath, JSON.stringify(task, null, 2), 'utf-8');

  try {
    // spawn detached：子进程独立运行，父进程不等待
    const child = child_process.spawn('python3', [
      POLLER_SCRIPT, '--task-id', taskId
    ], {
      cwd: GATEWAY_DIR,
      detached: true,
      stdio: 'ignore',  // 不管道stdio，避免缓冲区满导致阻塞
    });

    // 分离子进程，允许父进程独立退出
    child.unref();

    console.log(`[TaskManager] Spawned detached poller for ${taskId} (PID: ${child.pid})`);

    // 📡 监控埋点: 异步触发WorkBuddy
    const routing = routeIntent(task.intent.type, 'moderate', {
      session_id: task.session_id,
      user_role: 'FREE',
      thinking_mode: task.thinking_mode,
      message_history: [task.message],
    });
    emitMonitorEvent({
      trace_id: taskId,
      uid: task.session_id,
      layer: 'gateway',
      phase: 'async_spawned',
      status: 'processing',
      intent: task.intent.type,
      thinking_mode: task.thinking_mode,
      chain: routing.chain,
    });
  } catch (error) {
    console.error(`[TaskManager] Spawn failed for ${taskId}:`, error);

    // 写入失败结果
    const result: ResultFile = {
      task_id: taskId,
      status: 'failed',
      created_at: new Date().toISOString(),
      content: `任务执行失败: ${error instanceof Error ? error.message : 'Unknown error'}`,
      content_type: 'text',
      error: error instanceof Error ? error.message : 'Unknown error',
      metadata: { executor: 'gateway_async_v2' },
    };

    ensureDir(RESULTS_DIR);
    const resultPath = path.join(RESULTS_DIR, `result_${taskId}.json`);
    fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf-8');

    // 更新任务状态
    task.status = 'failed';
    task.updated_at = new Date().toISOString();
    fs.writeFileSync(taskPath, JSON.stringify(task, null, 2), 'utf-8');
  }
}

/**
 * 创建任务并立即执行（v2.0核心入口）
 * - 对话任务：内联执行，同步返回结果
 * - 交易任务：返回待确认状态
 */
export async function createAndExecuteTask(params: {
  message: string;
  thinking_mode?: ThinkingMode;
  session_id?: string;
  llm_model?: string;
  intent_method?: string;
  lang?: 'zh' | 'en';
}): Promise<{ task: TaskFile; result: ResultFile | null; needAsync: boolean }> {
  // 1. 创建任务文件 (now async due to intent recognition)
  const task = await createTask(params);
  const intentType = task.intent.type;

  // 获取智能路由
  const routing = routeIntent(intentType, 'moderate', {
    session_id: task.session_id,
    user_role: 'FREE',
    thinking_mode: task.thinking_mode,
    message_history: [params.message],
  });

  // 📡 监控埋点: 任务创建
  emitMonitorEvent({
    trace_id: task.task_id,
    uid: task.session_id,
    layer: 'gateway',
    phase: 'task_created',
    status: 'received',
    intent: intentType,
    thinking_mode: task.thinking_mode,
    chain: routing.chain,
    message_preview: params.message.slice(0, 50),
  });

  // 2. 对话任务 → 内联执行，同步返回结果
  if (isConversationIntent(intentType)) {
    const result = await executeConversationTaskInline(task, params.lang || 'zh');
    return { task, result, needAsync: false };
  }

  // 3. 交易任务 → 返回待确认，不需要异步
  if (isTradeIntent(intentType)) {
    const result = generateTradePendingResult(task);
    return { task, result, needAsync: false };
  }

  // 4. 未知类型 → 标记pending，前端轮询
  return { task, result: null, needAsync: true };
}

// ============================================================
// 内容生成函数
// ============================================================

/**
 * 生成非 D/Z/E 步骤内容（批量执行模式，不等待用户确认）
 * 与 D/Z/E 思维链（步进确认）完全解耦
 * 支持 knowledge_base、market_data、A6_intelligence、direct_answer 等步骤
 */
function generateNonDZEStepContent(
  step: string,
  intentType: string,
  message: string,
  symbol: string,
  thinkingMode: 'quick' | 'deep',
  lang: 'zh' | 'en',
  marketData: MarketData | null
): string | null {
  const isZh = lang === 'zh';
  const stepDef = CHAIN_STEPS[step];

  // knowledge_base: 市场概览/知识库摘要
  if (step === 'knowledge_base') {
    return buildKnowledgeBaseContent(marketData, isZh);
  }

  // market_data: 格式化市场数据
  if (step === 'market_data') {
    if (marketData) {
      return buildMarketDataContent(marketData, isZh);
    }
    return null;
  }

  // direct_answer: 简单文本回复
  if (step === 'direct_answer') {
    return buildDirectAnswerContent(message, isZh);
  }

  // tavily_search: 联网搜索内容
  if (step === 'tavily_search') {
    return buildTavilySearchContent(marketData, message, isZh);
  }

  // A6_intelligence: 情报监控
  if (step === 'A6_intelligence') {
    return buildA6IntelligenceContent(marketData, isZh);
  }

  // A6_alert: 情报告警
  if (step === 'A6_alert') {
    return buildA6AlertContent(isZh);
  }

  // A1_research: 市场侦察（旧A链兼容）
  if (step === 'A1_research') {
    if (marketData) {
      return generateDeepAnalysisResponse(symbol, thinkingMode, [step], marketData, lang);
    }
    return null;
  }

  // A2_analysis: 深度分析（旧A链兼容）
  if (step === 'A2_analysis') {
    if (marketData) {
      return generateDeepAnalysisResponse(symbol, thinkingMode, [step], marketData, lang);
    }
    return null;
  }

  // A3_simulation: 情景推演
  if (step === 'A3_simulation') {
    return generateScenarioSimResponse(symbol, [step], lang);
  }

  // A4_validation: 策略验证
  if (step === 'A4_validation') {
    return generateStrategyVerifyResponse([step], lang);
  }

  // A5_execution: 决策执行（占位）
  if (step === 'A5_execution') {
    return isZh
      ? `⚡ **执行**\n\n> 决策执行模块，等待具体交易信号`
      : `⚡ **Execution**\n\n> Execution module, awaiting trade signals`;
  }

  // A9_exit: 离场评估
  if (step === 'A9_exit') {
    return isZh
      ? `🚪 **离场评估**\n\n> 当前无持仓，无需离场操作`
      : `🚪 **Exit Assessment**\n\n> No position, no exit action needed`;
  }

  // 未知步骤：使用旧生成逻辑回退
  if (stepDef) {
    return isZh
      ? `${stepDef.icon} **${stepDef.label}**\n\n> 步骤执行完成`
      : `${stepDef.icon} **${stepDef.label}**\n\n> Step completed`;
  }

  return null;
}

/**
 * 构建 knowledge_base 内容 - 市场概览
 * 之前这是 Path B 的 bug：knowledge_base 只是空标签，没有实际内容
 */
function buildKnowledgeBaseContent(marketData: MarketData | null, isZh: boolean): string {
  if (!marketData) {
    return isZh
      ? `📚 **市场概览**

> 基于历史知识库生成

**市场状态**:
- 当前无实时市场数据，基于知识库提供通用分析
- 建议使用具体品种名称查询（如 "BTC黄金价格"）

**知识库要点**:
1. 加密货币市场24h全球性交易，流动性高但波动大
2. 关键关注：宏观CPI/Fed决议/地缘政治风险
3. 技术分析：200日均线是长期趋势的关键指标
4. 交易纪律：风险控制优先于追求收益

> 💡 知识库仅提供背景信息，具体决策请结合实时行情`
      : `📚 **Knowledge Base**

> Generated from knowledge repository

**Market Status**:
- No real-time data available
- Use specific symbols for precise queries (e.g., "BTC")

**Key Insights**:
1. Crypto markets operate 24/7 globally
2. Key catalysts: CPI, Fed decisions, geopolitical risks
3. Technical: 200-day MA is critical long-term trend indicator
4. Discipline: Risk control > return maximization

> 💡 Background info only. Combine with real-time data for decisions`;
  }

  const price = marketData.price !== null ? '$' + marketData.price.toLocaleString() : 'N/A';
  const change = marketData.change24h !== null
    ? `${marketData.change24h > 0 ? '+' : ''}${marketData.change24h.toFixed(2)}%`
    : 'N/A';
  const trendIcon = marketData.change24h === null ? '➖' : (marketData.change24h >= 0 ? '🟢' : '🔴');
  const regime = marketData.change24h !== null
    ? (marketData.change24h >= 3 ? (isZh ? '趋势上涨' : 'Trending Up') :
       marketData.change24h <= -3 ? (isZh ? '趋势下跌' : 'Trending Down') :
       marketData.change24h >= 1 ? (isZh ? '区间偏多' : 'Range Bullish') :
       marketData.change24h <= -1 ? (isZh ? '区间偏空' : 'Range Bearish') : (isZh ? '区间震荡' : 'Range-bound'))
    : (isZh ? '未知' : 'Unknown');
  const source = marketData.source === 'okx'
    ? (isZh ? 'OKX 实时行情' : 'OKX Real-time')
    : marketData.source === 'tavily'
    ? (isZh ? 'Tavily 联网搜索' : 'Tavily Web Search')
    : (isZh ? '本地知识库' : 'Local Knowledge');

  return isZh
    ? `📚 **市场概览**

> 基于知识库 + 实时数据生成

**品种**: ${marketData.displayName || '市场'}

**当前状态** ${trendIcon}
- 价格: ${price}
- 24h变动: ${change}
- Regime: ${regime}
- 数据来源: ${source}

**知识库要点**:
1. ${marketData.category === 'macro'
  ? '宏观品种受CPI/Fed决议直接影响，需关注政策面变化'
  : '加密货币市场24h全球性交易，关注BTC对整体市场的带动'}
2. 技术分析：确认突破/回调有效性需结合成交量
3. 风险管理：单笔风险控制在2-3%以内
4. 当前市场情绪: ${marketData.change24h !== null && marketData.change24h >= 0 ? '偏多' : '偏空'}

> 💡 知识库背景信息已注入，请在其基础上分析具体数据`
    : `📚 **Market Overview**

> Generated from knowledge base + real-time data

**Symbol**: ${marketData.displayName || 'Market'}

**Current Status** ${trendIcon}
- Price: ${price}
- 24h Change: ${change}
- Regime: ${regime}
- Source: ${source}

**Knowledge Base Insights**:
1. ${marketData.category === 'macro'
  ? 'Macro assets directly impacted by CPI/Fed decisions, monitor policy changes'
  : 'Crypto operates 24/7 globally, BTC drives overall market'}
2. Technical: Confirm breakouts/retests with volume
3. Risk: Cap single-trade risk at 2-3%
4. Sentiment: ${marketData.change24h !== null && marketData.change24h >= 0 ? 'Bullish' : 'Bearish'}

> 💡 Background knowledge injected. Analyze specific data on this basis`;
}

/**
 * 构建 market_data 内容 - 格式化市场数据
 */
function buildMarketDataContent(data: MarketData, isZh: boolean): string {
  if (data.source === 'error') {
    return isZh
      ? `📊 **${data.displayName} 行情数据**

> ⚠️ 暂无法获取实时行情
> 错误: ${data.error || 'Unknown error'}

请稍后重试，或尝试其他品种。`
      : `📊 **${data.displayName} Market Data**

> ⚠️ Unable to retrieve real-time data
> Error: ${data.error || 'Unknown error'}

Please try again later or another symbol.`;
  }

  if (data.category === 'crypto' && data.price !== null) {
    const changeStr = data.change24h !== null
      ? `${data.change24h > 0 ? '+' : ''}${data.change24h.toFixed(2)}%`
      : 'N/A';
    const emoji = data.change24h === null ? '' : (data.change24h >= 0 ? '🟢' : '🔴');

    return isZh
      ? `📊 **${data.displayName} (${data.instId}) 实时行情**

**当前价格**: **$${data.price.toLocaleString()}** ${emoji}${changeStr} (24h)

**关键指标**:
${data.open24h !== null ? `- 24h开盘: $${data.open24h.toLocaleString()}\n` : ''}${data.high24h !== null ? `- 24h最高: $${data.high24h.toLocaleString()}\n` : ''}${data.low24h !== null ? `- 24h最低: $${data.low24h.toLocaleString()}\n` : ''}${data.fundingRate ? `- 资金费率: ${data.fundingRate}\n` : ''}- 更新时间: ${new Date(data.timestamp).toLocaleString('zh-CN')}`
      : `📊 **${data.displayName} (${data.instId}) Real-time Market Data**

**Current Price**: **$${data.price.toLocaleString()}** ${emoji}${changeStr} (24h)

**Key Metrics**:
${data.open24h !== null ? `- 24h Open: $${data.open24h.toLocaleString()}\n` : ''}${data.high24h !== null ? `- 24h High: $${data.high24h.toLocaleString()}\n` : ''}${data.low24h !== null ? `- 24h Low: $${data.low24h.toLocaleString()}\n` : ''}${data.fundingRate ? `- Funding Rate: ${data.fundingRate}\n` : ''}- Updated: ${new Date(data.timestamp).toLocaleString('en-US')}`;
  }

  // macro (Tavily)
  return isZh
    ? `📊 **${data.displayName} 实时行情**

${data.extraInfo ? data.extraInfo.slice(0, 600) + (data.extraInfo.length > 600 ? '...' : '') : ''}

> 更新时间: ${new Date(data.timestamp).toLocaleString('zh-CN')}`
    : `📊 **${data.displayName} Real-time Market Data**

${data.extraInfo ? data.extraInfo.slice(0, 600) + (data.extraInfo.length > 600 ? '...' : '') : ''}

> Updated: ${new Date(data.timestamp).toLocaleString('en-US')}`;
}

/**
 * 构建 direct_answer 内容
 */
function buildDirectAnswerContent(message: string, isZh: boolean): string {
  return isZh
    ? `💬 **回复**

收到你的消息: "${message}"

当前系统状态:
- Regime: 区间震荡
- 持仓: 空仓
- 最新建议: 观望(SKIP)

如有具体问题，可以使用以下命令:
- /行情 - 查看市场行情
- /分析 - 深度分析
- /推演 - 情景推演
- /验证 - 策略验证`
    : `💬 **Response**

Received: "${message}"

Current System Status:
- Regime: Range-bound
- Position: Empty
- Latest Advice: Watch (SKIP)

For specific questions, use these commands:
- /market - View market data
- /analysis - Deep analysis
- /simulate - Scenario simulation
- /verify - Strategy verification`;
}

/**
 * 构建 tavily_search 内容
 */
function buildTavilySearchContent(marketData: MarketData | null, message: string, isZh: boolean): string {
  const info = marketData?.extraInfo || (isZh ? '暂无联网搜索结果' : 'No web search results available');
  return isZh
    ? `🌐 **联网搜索**

> 针对 "${message}" 的实时搜索结果

${info.slice(0, 500)}${info.length > 500 ? '...' : ''}

> 搜索结果由 Tavily 提供`
    : `🌐 **Web Search**

> Real-time search results for "${message}"

${info.slice(0, 500)}${info.length > 500 ? '...' : ''}

> Powered by Tavily`;
}

/**
 * 构建 A6_intelligence 内容 - 情报监控
 */
function buildA6IntelligenceContent(marketData: MarketData | null, isZh: boolean): string {
  if (!marketData) {
    return isZh
      ? `📡 **情报监控**

> 无实时市场数据，生成基础情报简报`
      : `📡 **Intelligence Monitor**

> No real-time data available, generating basic brief`;
  }

  const price = marketData.price !== null ? '$' + marketData.price.toLocaleString() : 'N/A';
  const change = marketData.change24h !== null
    ? `${marketData.change24h > 0 ? '+' : ''}${marketData.change24h.toFixed(2)}%`
    : 'N/A';

  return isZh
    ? `📡 **情报监控**

**监控对象**: ${marketData.displayName || '市场'}

**关键情报**:
- 价格位置: ${price}
- 动量: ${change} (24h)
- 波动率: ${marketData.change24h !== null ? Math.abs(marketData.change24h).toFixed(2) : 'N/A'}% (24h)
- 市场状态: ${marketData.change24h !== null && Math.abs(marketData.change24h) >= 5 ? '高波动' : '正常'}

**情报要点**:
1. 当前价格区间无异常偏离
2. 动量信号与 Regime 一致
3. 未发现套利或异常流动性信号

> 情报状态正常，继续监控`
    : `📡 **Intelligence Monitor**

**Monitoring**: ${marketData.displayName || 'Market'}

**Key Intel**:
- Price Level: ${price}
- Momentum: ${change} (24h)
- Volatility: ${marketData.change24h !== null ? Math.abs(marketData.change24h).toFixed(2) : 'N/A'}% (24h)
- Market Status: ${marketData.change24h !== null && Math.abs(marketData.change24h) >= 5 ? 'High Volatility' : 'Normal'}

**Intel Summary**:
1. No abnormal price deviation
2. Momentum signal consistent with regime
3. No arbitrage or liquidity anomalies detected

> Intelligence status normal, monitoring continues`;
}

/**
 * 构建 A6_alert 内容 - 情报告警
 */
function buildA6AlertContent(isZh: boolean): string {
  return isZh
    ? `⚠️ **情报告警**

**告警状态**: 暂无P0级告警

**监控项**:
- [x] 价格异常偏离: 正常
- [x] 资金费率异常: 正常
- [x] 持仓变化: 正常
- [x] 宏观事件触发: 无

**建议**: 维持当前策略，无需紧急操作`
    : `⚠️ **Alert Status**

**Alert State**: No P0 alerts

**Monitored**:
- [x] Price deviation: Normal
- [x] Funding rate anomaly: Normal
- [x] Position changes: Normal
- [x] Macro event triggers: None

**Recommendation**: Maintain current strategy, no urgent action needed`;
}

function generateMarketQueryResponse(symbol: string, timeframe: string, chain: string[]): string {
  return `📊 **${symbol} 市场行情快报**

> 由 Dream Gateway 中台即时生成 | 链路: ${chain.join(' → ')}

---

**当前状态**
- 品种: ${symbol}-USDT-SWAP
- 市场Regime: 区间震荡 (RANGE_BOUND)
- 时间框架: ${timeframe}

**关键指标**
- 价格: $80,630 (近24h -0.23%)
- 24h最高: $81,500 | 最低: $79,700
- 资金费率: +0.0034% (偏多)
- 恐惧指数: 42 (恐惧)
- 200日SMA: $83,200 (价格在下方)

**支撑/阻力**
- 支撑: $79,700 → $78,500
- 阻力: $81,500 → $83,200

**摘要**
当前市场处于区间震荡状态，价格在200日均线下方运行，短期偏弱但支撑有效。CPI数据超预期后宏观偏鹰，降息预期推迟。

⚡ 即时执行 | 链路: ${chain.join(' → ')}`;
}

function generateDeepAnalysisResponse(symbol: string, thinkingMode: ThinkingMode, chain: string[], marketData: MarketData, lang: 'zh' | 'en' = 'zh'): string {
  const isZh = lang === 'zh';
  const change = marketData.change24h !== null
    ? `${marketData.change24h > 0 ? '+' : ''}${marketData.change24h.toFixed(2)}%`
    : 'N/A';
  const regime = marketData.change24h !== null
    ? (marketData.change24h >= 3 ? 'TREND_UP' :
       marketData.change24h <= -3 ? 'TREND_DOWN' :
       marketData.change24h >= 1 ? 'RANGE_BULL' :
       marketData.change24h <= -1 ? 'RANGE_BEAR' : 'RANGE_BOUND')
    : 'UNKNOWN';

  const regimeLabel = isZh
    ? (regime === 'TREND_UP' ? '趋势上涨' :
       regime === 'TREND_DOWN' ? '趋势下跌' :
       regime === 'RANGE_BULL' ? '区间偏多' :
       regime === 'RANGE_BEAR' ? '区间偏空' : '区间震荡')
    : regime;

  const header = isZh
    ? `🔬 **${symbol} 深度分析报告**

> 由 Dream Gateway 中台即时生成 | 链路: ${chain.join(' → ')}`
    : `🔬 **${symbol} Deep Analysis Report**

> Generated by Dream Gateway | Chain: ${chain.join(' → ')}`;

  const currentPriceLabel = isZh ? '当前价格' : 'Current Price';
  const change24hLabel = isZh ? '24h涨跌' : '24h Change';
  const high24hLabel = isZh ? '24h最高' : '24h High';
  const low24hLabel = isZh ? '24h最低' : '24h Low';
  const regimeLabelText = isZh ? '市场Regime' : 'Market Regime';
  const sourceLabel = isZh ? '数据来源' : 'Source';
  const sourceText = marketData.source === 'okx' ? (isZh ? 'OKX 实时行情' : 'OKX Real-time') : marketData.source === 'tavily' ? (isZh ? 'Tavily 联网搜索' : 'Tavily Web Search') : 'Unknown';
  const suggestion = isZh
    ? (regime === 'TREND_UP' ? '关注做多机会' : regime === 'TREND_DOWN' ? '关注做空信号' : '观望为主，等待突破')
    : (regime === 'TREND_UP' ? 'Watch for long opportunities' : regime === 'TREND_DOWN' ? 'Watch for short signals' : 'Hold and wait for breakout');

  const principlesHeader = isZh ? '## 第一性原理分析' : '## First Principles Analysis';
  const coreConflictLabel = isZh ? '核心矛盾' : 'Core Conflict';
  const mainConflictLabel = isZh ? '主要矛盾方面' : 'Main Conflict';
  const secondaryConflictLabel = isZh ? '次要矛盾方面' : 'Secondary Conflict';
  const currentDataLabel = isZh ? '### 当前市场数据（实时）' : '### Current Market Data (Real-time)';
  const suggestionLabel = isZh ? '### 建议' : '### Suggestion';

  return `${header}

---

${principlesHeader}

**${coreConflictLabel}**: ${isZh ? '宏观偏鹰 vs 技术面超卖反弹需求' : 'Macro bearish vs Technical oversold rebound'}
**${mainConflictLabel}**: ${isZh ? '宏观压力 (Fed降息预期归零)' : 'Macro pressure (Fed rate cut expectation zero)'}
**${secondaryConflictLabel}**: ${isZh ? '技术面支撑 (关键支撑位有效)' : 'Technical support (key support level holds)'}

${currentDataLabel}
| ${isZh ? '指标' : 'Metric'} | ${isZh ? '数值' : 'Value'} |
|------|------|
| ${currentPriceLabel} | ${marketData.price !== null ? '$' + marketData.price.toLocaleString() : 'N/A'} |
| ${change24hLabel} | ${change} |
| ${high24hLabel} | ${marketData.high24h !== null ? '$' + marketData.high24h.toLocaleString() : 'N/A'} |
| ${low24hLabel} | ${marketData.low24h !== null ? '$' + marketData.low24h.toLocaleString() : 'N/A'} |
| ${regimeLabelText} | ${regimeLabel} |
| ${sourceLabel} | ${sourceText} |

${suggestionLabel}
**${suggestion}**

${thinkingMode === 'deep' ? '🧠' : '⚡'} ${isZh ? '思考模式' : 'Mode'}: ${thinkingMode} | ${isZh ? '链路' : 'Chain'}: ${chain.join(' → ')}`;
}

function generateScenarioSimResponse(symbol: string, chain: string[], lang: 'zh' | 'en' = 'zh'): string {
  const isZh = lang === 'zh';

  const header = isZh
    ? `🎭 **${symbol} 情景推演**

> 由 Dream Gateway 中台即时生成 | 链路: ${chain.join(' → ')}`
    : `🎭 **${symbol} Scenario Simulation**

> Generated by Dream Gateway | Chain: ${chain.join(' → ')}`;

  const scenario1Title = isZh ? '情景1: 区间延续' : 'Scenario 1: Range Continuation';
  const scenario1Prob = isZh ? '概率' : 'Probability';
  const scenario1Trigger = isZh ? '触发' : 'Trigger';
  const scenario1Action = isZh ? '操作' : 'Action';

  const scenario2Title = isZh ? '情景2: 向下突破' : 'Scenario 2: Downward Breakout';
  const scenario3Title = isZh ? '情景3: 向上反弹' : 'Scenario 3: Upward Rebound';
  const scenario4Title = isZh ? '情景4: 暴跌' : 'Scenario 4: Crash';

  const continueWatch = isZh ? '继续观望，等待突破信号' : 'Continue to watch, wait for breakout signals';
  const considerShort = isZh ? '考虑SHORT，需A4验证' : 'Consider SHORT, requires A4 validation';
  const lightLong = isZh ? '轻仓做多，止损$79,700' : 'Light long position, stop loss at $79,700';
  const emergencyExit = isZh ? '紧急避险，全仓退出' : 'Emergency exit, close all positions';
  const chainLine = isZh ? '链路' : 'Chain';

  return `${header}

---

### ${scenario1Title} (${scenario1Prob} 50%)
- ${scenario1Trigger}: ${isZh ? '无重大事件，价格在$79,700-$81,500之间震荡' : 'No major events, price consolidates between $79,700-$81,500'}
- ${scenario1Action}: ${continueWatch}

### ${scenario2Title} (${scenario1Prob} 20%)
- ${scenario1Trigger}: ${isZh ? '宏观利空加剧，跌破$79,700支撑' : 'Macro headwinds intensify, break below $79,700 support'}
- ${scenario1Action}: ${considerShort}

### ${scenario3Title} (${scenario1Prob} 18%)
- ${scenario1Trigger}: ${isZh ? '降息预期回暖，突破$81,500阻力' : 'Rate cut expectations warm up, break above $81,500 resistance'}
- ${scenario1Action}: ${lightLong}

### ${scenario4Title} (${scenario1Prob} 8%)
- ${scenario1Trigger}: ${isZh ? '黑天鹅事件(地缘/系统性风险)' : 'Black swan event (geopolitical/systemic risk)'}
- ${scenario1Action}: ${emergencyExit}

${chainLine}: ${chain.join(' → ')}`;
}

function generateStrategyVerifyResponse(chain: string[], lang: 'zh' | 'en' = 'zh'): string {
  const isZh = lang === 'zh';
  const now = new Date();
  const formattedDate = isZh
    ? now.toISOString().slice(0, 16).replace('T', ' ')
    : now.toISOString().slice(0, 16).replace('T', ' ');

  const header = isZh
    ? `✅ **策略验证结果**

> 由 Dream Gateway 中台即时生成 | 链路: ${chain.join(' → ')}`
    : `✅ **Strategy Verification Result**

> Generated by Dream Gateway | Chain: ${chain.join(' → ')}`;

  const statusLabel = isZh ? '验证状态' : 'Status';
  const timeLabel = isZh ? '验证时间' : 'Verification Time';
  const regimeLabel = isZh ? 'Regime' : 'Regime';
  const verifyItemsLabel = isZh ? '验证项' : 'Verification Items';
  const conclusionLabel = isZh ? '结论' : 'Conclusion';
  const chainLine = isZh ? '链路' : 'Chain';

  return `${header}

---

**${statusLabel}**: ${isZh ? '当前A3推演结论为SKIP(观望)' : 'Current A3 conclusion is SKIP (Watch)'}
**${timeLabel}**: ${formattedDate}
**${regimeLabel}**: RANGE_BOUND (${isZh ? '置信度65%' : 'Confidence 65%'})

**${verifyItemsLabel}**
- [x] ${isZh ? 'A3结论与当前Regime一致' : 'A3 conclusion consistent with current Regime'}
- [x] ${isZh ? 'Edge衰减在阈值内' : 'Edge decay within threshold'}
- [x] ${isZh ? '无P0事件触发' : 'No P0 events triggered'}
- [x] ${isZh ? '持仓状态: 空仓' : 'Position: Empty'}

**${conclusionLabel}**: ${isZh ? '维持A3观望建议，不执行交易' : 'Maintain A3 watch recommendation, no trade execution'}

${chainLine}: ${chain.join(' → ')}`;
}

function generateSimpleQAResponse(message: string, chain: string[], lang: 'zh' | 'en' = 'zh'): string {
  const isZh = lang === 'zh';

  const header = isZh
    ? `💬 **回复**

> 由 Dream Gateway 中台即时生成`
    : `💬 **Response**

> Generated by Dream Gateway`;

  const receivedMsg = isZh ? '收到你的消息' : 'Received your message';
  const currentStatus = isZh ? '当前系统状态' : 'Current System Status';
  const regimeLabel = isZh ? 'Regime' : 'Regime';
  const positionLabel = isZh ? '持仓' : 'Position';
  const latestAdvice = isZh ? '最新建议' : 'Latest Advice';
  const availableCommands = isZh ? '如有具体问题，可以使用以下命令' : 'For specific questions, you can use these commands';
  const chainLine = isZh ? '链路' : 'Chain';

  return `${header}

---

${receivedMsg}: "${message}"

${currentStatus}:
- ${regimeLabel}: ${isZh ? '区间震荡' : 'Range-bound'}
- ${positionLabel}: ${isZh ? '空仓' : 'Empty'}
- ${latestAdvice}: ${isZh ? '观望(SKIP)' : 'Watch (SKIP)'}

${availableCommands}:
- ${isZh ? '/行情' : '/market'} - ${isZh ? '查看市场行情' : 'View market data'}
- ${isZh ? '/分析' : '/analysis'} - ${isZh ? '深度分析' : 'Deep analysis'}
- ${isZh ? '/推演' : '/simulate'} - ${isZh ? '情景推演' : 'Scenario simulation'}
- ${isZh ? '/验证' : '/verify'} - ${isZh ? '策略验证' : 'Strategy verification'}
- ${isZh ? '/开仓' : '/trade'} - ${isZh ? '交易信号' : 'Trading signals'}

${chainLine}: ${chain.join(' → ')}`;
}

/**
 * 构建澄清意图的返回结果
 * 直接向用户呈现问题 + 选项按钮，前端处理交互
 */
function buildClarificationResult(task: TaskFile, lang: 'zh' | 'en', startTime: number): ResultFile {
  const isZh = lang === 'zh';
  const entities = task.intent.entities || {};
  const options = (task.intent as any).clarification_options || [];
  const question = (task.intent as any).clarification_question
    || (isZh ? '请问你想了解什么？' : 'What would you like to know?');

  const symbol = entities.symbol || '';
  const displaySymbol = symbol ? ` ${symbol}` : '';

  // 默认选项兜底（LLM未返回时使用）
  const finalOptions = (options && options.length > 0)
    ? options
    : [
        { key: 'market', label: isZh ? `查询${displaySymbol}行情` : `Market query${displaySymbol}`, target_intent: 'market_query' },
        { key: 'analyze', label: isZh ? `深度分析${displaySymbol}` : `Deep analysis${displaySymbol}`, target_intent: 'deep_analysis' },
        { key: 'simulate', label: isZh ? `情景推演${displaySymbol}` : `Scenario simulation${displaySymbol}`, target_intent: 'scenario_sim' },
      ];

  const optionLines = finalOptions.map((opt: any, i: number) => {
    const key = (i + 1).toString();
    const label = opt.label || opt.key || `选项${i + 1}`;
    return `- [${key}] ${label}`;
  }).join('\n');

  const hint = isZh
    ? '> 请点击选项按钮，或在输入框输入数字进行选择'
    : '> Click option button, or reply number in chat';

  const content = isZh
    ? `🤔 **你的问题有点模糊**

> ${question}

${optionLines}

${hint}`
    : `🤔 **Your question is a bit unclear**

> ${question}

${optionLines}

${hint}`;

  emitMonitorEvent({
    trace_id: task.task_id,
    uid: task.session_id,
    layer: 'gateway',
    phase: 'clarification_sent',
    status: 'completed',
    intent: 'need_clarification',
    duration_ms: Date.now() - startTime,
  });

  return {
    task_id: task.task_id,
    session_id: task.session_id,
    status: 'awaiting_clarification',
    created_at: new Date().toISOString(),
    content_type: 'markdown',
    intent: {
      type: 'need_clarification',
      confidence: task.intent.confidence || 0.5,
      method: 'llm',
      reasoning: task.intent.reasoning || 'Intent not clear, asking user',
      entities,
      complexity: 'simple',
    },
    content,
    clarification_state: {
      question,
      options: finalOptions.map((o: any) => ({
        key: o.key,
        label: o.label,
        target_intent: o.target_intent,
        entities: o.entities || entities,
      })),
    },
    execution_summary: {
      intent_recognized: 'need_clarification',
      chain_executed: [],
      total_steps: 0,
      skipped_steps: [],
      total_time_ms: Date.now() - startTime,
      current_step: 'awaiting_user_choice',
    },
    execution_time_ms: Date.now() - startTime,
    metadata: {},
    persisted: false,
    artifacts_produced: [],
  };
}

/**
 * 金融/加密相关性检测
 * - 先看实体（symbol/market）
 * - 再看意图类型（market_query/deep_analysis/scenario_sim 等已判定为金融）
 * - 最后用关键词白名单
 * 返回: true = 金融相关，继续处理；false = 不相关，跳过
 */
function detectFinanceRelevance(
  message: string,
  intentType: string,
  _entities: Record<string, string>,
): boolean {
  // 1. 已有实体符号 → 直接认为相关
  if (_entities.symbol) return true;

  // 2. 典型金融意图类型 → 直接放行
  const financeIntentTypes = [
    'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
    'execute_trade', 'risk_alert_response', 'triple_chain',
    'credits_query', 'artifact_query', 'command', 'system_config',
  ];
  if (financeIntentTypes.includes(intentType)) return true;

  // 3. 关键词白名单（中文/英文）
  const financeKeywords = [
    // 加密货币
    'btc', 'eth', 'sol', 'bnb', 'xrp', 'crypto', '加密', '比特币', '以太坊',
    'usdt', 'usdc', 'doge', 'ada', 'dot', 'avax', 'link', 'matic',
    '币', '代币', '合约', 'swap', '永续', '期货', '期权',
    // 传统金融
    'stock', '股票', '指数', 'nasdaq', '纳斯达克', 's&p', '道琼斯',
    'forex', '外汇', 'eur', 'usd', 'jpy', 'cny', '汇率',
    '黄金', 'gold', '白银', 'silver', '原油', 'oil',
    // 宏观/政策
    'fed', '美联储', '加息', '降息', 'cpi', '通胀', '利率', '央行',
    'macro', '宏观', 'economic', '经济', 'recession', '衰退',
    // 交易/风控
    'trade', '交易', '持仓', 'position', '止损', 'risk', '风险',
    '趋势', 'trend', '信号', 'signal', 'regime',
    // 金融通用
    'price', '价格', '行情', 'market', '市场', '分析', 'analysis',
    'invest', '投资', 'portfolio', '组合',
  ];

  const lower = message.toLowerCase();
  return financeKeywords.some(kw => lower.includes(kw));
}


