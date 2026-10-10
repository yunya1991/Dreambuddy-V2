/**
 * cognitive-context-fetcher.ts — 大模型认知上下文获取
 *
 * 在 deep 模式下，并行查询认知记忆 + SKILL 索引 + 知识库，
 * 格式化为 LLM prompt 注入文本。
 *
 * 各子系统独立 FAIL-OPEN，互不阻塞。
 */
import { callCognitive } from './cognitive-client';
import { spawn } from 'child_process';
import path from 'path';

const SKILL_ADAPTER = path.join(process.cwd(), 'scripts', 'skill_index_adapter.py');
const KNOWLEDGE_ADAPTER = path.join(process.cwd(), 'scripts', 'knowledge_search_adapter.py');
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const TIMEOUT_MS = 30000;

function spawnAdapter(
  adapterPath: string,
  command: string,
  args: Record<string, unknown>
): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  return new Promise((resolve) => {
    let stdoutBuf = '';
    let settled = false;
    const child = spawn(PYTHON_BIN, [adapterPath, command, JSON.stringify(args)], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({ ok: false, error: `timeout` });
    }, TIMEOUT_MS);
    child.stdout.on('data', (chunk: Buffer) => { stdoutBuf += chunk.toString(); });
    child.stderr.on('data', () => { /* discard */ });
    child.on('error', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, error: 'spawn_failed' });
    });
    child.on('close', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const lines = stdoutBuf.split('\n').filter((l) => l.trim().startsWith('{'));
      const lastLine = lines[lines.length - 1] || '{}';
      try {
        resolve(JSON.parse(lastLine));
      } catch {
        resolve({ ok: false, error: 'parse_failed' });
      }
    });
  });
}

export interface CognitiveContext {
  memories: Array<{ content: string; score: number; id: string; tags: string[] }>;
  skills: Array<{ name: string; description: string; category: string }>;
  knowledge: Array<{ content: string; score: number; source: string; heading: string }>;
}

/**
 * 并行查询认知记忆 + SKILL + 知识库，各子系统独立 FAIL-OPEN。
 */
export async function fetchCognitiveContext(
  query: string,
  topK: number = 3,
  lang: 'zh' | 'en' = 'zh'
): Promise<CognitiveContext> {
  const [recallRes, skillRes, knowledgeRes] = await Promise.all([
    callCognitive('recall', { context: query, top_k: topK, min_quality: 'C' }),
    spawnAdapter(SKILL_ADAPTER, 'query', { trigger: query }),
    spawnAdapter(KNOWLEDGE_ADAPTER, 'search', { query, top_k: topK, method: 'hybrid' }),
  ]);

  const memories: CognitiveContext['memories'] = [];
  if (recallRes.ok && recallRes.data) {
    const raw = (recallRes.data as any)?.memories || [];
    for (const m of raw.slice(0, topK)) {
      memories.push({
        content: m.content || '',
        score: m.score ?? 0,
        id: m.id || '',
        tags: m.tags || [],
      });
    }
  }

  const skills: CognitiveContext['skills'] = [];
  if (skillRes.ok && skillRes.data) {
    const raw = (skillRes.data as any)?.skills || [];
    for (const s of raw.slice(0, topK)) {
      skills.push({
        name: s.name || '',
        description: s.description || '',
        category: s.category || '',
      });
    }
  }

  const knowledge: CognitiveContext['knowledge'] = [];
  if (knowledgeRes.ok && knowledgeRes.data) {
    const raw = (knowledgeRes.data as any)?.results || [];
    for (const r of raw.slice(0, topK)) {
      knowledge.push({
        content: r.content || '',
        score: r.score ?? 0,
        source: r.source || '',
        heading: r.heading || '',
      });
    }
  }

  return { memories, skills, knowledge };
}

/**
 * 将认知上下文格式化为 LLM 注入文本。
 */
export function formatCognitiveContextForLLM(
  ctx: CognitiveContext,
  lang: 'zh' | 'en' = 'zh'
): string {
  const lines: string[] = [];

  const hasMemories = ctx.memories.length > 0;
  const hasSkills = ctx.skills.length > 0;
  const hasKnowledge = ctx.knowledge.length > 0;

  if (!hasMemories && !hasSkills && !hasKnowledge) {
    return ''; // 无认知上下文，不注入
  }

  if (lang === 'zh') {
    if (hasMemories) {
      lines.push('\n--- 认知记忆（相关历史经验）---');
      for (const m of ctx.memories) {
        const tagsStr = m.tags.length > 0 ? ` [${m.tags.join(',')}]` : '';
        const content = m.content.length > 200 ? m.content.slice(0, 200) + '...' : m.content;
        lines.push(`[${m.id}]${tagsStr} ${content}`);
      }
    }

    if (hasSkills) {
      lines.push('\n--- 相关 SKILL ---');
      for (const s of ctx.skills) {
        lines.push(`${s.name}: ${s.description}`);
      }
    }

    if (hasKnowledge) {
      lines.push('\n--- 知识库检索 ---');
      for (const k of ctx.knowledge) {
        const content = k.content.length > 300 ? k.content.slice(0, 300) + '...' : k.content;
        lines.push(`(${k.heading || k.source}) ${content}`);
      }
    }
  } else {
    if (hasMemories) {
      lines.push('\n--- Cognitive Memories (relevant historical experience) ---');
      for (const m of ctx.memories) {
        const tagsStr = m.tags.length > 0 ? ` [${m.tags.join(',')}]` : '';
        const content = m.content.length > 200 ? m.content.slice(0, 200) + '...' : m.content;
        lines.push(`[${m.id}]${tagsStr} ${content}`);
      }
    }

    if (hasSkills) {
      lines.push('\n--- Relevant SKILLs ---');
      for (const s of ctx.skills) {
        lines.push(`${s.name}: ${s.description}`);
      }
    }

    if (hasKnowledge) {
      lines.push('\n--- Knowledge Base ---');
      for (const k of ctx.knowledge) {
        const content = k.content.length > 300 ? k.content.slice(0, 300) + '...' : k.content;
        lines.push(`(${k.heading || k.source}) ${content}`);
      }
    }
  }

  return lines.join('\n') + '\n';
}
