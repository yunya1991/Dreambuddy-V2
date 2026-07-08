import {
  loadSessionHistory,
  saveSessionHistory,
  estimateTokens,
  getTotalMessageTokens,
  CONTEXT_COMPRESSION_THRESHOLDS,
  type ChatSessionHistory,
  type ChatHistoryMessage,
} from './chat-history';
import { callLLM } from './orchestration/llm-bridge';

export interface ContextForLLM {
  type: 'raw' | 'summary' | 'graph';
  content: string;
  token_estimate: number;
  message_count: number;
  summary_level: number;
}

export async function getContextForLLM(sessionId: string): Promise<ContextForLLM> {
  const history = loadSessionHistory(sessionId);
  const totalTokens = getTotalMessageTokens(history);
  const msgCount = history.messages.length;

  if (msgCount <= CONTEXT_COMPRESSION_THRESHOLDS.RAW_MAX_MESSAGES * 2) {
    return {
      type: 'raw',
      content: formatRawMessages(history.messages),
      token_estimate: totalTokens,
      message_count: msgCount,
      summary_level: 0,
    };
  }

  if (msgCount <= CONTEXT_COMPRESSION_THRESHOLDS.SUMMARY_MAX_MESSAGES * 2) {
    const summary = await ensureRollingSummary(history);
    const recentMessages = history.messages.slice(-6);
    return {
      type: 'summary',
      content: formatSummaryContext(summary, recentMessages),
      token_estimate: estimateTokens(summary) + getTotalMessageTokens({ ...history, messages: recentMessages } as any),
      message_count: msgCount,
      summary_level: 1,
    };
  }

  const summary = await ensureRollingSummary(history);
  const recentMessages = history.messages.slice(-4);
  return {
    type: 'graph',
    content: formatGraphContext(summary, recentMessages, history),
    token_estimate: estimateTokens(summary) + getTotalMessageTokens({ ...history, messages: recentMessages } as any),
    message_count: msgCount,
    summary_level: 2,
  };
}

function formatRawMessages(messages: ChatHistoryMessage[]): string {
  if (messages.length === 0) return '（无历史对话）';
  return messages
    .map((m) => {
      const role = m.role === 'user' ? '用户' : '助手';
      return `${role}: ${m.content}`;
    })
    .join('\n\n');
}

function formatSummaryContext(summary: string, recentMessages: ChatHistoryMessage[]): string {
  return `【对话历史摘要】
${summary}

【最近对话】
${formatRawMessages(recentMessages)}`;
}

function formatGraphContext(
  summary: string,
  recentMessages: ChatHistoryMessage[],
  history: ChatSessionHistory
): string {
  const topics = extractTopics(history);
  return `【对话核心主题】
${topics}

【对话历史摘要】
${summary}

【最近对话】
${formatRawMessages(recentMessages)}

（注：对话已超过${CONTEXT_COMPRESSION_THRESHOLDS.SUMMARY_MAX_MESSAGES}轮，使用图结构上下文压缩保留核心记忆）`;
}

function extractTopics(history: ChatSessionHistory): string {
  const intentTypes = new Set<string>();
  history.messages.forEach((m) => {
    if (m.intent_type) intentTypes.add(m.intent_type);
  });
  if (intentTypes.size === 0) return '多主题对话';
  return Array.from(intentTypes)
    .map((t) => `- ${t}`)
    .join('\n');
}

async function ensureRollingSummary(history: ChatSessionHistory): Promise<string> {
  const now = Date.now();
  const msgCount = history.messages.length;

  if (history.summary && history.summary_level >= 1 && msgCount < history.messages.length + 5) {
    return history.summary;
  }

  try {
    const messagesToSummarize = history.messages.slice(0, -6);
    if (messagesToSummarize.length < 4) {
      return formatRawMessages(history.messages);
    }

    const previousSummary = history.summary || '';
    const summary = await generateRollingSummary(messagesToSummarize, previousSummary);

    history.summary = summary;
    history.summary_level = 1;
    saveSessionHistory(history);

    return summary;
  } catch (err) {
    console.warn('[context-compression] 摘要生成失败，使用原文:', err instanceof Error ? err.message : err);
    return formatRawMessages(history.messages);
  }
}

async function generateRollingSummary(
  messages: ChatHistoryMessage[],
  previousSummary: string
): Promise<string> {
  const conversationText = messages
    .map((m) => `${m.role === 'user' ? '用户' : '助手'}: ${m.content}`)
    .join('\n\n');

  const systemPrompt = `你是对话摘要引擎。请将以下对话历史压缩为简洁的摘要。

要求：
1. 保留核心议题、关键结论、已确认的事实
2. 保留用户偏好和重要的上下文信息
3. 控制在 300 字以内
4. 如果有之前的摘要，请在其基础上增量更新
5. 使用要点式输出，每点不超过 50 字`;

  const userPrompt = previousSummary
    ? `之前的摘要：
${previousSummary}

新增的对话内容：
${conversationText}

请在之前摘要的基础上，整合新对话内容，生成更新后的完整摘要。`
    : `对话内容：
${conversationText}

请生成对话摘要。`;

  const result = await callLLM({
    prompt: userPrompt,
    systemPrompt,
    temperature: 0.3,
    timeoutMs: 15000,
  });

  return result.content.trim();
}
