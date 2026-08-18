import fs from 'fs';
import path from 'path';
import matter from 'gray-matter';
import FlexSearch from 'flexsearch';

// ============================================================
// 搜索索引动态生成（无需静态文件）
// ============================================================
const ARTIFACTS_ROOT = path.join(
  process.env.HOME || '/Users/zhangjiangtao',
  '.workbuddy/artifacts'
);

interface SearchIndexItem {
  id: string;
  title: string;
  content: string;
  snippet: string;
  url: string;
}

interface SearchIndex {
  version: string;
  last_build: string;
  total_items: number;
  items: SearchIndexItem[];
}

// Flexsearch index instance (singleton)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let flexsearchIndex: any = null;
let searchIndexCache: SearchIndex | null = null;

/**
 * 扫描后端产物，生成搜索索引
 */
function buildSearchIndex(): SearchIndex {
  const items: SearchIndexItem[] = [];

  if (!fs.existsSync(ARTIFACTS_ROOT)) {
    console.warn('[search] Artifacts root not found');
    return { version: '2.0', last_build: new Date().toISOString(), total_items: 0, items: [] };
  }

  const categories = fs.readdirSync(ARTIFACTS_ROOT).filter(f => {
    const fp = path.join(ARTIFACTS_ROOT, f);
    return fs.statSync(fp).isDirectory() && !f.startsWith('.');
  });

  for (const category of categories) {
    const catDir = path.join(ARTIFACTS_ROOT, category);
    const indexFile = path.join(catDir, 'index.json');
    if (!fs.existsSync(indexFile)) continue;

    try {
      const catIndex = JSON.parse(fs.readFileSync(indexFile, 'utf-8'));
      const catArtifacts = catIndex.artifacts || [];

      for (const item of catArtifacts) {
        const artifactId = item.artifact_id || item.id || 'unknown';
        const filename = item.filename || `${artifactId}.md`;
        const filePath = path.join(catDir, filename);

        let title = artifactId;
        let content = '';
        let snippet = '';

        // 读取 .md 文件内容（gray-matter 解析失败时跳过内容读取）
        if (fs.existsSync(filePath)) {
          try {
            const fileContent = fs.readFileSync(filePath, 'utf-8');
            const parsed = matter(fileContent);
            title = parsed.data.title || artifactId;
            content = parsed.content || '';
            snippet = content.substring(0, 200).replace(/\n/g, ' ');
          } catch (e) {
            // gray-matter 解析失败时，使用 index.json 的 title
            console.warn(`[search] gray-matter failed, using index.json: ${filePath}`);
            title = item.title || artifactId;
            content = '';
            snippet = '';
          }
        }

        items.push({
          id: `${category}/${artifactId}`,
          title,
          content: content.substring(0, 2000), // 限制长度
          snippet,
          url: `/feed/${category}/${artifactId}`,
        });
      }
    } catch (e) {
      console.warn(`[search] Failed to process ${category}:`, e);
    }
  }

  return {
    version: '2.0',
    last_build: new Date().toISOString(),
    total_items: items.length,
    items,
  };
}

/**
 * Initialize Flexsearch index
 */
export async function initSearchIndex(): Promise<void> {
  if (flexsearchIndex) return; // Already initialized
  
  try {
    // 动态生成搜索索引
    searchIndexCache = buildSearchIndex();
    
    // Create Flexsearch document index
    const FlexSearch = (await import('flexsearch')).default;
    flexsearchIndex = new FlexSearch.Document({
      tokenize: 'forward',
      cache: true,
      document: {
        id: 'id',
        index: ['title', 'content', 'snippet'],
        store: ['title', 'url', 'snippet']
      }
    });
    
    // Add all documents to the index
    for (const item of searchIndexCache.items) {
      flexsearchIndex.add(item);
    }
    
    console.log(`✅ Flexsearch 索引已加载: ${searchIndexCache.total_items} 条记录`);
  } catch (error) {
    console.error('❌ 初始化搜索索引失败:', error);
  }
}

/**
 * Full-text search using Flexsearch
 */
export async function searchFullText(
  query: string,
  limit: number = 20
): Promise<string[]> {
  if (!flexsearchIndex || !query.trim()) return [];
  
  try {
    const results = await flexsearchIndex.searchAsync(query, {
      limit,
      enrich: true
    });
    
    // Collect unique IDs from all field results
    const ids = new Set<string>();
    for (const fieldResult of results as any[]) {
      if (fieldResult.result) {
        for (const item of fieldResult.result) {
          ids.add(String(item.id));
        }
      }
    }
    
    return Array.from(ids);
  } catch (error) {
    console.error('❌ 全文搜索失败:', error);
    return [];
  }
}

/**
 * Client-side search: filter artifacts by query string
 * Searches across title, tags, and type fields
 */
export function searchArtifacts(
  query: string,
  artifacts: any[],
  fullTextIds?: string[]
): any[] {
  if (!query.trim()) return artifacts;

  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((t: string) => t.length > 0);

  if (terms.length === 0) return artifacts;

  // First, filter by metadata (title, tags, etc.)
  let result = artifacts.filter((artifact: any) => {
    const searchable = [
      artifact.title,
      artifact.tags,
      artifact.type,
      artifact.department,
      artifact.chain_phase,
    ]
      .join(' ')
      .toLowerCase();

    return terms.every((term: string) => searchable.includes(term));
  });

  // If full-text IDs provided, also include those results
  if (fullTextIds && fullTextIds.length > 0) {
    const metadataIds = new Set(result.map((a: any) => a.id));
    const fullTextArtifacts = artifacts.filter((a: any) => 
      fullTextIds.includes(a.id) && !metadataIds.has(a.id)
    );
    result = [...result, ...fullTextArtifacts];
  }

  return result;
}

/**
 * Combined search: metadata + full-text
 */
export async function searchCombined(
  query: string,
  artifacts: any[],
  limit: number = 20
): Promise<any[]> {
  if (!query.trim()) return artifacts;
  
  // Get full-text matching IDs
  const fullTextIds = await searchFullText(query, limit);
  
  // Search metadata + include full-text results
  return searchArtifacts(query, artifacts, fullTextIds);
}

/**
 * Filter artifacts by department
 */
export function filterByDepartment(
  department: string,
  artifacts: any[]
): any[] {
  if (department === 'all') return artifacts;
  return artifacts.filter((a: any) => a.department === department);
}

/**
 * Filter artifacts by time range
 */
export function filterByTimeRange(
  range: string,
  artifacts: any[]
): any[] {
  if (range === 'all') return artifacts;

  const now = new Date();
  now.setHours(23, 59, 59, 999);

  return artifacts.filter((a: any) => {
    if (!a.date || a.date === 'unknown') return false;
    try {
      const date = new Date(a.date);
      if (isNaN(date.getTime())) return false;

      if (range === 'today') {
        const start = new Date(now);
        start.setHours(0, 0, 0, 0);
        return date >= start && date <= now;
      }
      if (range === 'week') {
        const start = new Date(now);
        start.setDate(start.getDate() - 7);
        start.setHours(0, 0, 0, 0);
        return date >= start && date <= now;
      }
      if (range === 'month') {
        const start = new Date(now);
        start.setMonth(start.getMonth() - 1);
        start.setHours(0, 0, 0, 0);
        return date >= start && date <= now;
      }
    } catch {
      return false;
    }
    return true;
  });
}

/**
 * Paginate artifacts
 */
export function paginate<T>(
  items: T[],
  page: number,
  pageSize: number
): { items: T[]; totalPages: number } {
  const totalPages = Math.ceil(items.length / pageSize);
  const safePage = Math.max(1, Math.min(page, totalPages));
  const start = (safePage - 1) * pageSize;
  const itemsPage = items.slice(start, start + pageSize);
  return { items: itemsPage, totalPages };
}
