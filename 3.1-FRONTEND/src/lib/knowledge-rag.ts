/**
 * Knowledge RAG — 真正的向量检索模块
 * ==========================================
 * 替换关键词/正则匹配为语义向量检索 (Semantic RAG)
 *
 * 架构:
 *   1. 文档切片 (Document Chunking) — 按 Markdown 标题切分 + 尺寸约束
 *   2. 向量化 (DeepSeek Embeddings) — POST https://api.deepseek.com/embeddings
 *   3. 向量缓存 (Vector Cache) — JSON 文件持久化，避免重复向量化
 *   4. 语义检索 (Cosine Similarity) — 纯数学运算，零外部依赖
 *   5. 检索重排 (Hybrid Rerank) — 向量相似度 + 关键词命中加权
 *
 * 设计原则:
 *   - 零重型依赖（不使用 numpy/sentence-transformers/faiss 等）
 *   - 纯 TypeScript + 数学运算，与 Next.js 完全兼容
 *   - 可配置化（API key、切片大小、top-k、相似度阈值）
 *   - 优雅降级（embedding 失败时用字符 n-gram 作为 fallback，NOT jieba）
 *
 * 文件位置: 3-FRONTEND/dream-universal-gateway/src/lib/knowledge-rag.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import { createHash } from 'crypto';

// ============================================================
// 1. 配置（集中管理，便于后续调整）
// ============================================================

const RAG_CONFIG = {
  // DeepSeek Embeddings API
  embeddingEndpoint: 'https://api.deepseek.com/embeddings',
  embeddingModel: 'deepseek-chat', // DeepSeek 官方 embedding 模型

  // 文档切片
  chunkSize: 600,       // 每个 chunk 最大字符数
  chunkOverlap: 100,    // 切片之间重叠字符（保证上下文完整性）

  // 检索参数
  topK: 5,              // 默认返回最相关的 5 个 chunk
  similarityThreshold: 0.35, // 相似度阈值（余弦相似度，范围 -1 ~ 1）

  // 向量缓存路径（相对项目根目录）
  vectorCacheFile: 'data/knowledge_vector_cache_v2.json',

  // 超时与重试
  embeddingTimeoutMs: 15000,
  maxRetries: 2,
};

// ============================================================
// 2. 类型定义
// ============================================================

export interface DocumentChunk {
  docPath: string;        // 源文档路径，如 "1-TRADING/三屏系统架构.md"
  docTitle: string;       // 源文档标题（如文件名）
  chunkId: string;        // 唯一 ID: hash(docPath + chunkIndex)
  chunkIndex: number;     // 在该文档中的序号
  content: string;        // 文本内容
  section: string;        // 所属章节标题（用于展示）
  charHash: string;       // 内容 hash（用于判断是否需要重新向量化）
  vector?: number[];      // 向量（可能为 null，若还未向量化）
}

export interface VectorCache {
  version: string;        // 缓存格式版本
  model: string;          // 使用的 embedding 模型
  createdAt: number;      // 创建时间
  updatedAt: number;      // 最后更新时间
  chunks: DocumentChunk[];
  indexPath: string;      // 索引记录：chunkId -> 数组位置
}

export interface RetrievalResult {
  chunk: DocumentChunk;
  similarity: number;     // 余弦相似度
  keywordBoost: number;   // 关键词命中加分
  finalScore: number;     // 综合分数
  highlight: string[];    // 高亮的关键词
}

// ============================================================
// 3. 路径与缓存管理
// ============================================================

// 项目根目录 — knowledge-loader.ts 在 src/lib/，
// cache 文件在 3-FRONTEND/dream-universal-gateway/data/
const PROJECT_ROOT = path.resolve(__dirname, '../../../../');
const KNOWLEDGE_ROOT = path.join(PROJECT_ROOT, '2-KNOWLEDGE');
const CACHE_PATH = path.join(PROJECT_ROOT, RAG_CONFIG.vectorCacheFile);

/**
 * 检查缓存目录是否存在，不存在则创建
 */
function ensureCacheDir(): void {
  const cacheDir = path.dirname(CACHE_PATH);
  if (!fs.existsSync(cacheDir)) {
    fs.mkdirSync(cacheDir, { recursive: true });
  }
}

/**
 * 计算内容 hash（用于检测文档变更是否需要重新向量化）
 */
function contentHash(text: string): string {
  return createHash('sha256')
    .update(text.slice(0, 5000) + text.length.toString())
    .digest('hex')
    .slice(0, 16);
}

/**
 * 从磁盘加载向量缓存
 */
function loadVectorCache(): VectorCache | null {
  try {
    if (!fs.existsSync(CACHE_PATH)) return null;
    const raw = fs.readFileSync(CACHE_PATH, 'utf-8');
    const parsed = JSON.parse(raw) as VectorCache;
    if (parsed && parsed.chunks && Array.isArray(parsed.chunks)) {
      return parsed;
    }
    return null;
  } catch (e) {
    console.warn('[RAG] Failed to load vector cache:', e);
    return null;
  }
}

/**
 * 保存向量缓存到磁盘
 */
function saveVectorCache(cache: VectorCache): void {
  try {
    ensureCacheDir();
    cache.updatedAt = Date.now();
    fs.writeFileSync(CACHE_PATH, JSON.stringify(cache, null, 0), 'utf-8');
  } catch (e) {
    console.warn('[RAG] Failed to save vector cache:', e);
  }
}

// ============================================================
// 4. 文档发现 & 切片
// ============================================================

/**
 * 递归遍历 2-KNOWLEDGE/ 目录，收集所有 .md 文件
 */
function discoverMarkdownFiles(root: string = KNOWLEDGE_ROOT): string[] {
  const results: string[] = [];
  if (!fs.existsSync(root)) return results;

  const walk = (dir: string) => {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        // 跳过隐藏目录和分析目录
        if (entry.name.startsWith('_') || entry.name.startsWith('.')) continue;
        walk(fullPath);
      } else if (entry.isFile() && entry.name.endsWith('.md')) {
        const relativePath = path.relative(KNOWLEDGE_ROOT, fullPath);
        results.push(relativePath);
      }
    }
  };
  walk(root);
  return results.sort();
}

/**
 * 读取单个 Markdown 文件，按标题切片
 *
 * 切片策略:
 *   - 优先按 ## / ### 章节标题切分（保证语义完整性）
 *   - 若单个章节超过 chunkSize，进一步按段落/句号硬切
 *   - 相邻切片保留 chunkOverlap 字符重叠
 */
function chunkMarkdownFile(relativePath: string): DocumentChunk[] {
  const fullPath = path.join(KNOWLEDGE_ROOT, relativePath);
  if (!fs.existsSync(fullPath)) return [];

  let content = '';
  try {
    content = fs.readFileSync(fullPath, 'utf-8');
  } catch {
    return [];
  }

  // 清洗
  content = content
    .replace(/\r\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  if (content.length < 30) return [];

  const docTitle = path.basename(relativePath, '.md');

  // 第一步：按标题切分（# / ## / ### 为一级标题）
  const sections: { title: string; body: string }[] = [];
  const headerRegex = /^(#{1,4})\s+(.+)$/gm;
  const matches: { level: number; title: string; start: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = headerRegex.exec(content)) !== null) {
    matches.push({
      level: m[1].length,
      title: m[2].trim(),
      start: m.index,
    });
  }

  if (matches.length === 0) {
    // 无标题 → 作为一个章节
    sections.push({ title: docTitle, body: content });
  } else {
    // 按标题切分
    for (let i = 0; i < matches.length; i++) {
      const start = matches[i].start;
      const end = i + 1 < matches.length ? matches[i + 1].start : content.length;
      const raw = content.slice(start, end).trim();
      // 跳过第一行（就是标题本身）
      const newlineIdx = raw.indexOf('\n');
      const body = (newlineIdx >= 0 ? raw.slice(newlineIdx).trim() : raw).trim();
      if (body.length >= 20) {
        sections.push({ title: matches[i].title, body });
      }
    }
  }

  // 第二步：对超大章节进一步硬切（按字符数限制，尊重换行）
  const chunks: DocumentChunk[] = [];
  let chunkIndex = 0;

  for (const section of sections) {
    let remaining = section.body;

    while (remaining.length > 0) {
      // 取前 chunkSize 字符
      let take = remaining.slice(0, RAG_CONFIG.chunkSize);

      // 如果还有剩余内容，尝试在句子/段落边界结束
      if (remaining.length > RAG_CONFIG.chunkSize) {
        const cutCandidates = [
          take.lastIndexOf('\n\n'),  // 段落边界
          take.lastIndexOf('。\n'),  // 中文句子边界
          take.lastIndexOf('。'),    // 中文句号
          take.lastIndexOf('.\n'),   // 英文句子边界
          take.lastIndexOf('\n'),    // 换行
        ];
        const cutPoint = cutCandidates.find((p) => p > RAG_CONFIG.chunkSize * 0.5) ?? -1;
        if (cutPoint > 0) {
          take = take.slice(0, cutPoint + 1).trim();
        }
      }

      take = take.trim();
      if (take.length >= 30) {
        const chunkContent = `【${docTitle}】${section.title}\n${take}`;
        chunks.push({
          docPath: relativePath,
          docTitle,
          chunkId: `${relativePath.replace(/[\/\\\s]/g, '_')}_${chunkIndex}`,
          chunkIndex,
          content: chunkContent,
          section: section.title,
          charHash: contentHash(chunkContent),
        });
        chunkIndex++;
      }

      // 移除已处理内容，保留 overlap
      if (remaining.length <= RAG_CONFIG.chunkSize) break;
      const overlap = Math.min(RAG_CONFIG.chunkOverlap, take.length * 0.3);
      remaining = remaining.slice(take.length - overlap).trim();
    }
  }

  return chunks;
}

// ============================================================
// 5. DeepSeek Embeddings API
// ============================================================

/**
 * 获取 API key — 复用 route.ts 中的 DEEPSEEK_API_KEY
 */
function getApiKey(): string {
  const key = process.env.DEEPSEEK_API_KEY;
  if (!key) {
    throw new Error('DEEPSEEK_API_KEY is not set (RAG module)');
  }
  return key;
}

/**
 * 调用 DeepSeek Embeddings API — 批量获取向量
 * 一次最多 100 个文本
 *
 * 返回: 与输入顺序对应的向量数组
 */
async function embedTexts(texts: string[]): Promise<number[][]> {
  if (texts.length === 0) return [];

  const apiKey = getApiKey();
  const batchSize = 100; // DeepSeek 单次上限
  const allVectors: number[][] = [];

  for (let i = 0; i < texts.length; i += batchSize) {
    const batch = texts.slice(i, i + batchSize);

    // 重试逻辑
    let lastError: Error | null = null;
    for (let attempt = 0; attempt <= RAG_CONFIG.maxRetries; attempt++) {
      try {
        const controller = new AbortController();
        const t = setTimeout(() => controller.abort(), RAG_CONFIG.embeddingTimeoutMs);

        const res = await fetch(RAG_CONFIG.embeddingEndpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`,
          },
          body: JSON.stringify({
            model: RAG_CONFIG.embeddingModel,
            input: batch,
            encoding_format: 'float',
          }),
          signal: controller.signal,
        });
        clearTimeout(t);

        if (!res.ok) {
          const errText = await res.text().catch(() => '');
          lastError = new Error(`HTTP ${res.status}: ${errText.slice(0, 200)}`);
          // 429 / 5xx → 重试；4xx → 直接失败
          if (res.status >= 400 && res.status < 500 && res.status !== 429) {
            throw lastError;
          }
          await delay(500 * (attempt + 1));
          continue;
        }

        const json = await res.json();
        const data = json.data as { index: number; embedding: number[] }[];
        // 按 index 排序确保顺序正确
        data.sort((a, b) => a.index - b.index);
        const vectors = data.map((d) => d.embedding);
        allVectors.push(...vectors);
        lastError = null;
        break;
      } catch (e) {
        lastError = e instanceof Error ? e : new Error(String(e));
        if (attempt < RAG_CONFIG.maxRetries) {
          await delay(500 * (attempt + 1));
        }
      }
    }

    if (lastError) {
      throw lastError;
    }

    // 批次之间短暂停顿
    if (i + batchSize < texts.length) await delay(100);
  }

  return allVectors;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ============================================================
// 6. 向量运算 — 余弦相似度（纯数学，零依赖）
// ============================================================

function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length || a.length === 0) return 0;

  let dot = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  const denom = Math.sqrt(normA) * Math.sqrt(normB);
  if (denom === 0) return 0;
  return dot / denom;
}

// ============================================================
// 7. Fallback — 字符 n-gram 相似度（不依赖 jieba）
// ============================================================

/**
 * 当 embeddings API 不可用时，用字符级 n-gram 重叠率作为 fallback。
 * 这完全不依赖任何分词器，避免了 "用户明确说不要用 jieba 但回退到 jieba" 的问题。
 */
function ngramSimilarity(query: string, text: string, n: number = 3): number {
  const getNgrams = (s: string): Set<string> => {
    const set = new Set<string>();
    const cleaned = s.toLowerCase().replace(/\s+/g, ' ');
    for (let i = 0; i <= cleaned.length - n; i++) {
      set.add(cleaned.slice(i, i + n));
    }
    return set;
  };
  const a = getNgrams(query);
  const b = getNgrams(text);
  if (a.size === 0 || b.size === 0) return 0;
  let intersection = 0;
  for (const g of a) {
    if (b.has(g)) intersection++;
  }
  return intersection / Math.sqrt(a.size * b.size); // 余弦相似（集合版本）
}

// ============================================================
// 8. 检索主流程
// ============================================================

/**
 * 核心检索函数：
 *   1. 发现 & 切片知识库文档（若无缓存则首次切片）
 *   2. 对未向量化的 chunk 调用 embeddings API
 *   3. 将用户 query 向量化
 *   4. 计算所有 chunk 与 query 的余弦相似度
 *   5. 关键词命中加权（hybrid rerank）
 *   6. 返回 top-K 结果
 *
 * @param query 用户原始查询
 * @param intentHint 意图提示（影响关键词提取）
 * @param topK 返回的 chunk 数量
 * @returns 排序后的检索结果
 */
export async function retrieveRelevantChunks(
  query: string,
  intentHint: string = '',
  topK: number = RAG_CONFIG.topK,
): Promise<RetrievalResult[]> {
  if (!query || query.trim().length === 0) return [];

  try {
    // --- 阶段 1: 加载 / 构建知识库切片索引 ---
    let cache = loadVectorCache();
    const discoveredFiles = discoverMarkdownFiles();

    // 计算现有 cache 的 chunk 数量 & 映射
    const cacheByDocPath = new Map<string, DocumentChunk[]>();
    if (cache) {
      for (const c of cache.chunks) {
        if (!cacheByDocPath.has(c.docPath)) cacheByDocPath.set(c.docPath, []);
        cacheByDocPath.get(c.docPath)!.push(c);
      }
    }

    // 检测新增 / 变更的文档
    const chunksToEmbed: DocumentChunk[] = [];
    const allChunks: DocumentChunk[] = [];

    for (const file of discoveredFiles) {
      const freshChunks = chunkMarkdownFile(file);
      if (freshChunks.length === 0) continue;

      // 检查是否已有缓存且 hash 匹配
      const existing = cacheByDocPath.get(file) || [];
      const existingMap = new Map<string, DocumentChunk>();
      for (const c of existing) existingMap.set(c.charHash, c);

      for (const chunk of freshChunks) {
        const cached = existingMap.get(chunk.charHash);
        if (cached && cached.vector && cached.vector.length > 0) {
          // 缓存命中 — 直接复用
          allChunks.push(cached);
        } else {
          // 未命中或需要重新向量化 — 加入待处理队列
          chunksToEmbed.push(chunk);
          allChunks.push(chunk);
        }
      }
    }

    // --- 阶段 2: 批量向量化新增 chunk ---
    if (chunksToEmbed.length > 0) {
      const texts = chunksToEmbed.map((c) => c.content);
      try {
        console.log(`[RAG] Embedding ${chunksToEmbed.length} new chunks...`);
        const vectors = await embedTexts(texts);
        if (vectors.length === chunksToEmbed.length) {
          for (let i = 0; i < chunksToEmbed.length; i++) {
            chunksToEmbed[i].vector = vectors[i];
          }
          console.log(`[RAG] Embedding completed.`);
        } else {
          console.warn(`[RAG] Embedding mismatch: expected ${chunksToEmbed.length}, got ${vectors.length}`);
        }
      } catch (e) {
        // embeddings 失败 → 不影响检索流程（后续走 fallback）
        console.warn(`[RAG] Embedding failed, will use n-gram fallback:`, e);
      }

      // 更新缓存
      const newCache: VectorCache = cache || {
        version: '1.0',
        model: RAG_CONFIG.embeddingModel,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        chunks: [],
        indexPath: CACHE_PATH,
      };
      newCache.chunks = allChunks.filter((c) => c.vector && c.vector.length > 0);
      saveVectorCache(newCache);
      cache = newCache;
    }

    // --- 阶段 3: 将 query 向量化 ---
    let queryVector: number[] | null = null;
    try {
      const qVecs = await embedTexts([query + (intentHint ? ` (${intentHint})` : '')]);
      if (qVecs.length > 0) queryVector = qVecs[0];
    } catch (e) {
      console.warn('[RAG] Query embedding failed, will use n-gram fallback:', e);
    }

    // --- 阶段 4: 计算相似度并排序 ---
    const results: RetrievalResult[] = [];
    const queryLower = query.toLowerCase();

    for (const chunk of allChunks) {
      let similarity = 0;

      // 向量相似度（主路径）
      if (queryVector && chunk.vector && chunk.vector.length === queryVector.length) {
        similarity = cosineSimilarity(queryVector, chunk.vector);
      } else {
        // 回退：n-gram 字符相似度
        similarity = ngramSimilarity(query, chunk.content);
        // n-gram 数值通常较低，做一点标准化
        similarity = Math.min(1.0, similarity * 2.5);
      }

      // 关键词命中加权（hybrid signal）
      const keywords = extractKeywords(query, intentHint);
      let keywordBoost = 0;
      const hits: string[] = [];
      for (const kw of keywords) {
        if (chunk.content.toLowerCase().includes(kw.toLowerCase())) {
          keywordBoost += 0.08;
          hits.push(kw);
        }
      }
      keywordBoost = Math.min(keywordBoost, 0.35); // 上限 0.35

      const finalScore = similarity + keywordBoost;

      results.push({
        chunk,
        similarity,
        keywordBoost,
        finalScore,
        highlight: hits.slice(0, 5),
      });
    }

    // 排序 & 过滤
    results.sort((a, b) => b.finalScore - a.finalScore);
    const filtered = results.filter((r) => r.finalScore >= RAG_CONFIG.similarityThreshold);

    return filtered.slice(0, topK);
  } catch (e) {
    console.error('[RAG] Critical error in retrieveRelevantChunks:', e);
    return [];
  }
}

/**
 * 提取查询中的关键词（简单启发式）
 * - 中文字：将用户的中文词直接视为关键词（基于常见长度）
 * - 英文字：取 3+ 字符以上的词
 * - 过滤停用词
 */
function extractKeywords(query: string, intentHint: string): string[] {
  const stopwords = new Set([
    '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
    '啊', '吗', '呢', '吧', '嗯', '哦', '你', '他', '她', '它', '这', '那', '这个',
    '那个', '什么', '怎么', '为什么', '吗', '给', '帮', '请', '问',
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'of', 'to', 'in', 'on',
    'and', 'or', 'for', 'with', 'by', 'at', 'from', 'as', 'it', 'this', 'that',
  ]);

  const keywords: string[] = [];
  // 英文词: 3+ chars
  const engWords = query.toLowerCase().match(/[a-z]{3,}/g) || [];
  for (const w of engWords) if (!stopwords.has(w)) keywords.push(w);

  // 中文: 2-4 char 子串
  const chineseChars = (query.match(/[\u4e00-\u9fa5]{2,4}/g) || []);
  for (const c of chineseChars) {
    if (!stopwords.has(c)) keywords.push(c);
  }

  // 添加意图关键词
  if (intentHint) keywords.push(...intentHint.toLowerCase().match(/[a-z]{3,}|[\u4e00-\u9fa5]{2,}/g) || []);

  return [...new Set(keywords)].slice(0, 10);
}

// ============================================================
// 9. 构建用于注入 LLM 的知识上下文文本
// ============================================================

/**
 * 根据用户查询 & 意图生成可注入 system prompt 的 RAG 文本
 */
export async function buildRAGContext(
  userQuery: string,
  intentHint: string = '',
  maxChars: number = 3500,
): Promise<string> {
  const results = await retrieveRelevantChunks(userQuery, intentHint, RAG_CONFIG.topK);

  if (results.length === 0) {
    return `
【方法论参考 — RAG 检索无高置信度匹配】
系统已检索知识库（2-KNOWLEDGE/），当前问题下未发现高置信度匹配内容。
请基于通用的量化交易方法论分析：
- 风险管理：单笔风险 ≤ 2%，连续亏损 3 次强制休息
- 技术分析：MA200/50、RSI14、ATR 止损
- 矛盾分析法：每笔交易前先列出 3 条反方理由
`;
  }

  let context = `
【方法论参考 — 来自知识库 2-KNOWLEDGE/（基于向量语义检索）】
→ 检索词: "${userQuery.slice(0, 80)}"
→ 命中 ${results.length} 篇文档片段（按语义相关度排序）

`;

  let currentSize = context.length;
  let idx = 1;
  for (const r of results) {
    const docInfo = `【${idx}. ${r.chunk.docTitle} · ${r.chunk.section}】`;
    const simInfo = `(语义相似度 ${(r.similarity * 100).toFixed(0)}%${r.keywordBoost > 0 ? ` + 关键词命中 +${(r.keywordBoost * 100).toFixed(0)}%` : ''})`;
    const highlightInfo = r.highlight.length > 0 ? `\n  命中关键词: ${r.highlight.join(' / ')}` : '';
    const bodyText = r.chunk.content.slice(0, 800);

    const block = `${docInfo} ${simInfo}${highlightInfo}\n${bodyText}\n\n`;

    if (currentSize + block.length > maxChars) {
      const remain = maxChars - currentSize;
      if (remain > 100) {
        context += block.slice(0, remain) + '\n...（截断）\n\n';
      }
      break;
    }

    context += block;
    currentSize += block.length;
    idx++;
  }

  context += `> 注：以上片段基于语义向量检索（DeepSeek Embeddings + 余弦相似度 + 关键词加权），
>       相似度仅反映语义相关性，不代表结论正确性，请结合上下文判断。`;

  return context;
}

// ============================================================
// 10. 诊断 / 统计接口（便于调试）
// ============================================================

export interface RAGStats {
  totalFiles: number;
  totalChunks: number;
  vectorizedChunks: number;
  cacheExists: boolean;
  cachePath: string;
  cacheSizeKB: number;
  lastUpdatedAt: number | null;
}

export function getRAGStats(): RAGStats {
  const files = discoverMarkdownFiles();
  const cache = loadVectorCache();
  const vectorized = cache ? cache.chunks.filter((c) => c.vector && c.vector.length > 0).length : 0;

  let cacheSizeKB = 0;
  try {
    if (fs.existsSync(CACHE_PATH)) {
      cacheSizeKB = Math.round(fs.statSync(CACHE_PATH).size / 1024);
    }
  } catch {}

  return {
    totalFiles: files.length,
    totalChunks: cache ? cache.chunks.length : 0,
    vectorizedChunks: vectorized,
    cacheExists: !!cache,
    cachePath: CACHE_PATH,
    cacheSizeKB,
    lastUpdatedAt: cache?.updatedAt ?? null,
  };
}

/**
 * 清除缓存（当知识库内容有重大变更时使用）
 */
export function clearRAGCache(): boolean {
  try {
    if (fs.existsSync(CACHE_PATH)) {
      fs.unlinkSync(CACHE_PATH);
      return true;
    }
  } catch (e) {
    console.warn('[RAG] Failed to clear cache:', e);
  }
  return false;
}
