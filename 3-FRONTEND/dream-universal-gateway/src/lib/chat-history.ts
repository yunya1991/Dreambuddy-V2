import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const HISTORY_DIR = path.join(__dirname, '..', '..', 'artifacts', 'chat-history');

export interface ChatHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  task_id?: string;
  intent_type?: string;
}

export interface ChatSessionHistory {
  session_id: string;
  created_at: string;
  updated_at: string;
  messages: ChatHistoryMessage[];
  summary?: string;
  summary_level: number;
  total_tokens: number;
}

function ensureDir(dir: string) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function getHistoryPath(sessionId: string): string {
  ensureDir(HISTORY_DIR);
  return path.join(HISTORY_DIR, `history_${sessionId}.json`);
}

export function loadSessionHistory(sessionId: string): ChatSessionHistory {
  const historyPath = getHistoryPath(sessionId);
  if (fs.existsSync(historyPath)) {
    try {
      const raw = fs.readFileSync(historyPath, 'utf-8');
      return JSON.parse(raw);
    } catch {
      // ignore
    }
  }
  const now = new Date().toISOString();
  return {
    session_id: sessionId,
    created_at: now,
    updated_at: now,
    messages: [],
    summary_level: 0,
    total_tokens: 0,
  };
}

export function saveSessionHistory(history: ChatSessionHistory): void {
  history.updated_at = new Date().toISOString();
  const historyPath = getHistoryPath(history.session_id);
  ensureDir(HISTORY_DIR);
  fs.writeFileSync(historyPath, JSON.stringify(history, null, 2), 'utf-8');
}

export function addUserMessage(sessionId: string, content: string): ChatSessionHistory {
  const history = loadSessionHistory(sessionId);
  history.messages.push({
    role: 'user',
    content,
    timestamp: new Date().toISOString(),
  });
  saveSessionHistory(history);
  return history;
}

export function addAssistantMessage(
  sessionId: string,
  content: string,
  metadata?: { task_id?: string; intent_type?: string }
): ChatSessionHistory {
  const history = loadSessionHistory(sessionId);
  history.messages.push({
    role: 'assistant',
    content,
    timestamp: new Date().toISOString(),
    task_id: metadata?.task_id,
    intent_type: metadata?.intent_type,
  });
  saveSessionHistory(history);
  return history;
}

export function clearSessionHistory(sessionId: string): void {
  const historyPath = getHistoryPath(sessionId);
  if (fs.existsSync(historyPath)) {
    fs.unlinkSync(historyPath);
  }
}

export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 2.5);
}

export function getTotalMessageTokens(history: ChatSessionHistory): number {
  return history.messages.reduce((sum, msg) => sum + estimateTokens(msg.content), 0);
}

export const CONTEXT_COMPRESSION_THRESHOLDS = {
  RAW_MAX_MESSAGES: 10,
  SUMMARY_MAX_MESSAGES: 20,
  GRAPH_MAX_TOKENS: 8000,
};
