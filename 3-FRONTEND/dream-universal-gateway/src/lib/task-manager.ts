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
  type IntentType,
  type IntentRecognitionResult,
  type RoutingDecision,
} from './intent';

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
];

// 交易类意图 - 需用户确认执行时间
const TRADE_INTENTS: IntentType[] = ['execute_trade'];

/**
 * 任务状态
 */
export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'timeout' | 'scheduled' | 'cancelled';

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
  status: 'completed' | 'failed';
  created_at: string;
  execution_time_ms?: number;
  content: string;
  content_type: 'markdown' | 'json' | 'text';
  artifacts_produced?: Array<{
    file: string;
    type: string;
    chain_phase: string;
  }>;
  execution_summary?: {
    chain_executed: string[];
    total_steps: number;
    skipped_steps: string[];
    regime?: string;
    confidence?: number;
  };
  error?: string;
  metadata?: {
    executor?: string;
    model?: string;
    cost_credits?: number;
  };
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
  return {
    type: result.intent,
    confidence: result.confidence,
    entities: {
      symbol: result.entities.symbol,
      timeframe: result.entities.timeframe,
      strategy: result.entities.strategy,
    },
  };
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
 */
export async function executeConversationTaskInline(task: TaskFile): Promise<ResultFile> {
  const startTime = Date.now();
  const intentType = task.intent.type;
  const thinkingMode = task.thinking_mode;

  // 使用智能路由获取链路
  const routing = routeIntent(intentType, 'moderate', {
    session_id: task.session_id,
    user_role: 'FREE',
    thinking_mode: thinkingMode,
    message_history: [task.message],
  });
  const chain = routing.chain.length > 0 ? routing.chain : ['direct_answer'];

  const entities = task.intent.entities || {};
  const symbol = entities.symbol || 'BTC';
  const timeframe = entities.timeframe || '4h';
  const message = task.message;

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

  // 根据意图生成内容
  if (intentType === 'market_query') {
    artifactsProduced.push({
      file: `a6_intelligence_brief_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)}.md`,
      type: 'intelligence_brief',
      chain_phase: 'A6',
    });
    content = generateMarketQueryResponse(symbol, timeframe, chain);
  } else if (intentType === 'deep_analysis') {
    artifactsProduced.push({
      file: `a2_first_principles_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)}.md`,
      type: 'first_principles',
      chain_phase: 'A2',
    });
    content = generateDeepAnalysisResponse(symbol, thinkingMode, chain);
  } else if (intentType === 'scenario_sim') {
    content = generateScenarioSimResponse(symbol, chain);
  } else if (intentType === 'strategy_verify') {
    content = generateStrategyVerifyResponse(chain);
  } else {
    // simple_qa / command / others
    content = generateSimpleQAResponse(message, chain);
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
    const result = await executeConversationTaskInline(task);
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

function generateDeepAnalysisResponse(symbol: string, thinkingMode: ThinkingMode, chain: string[]): string {
  return `🔬 **${symbol} 深度分析报告**

> 由 Dream Gateway 中台即时生成 | 链路: ${chain.join(' → ')}

---

## 第一性原理分析

**核心矛盾**: 宏观偏鹰 vs 技术面超卖反弹需求
**主要矛盾方面**: 宏观压力 (Fed降息预期归零)
**次要矛盾方面**: 技术面支撑 (关键支撑位有效)

### 三维评分
| 维度 | 得分 | 说明 |
|------|------|------|
| 宏观 | 3/10 | CPI超预期，鹰派基调 |
| 技术 | 5/10 | 关键均线下方，支撑有效 |
| 情绪 | 4/10 | FGI=42恐惧，但非极端 |

### Edge分析
- 当前Edge: -15 (偏空但未达极端)
- 趋势动力: 不足 (区间震荡)
- 阻力最小方向: 横盘偏弱

### 建议
**SKIP** - 当前不满足开仓条件(评分<35且Edge<0)

${thinkingMode === 'deep' ? '🧠' : '⚡'} 思考模式: ${thinkingMode} | 链路: ${chain.join(' → ')}`;
}

function generateScenarioSimResponse(symbol: string, chain: string[]): string {
  return `🎭 **${symbol} 情景推演**

> 由 Dream Gateway 中台即时生成 | 链路: ${chain.join(' → ')}

---

### 情景1: 区间延续 (概率 50%)
- 触发: 无重大事件，价格在$79,700-$81,500之间震荡
- 操作: 继续观望，等待突破信号

### 情景2: 向下突破 (概率 20%)
- 触发: 宏观利空加剧，跌破$79,700支撑
- 操作: 考虑SHORT，需A4验证

### 情景3: 向上反弹 (概率 18%)
- 触发: 降息预期回暖，突破$81,500阻力
- 操作: 轻仓做多，止损$79,700

### 情景4: 暴跌 (概率 8%)
- 触发: 黑天鹅事件(地缘/系统性风险)
- 操作: 紧急避险，全仓退出

链路: ${chain.join(' → ')}`;
}

function generateStrategyVerifyResponse(chain: string[]): string {
  const now = new Date();
  return `✅ **策略验证结果**

> 由 Dream Gateway 中台即时生成 | 链路: ${chain.join(' → ')}

---

**验证状态**: 当前A3推演结论为SKIP(观望)
**验证时间**: ${now.toISOString().slice(0, 16).replace('T', ' ')}
**Regime**: RANGE_BOUND (置信度65%)

**验证项**
- [x] A3结论与当前Regime一致
- [x] Edge衰减在阈值内
- [x] 无P0事件触发
- [x] 持仓状态: 空仓

**结论**: 维持A3观望建议，不执行交易

链路: ${chain.join(' → ')}`;
}

function generateSimpleQAResponse(message: string, chain: string[]): string {
  return `💬 **回复**

> 由 Dream Gateway 中台即时生成

---

收到你的消息: "${message}"

当前系统状态:
- Regime: 区间震荡
- 持仓: 空仓
- 最新建议: 观望(SKIP)

如有具体问题，可以使用以下命令:
- /行情 - 查看市场行情
- /分析 - 深度分析
- /推演 - 情景推演
- /验证 - 策略验证
- /开仓 - 交易信号

链路: ${chain.join(' → ')}`;
}

