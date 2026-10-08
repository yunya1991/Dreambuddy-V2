/**
 * KnowledgeIngester — 知识沉淀 SKILL 实现
 * ========================================
 * SKILL 执行完成后（特别是调研类），将产出的知识/案例分类入库 +
 * RAG 向量化 + 认知记录 + 索引更新，形成"执行→沉淀→复用"闭环。
 *
 * 五步流程（SPEC §3.6）:
 *   1. 分类 → 确定入库目录
 *   2. 原子化存储 → 写 .md（frontmatter + 正文）
 *   3. 向量化 → 调用 build_index.py
 *   4. 认知记录 → callCognitive('record', ...)
 *   5. 索引更新 → IndexQueryService.reload()
 *
 * 设计原则:
 *   - HC-8: 知识只新增不修改；交易决策类需人工审核
 *   - FAIL-OPEN: 任一步骤失败不阻塞主流程
 *   - 开关: KNOWLEDGE_INGEST_ENABLED=false 时直接返回
 *
 * 位置: 3.1-FRONTEND/src/lib/knowledge-ingest.ts
 *
 * 复用（避免重复造轮子）:
 *   - build_index.py (2-KNOWLEDGE/9-RAG-INFRA/vector_store/) — RAG 向量化
 *   - callCognitive (cognitive-client.ts) — 认知记录
 *   - index_query_adapter.py (scripts/) — 索引 reload
 */

import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';
import { callCognitive } from './cognitive-client';

// ============================================================
// 1. 类型定义
// ============================================================

export type KnowledgeCategory =
  | 'trading'        // → 2-KNOWLEDGE/1-TRADING/
  | 'external_research' // → 2-KNOWLEDGE/7-EXTERNAL-RESEARCH/
  | 'methodology'   // → 2-KNOWLEDGE/5-METHODOLOGY/
  | 'ai_cognition'  // → 2-KNOWLEDGE/8-AI-COGNITION/
  | 'technical'     // → 2-KNOWLEDGE/2-TECHNICAL/
  | 'theory'        // → 2-KNOWLEDGE/3-THEORY/
  | 'case_study';   // → 2-KNOWLEDGE/10-CASE-STUDY/

export interface KnowledgeMetadata {
  title: string;
  domain: string;
  tags: string[];
  source: string;           // 来源 SKILL 或调研
  category: KnowledgeCategory;
  requires_human_review?: boolean;
}

export interface IngestResult {
  success: boolean;
  stored_path?: string;     // 存储的 .md 文件路径
  memory_id?: string;      // 认知记录返回的 memory_id
  vectorized: boolean;      // 是否成功向量化
  index_md_updated: boolean; // 是否成功更新 INDEX.md
  index_reloaded: boolean;  // 是否成功更新索引
  errors: string[];         // 各步骤错误（FAIL-OPEN 时收集）
  skipped: boolean;         // 是否跳过（开关关闭或需人工审核）
}

// ============================================================
// 2. 配置
// ============================================================

const INGEST_CONFIG = {
  /** 开关: KNOWLEDGE_INGEST_ENABLED=false 时跳过 */
  get enabled(): boolean {
    return process.env.KNOWLEDGE_INGEST_ENABLED !== 'false';
  },
  /** Python 解释器路径 */
  python_bin: process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3',
  /** 子进程超时 */
  timeout_ms: 30000,
};

/** 分类规则: 关键词 → 目录 */
const CATEGORY_KEYWORDS: Record<KnowledgeCategory, string[]> = {
  trading: ['策略', '回测', '仓位', '风控', '马丁', '网格', '止盈', '止损', '交易'],
  external_research: ['市场', '竞品', '行业', '调研', '宏观', '赛道'],
  methodology: ['方法论', '流程', 'TDD', '开发规范', '工作流', '编排'],
  ai_cognition: ['认知', '记忆', '进化', '蒸馏', '贝叶斯', '置信度'],
  technical: ['技术指标', 'K线', '趋势', '支撑阻力', 'MACD', 'RSI'],
  theory: ['理论', '模型', '数学', '统计', '概率', '博弈论'],
  case_study: ['案例', '实战', '复盘', '案例研究'],
};

/** 分类 → 知识库目录映射 */
const CATEGORY_DIRS: Record<KnowledgeCategory, string> = {
  trading: '2-KNOWLEDGE/1-TRADING',
  external_research: '2-KNOWLEDGE/7-EXTERNAL-RESEARCH',
  methodology: '2-KNOWLEDGE/5-METHODOLOGY',
  ai_cognition: '2-KNOWLEDGE/8-AI-COGNITION',
  technical: '2-KNOWLEDGE/2-TECHNICAL',
  theory: '2-KNOWLEDGE/3-THEORY',
  case_study: '2-KNOWLEDGE/10-CASE-STUDY',
};

// ============================================================
// 3. 路径解析
// ============================================================

/** 解析项目根目录（dreambuddy-v2 仓库根） */
function resolveProjectRoot(): string {
  const cwd = process.cwd();
  // cwd 可能是 3.1-FRONTEND/ 或项目根
  if (fs.existsSync(path.join(cwd, '2-KNOWLEDGE'))) {
    return cwd;
  }
  // 尝试 3.1-FRONTEND/..
  const parent = path.dirname(cwd);
  if (fs.existsSync(path.join(parent, '2-KNOWLEDGE'))) {
    return parent;
  }
  // fallback: 绝对路径
  const absRoot = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2';
  if (fs.existsSync(path.join(absRoot, '2-KNOWLEDGE'))) {
    return absRoot;
  }
  return cwd;
}

/** 解析 build_index.py 路径 */
function resolveBuildIndexPath(): string {
  const root = resolveProjectRoot();
  return path.join(root, '2-KNOWLEDGE', '9-RAG-INFRA', 'vector_store', 'build_index.py');
}

/** 解析 index_query_adapter.py 路径 */
function resolveIndexAdapterPath(): string {
  const root = resolveProjectRoot();
  const candidates = [
    path.join(root, 'scripts', 'index_query_adapter.py'),
    path.join(process.cwd(), 'scripts', 'index_query_adapter.py'),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return candidates[0];
}

// ============================================================
// 4. 分类逻辑
// ============================================================

/**
 * 根据内容关键词自动分类
 */
export function classifyContent(content: string, metadata?: Partial<KnowledgeMetadata>): KnowledgeCategory {
  // 如果 metadata 已指定 category，直接使用
  if (metadata?.category) return metadata.category;

  const lowerContent = content.toLowerCase();
  const scores: Record<string, number> = {};

  for (const [cat, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
    scores[cat] = keywords.reduce((sum, kw) => {
      return sum + (content.includes(kw) || lowerContent.includes(kw.toLowerCase()) ? 1 : 0);
    }, 0);
  }

  // 选择得分最高的分类
  let bestCat: KnowledgeCategory = 'methodology'; // 默认
  let bestScore = 0;
  for (const [cat, score] of Object.entries(scores)) {
    if (score > bestScore) {
      bestScore = score;
      bestCat = cat as KnowledgeCategory;
    }
  }

  // 如果所有分类得分为 0，默认 methodology
  return bestCat;
}

/**
 * 检测内容是否为交易决策类（需人工审核）
 */
export function isTradeDecision(content: string): boolean {
  const tradeKeywords = ['direction:', 'entry_price', 'stop_loss', 'take_profit', 'LONG', 'SHORT'];
  return tradeKeywords.some(kw => content.includes(kw));
}

// ============================================================
// 5. 原子化存储
// ============================================================

/**
 * 生成知识文件名: YYYYMMDD-HHmm-<slug>.md
 */
function generateFileName(title: string): string {
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
  const timeStr = now.toTimeString().slice(0, 5).replace(/:/g, '');
  const slug = title
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40) || 'untitled';
  return `${dateStr}-${timeStr}-${slug}.md`;
}

/**
 * 生成 frontmatter + 正文
 */
function buildMarkdownContent(content: string, meta: KnowledgeMetadata): string {
  const now = new Date().toISOString();
  const tags = [...meta.tags, meta.category].filter(Boolean);
  const frontmatter = [
    '---',
    `title: "${meta.title.replace(/"/g, '\\"')}"`,
    `domain: ${meta.domain}`,
    `tags: [${tags.map(t => `"${t}"`).join(', ')}]`,
    `source: "${meta.source}"`,
    `created_at: ${now}`,
    `requires_human_review: ${meta.requires_human_review ? 'true' : 'false'}`,
    '---',
    '',
  ].join('\n');

  return frontmatter + content;
}

/**
 * 存储知识到对应目录
 */
function storeKnowledge(content: string, meta: KnowledgeMetadata): string {
  const root = resolveProjectRoot();
  const categoryDir = CATEGORY_DIRS[meta.category];
  const targetDir = path.join(root, categoryDir);

  // 确保目录存在
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }

  const fileName = generateFileName(meta.title);
  const filePath = path.join(targetDir, fileName);
  const mdContent = buildMarkdownContent(content, meta);

  fs.writeFileSync(filePath, mdContent, 'utf-8');
  return filePath;
}

// ============================================================
// 6. 向量化（调用 build_index.py）
// ============================================================

/**
 * 调用 build_index.py 对知识目录进行增量向量化
 */
async function vectorizeKnowledge(categoryDir: string): Promise<{ success: boolean; error?: string }> {
  const root = resolveProjectRoot();
  const fullDir = path.join(root, categoryDir);
  const scriptPath = resolveBuildIndexPath();
  const scriptDir = path.dirname(scriptPath);

  return new Promise<{ success: boolean; error?: string }>((resolve) => {
    const child = spawn(INGEST_CONFIG.python_bin, [
      scriptPath,
      fullDir,
      '--force', 'false',
    ], {
      cwd: scriptDir,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({ success: false, error: 'vectorize_timeout' });
    }, INGEST_CONFIG.timeout_ms);

    let stderr = '';
    child.stderr.on('data', (chunk: Buffer) => { stderr += chunk.toString(); });

    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({ success: false, error: `spawn_failed: ${err.message}` });
    });

    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve({ success: true });
      } else {
        resolve({ success: false, error: `build_index_exit_${code}: ${stderr.slice(0, 200)}` });
      }
    });
  });
}

// ============================================================
// 7. 认知记录
// ============================================================

/**
 * 调用 callCognitive('record', ...) 记录知识摘要
 */
async function recordKnowledge(
  content: string,
  meta: KnowledgeMetadata,
  storedPath: string,
): Promise<{ memory_id?: string; error?: string }> {
  // 提取摘要（前300字）
  const summary = content.slice(0, 300).replace(/\n/g, ' ');
  const tags = ['knowledge-ingest', meta.category, meta.domain].filter(Boolean).join(',');

  const result = await callCognitive<{ id?: string }>('record', {
    content: `[knowledge-ingest] ${meta.title} | ${summary} | path: ${storedPath}`,
    quality_level: 'B',
    tags,
  });

  if (!result.ok || result.degraded) {
    return { error: result.error || 'record_failed' };
  }
  return { memory_id: result.data?.id };
}

// ============================================================
// 8. INDEX.md 更新（SPEC §3.6 step5: 更新对应目录的 INDEX.md）
// ============================================================

/**
 * 更新目标目录的 INDEX.md，追加新知识条目
 */
function updateIndexMd(storedPath: string, meta: KnowledgeMetadata): { success: boolean; error?: string } {
  try {
    const root = resolveProjectRoot();
    const categoryDir = CATEGORY_DIRS[meta.category];
    const indexMdPath = path.join(root, categoryDir, 'INDEX.md');

    const fileName = path.basename(storedPath);
    const relativePath = `./${fileName}`;
    const tagsStr = meta.tags.join(', ');
    const now = new Date().toISOString().slice(0, 10);

    // INDEX.md 条目格式: | [title](path) | domain | tags | date |
    const entry = `| [${meta.title}](${relativePath}) | ${meta.domain} | ${tagsStr} | ${now} |`;

    if (fs.existsSync(indexMdPath)) {
      // 追加到现有 INDEX.md
      const content = fs.readFileSync(indexMdPath, 'utf-8');
      // 查找表格末尾追加
      const lines = content.split('\n');
      const lastTableLine = lines.map((l, i) => ({ l, i })).filter(x => x.l.startsWith('|')).pop();
      if (lastTableLine) {
        lines.splice(lastTableLine.i + 1, 0, entry);
        fs.writeFileSync(indexMdPath, lines.join('\n'), 'utf-8');
      } else {
        // 没有表格，追加到文件末尾
        fs.appendFileSync(indexMdPath, `\n${entry}\n`, 'utf-8');
      }
    } else {
      // 创建新 INDEX.md
      const header = `# ${meta.category} 知识索引\n\n| 标题 | 领域 | 标签 | 日期 |\n|------|------|------|------|\n`;
      fs.writeFileSync(indexMdPath, header + entry + '\n', 'utf-8');
    }

    return { success: true };
  } catch (e) {
    return { success: false, error: `index_md_update_failed: ${e instanceof Error ? e.message : String(e)}` };
  }
}

// ============================================================
// 9. 索引 reload
// ============================================================

/**
 * 调用 index_query_adapter.py reload 重新扫描索引
 */
function reloadIndex(): Promise<{ success: boolean; error?: string }> {
  const adapterPath = resolveIndexAdapterPath();

  return new Promise<{ success: boolean; error?: string }>((resolve) => {
    const child = spawn(INGEST_CONFIG.python_bin, [
      adapterPath, 'reload',
    ], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({ success: false, error: 'reload_timeout' });
    }, INGEST_CONFIG.timeout_ms);

    child.on('error', () => {
      clearTimeout(timer);
      resolve({ success: false, error: 'reload_spawn_failed' });
    });

    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ success: code === 0, error: code !== 0 ? `reload_exit_${code}` : undefined });
    });
  });
}

// ============================================================
// 9. KnowledgeIngester 主类
// ============================================================

export class KnowledgeIngester {
  /**
   * 知识沉淀主入口
   *
   * @param content 知识内容（markdown 文本）
   * @param metadata 知识元数据（title, domain, tags, source, category）
   * @returns IngestResult
   */
  async ingest(content: string, metadata: KnowledgeMetadata): Promise<IngestResult> {
    const errors: string[] = [];

    // 开关检查
    if (!INGEST_CONFIG.enabled) {
      return { success: false, vectorized: false, index_md_updated: false, index_reloaded: false, errors: ['ingest_disabled'], skipped: true };
    }

    // 步骤1: 分类
    const category = classifyContent(content, metadata);
    const meta: KnowledgeMetadata = { ...metadata, category };

    // 交易决策类检查
    if (isTradeDecision(content)) {
      meta.requires_human_review = true;
    }

    // 交易决策类需人工审核，不自动入库
    if (meta.requires_human_review) {
      return {
        success: false,
        vectorized: false,
        index_md_updated: false,
        index_reloaded: false,
        errors: ['requires_human_review'],
        skipped: true,
      };
    }

    // 步骤2: 原子化存储
    let storedPath = '';
    try {
      storedPath = storeKnowledge(content, meta);
    } catch (e) {
      errors.push(`store_failed: ${e instanceof Error ? e.message : String(e)}`);
      return { success: false, vectorized: false, index_md_updated: false, index_reloaded: false, errors, skipped: false };
    }

    // 步骤3: 向量化（FAIL-OPEN）
    const categoryDir = CATEGORY_DIRS[category];
    const vectorResult = await vectorizeKnowledge(categoryDir);
    if (!vectorResult.success) {
      errors.push(vectorResult.error || 'vectorize_failed');
    }

    // 步骤3.5: 更新 INDEX.md（SPEC §3.6 step5: 更新对应目录的 INDEX.md）
    const indexMdResult = updateIndexMd(storedPath, meta);
    if (!indexMdResult.success) {
      errors.push(indexMdResult.error || 'index_md_update_failed');
    }

    // 步骤4: 认知记录（FAIL-OPEN）
    const recordResult = await recordKnowledge(content, meta, storedPath);
    if (recordResult.error) {
      errors.push(recordResult.error);
    }

    // 步骤5: 索引更新（FAIL-OPEN）
    const reloadResult = await reloadIndex();
    if (!reloadResult.success) {
      errors.push(reloadResult.error || 'reload_failed');
    }

    return {
      success: true, // 存储成功即视为成功，后续步骤 FAIL-OPEN
      stored_path: storedPath,
      memory_id: recordResult.memory_id,
      vectorized: vectorResult.success,
      index_md_updated: indexMdResult.success,
      index_reloaded: reloadResult.success,
      errors,
      skipped: false,
    };
  }

  /**
   * 批量入库
   */
  async ingestBatch(items: Array<{ content: string; metadata: KnowledgeMetadata }>): Promise<IngestResult[]> {
    return Promise.all(items.map(item => this.ingest(item.content, item.metadata)));
  }
}

// 单例导出
let _instance: KnowledgeIngester | null = null;
export function getKnowledgeIngester(): KnowledgeIngester {
  if (!_instance) _instance = new KnowledgeIngester();
  return _instance;
}
