/**
 * 客户端搜索模块
 * 只包含客户端可用的搜索/过滤函数
 * （FlexSearch全文搜索在服务端执行，通过API暴露）
 */
import type { CanonicalArtifactIndex } from './types';

/**
 * Client-side search: filter artifacts by query string
 * Searches across title, tags, and type fields
 */
export function searchArtifacts(
  query: string,
  artifacts: CanonicalArtifactIndex[],
  fullTextIds?: string[]
): CanonicalArtifactIndex[] {
  if (!query.trim()) return artifacts;

  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length > 0);

  if (terms.length === 0) return artifacts;

  // First, filter by metadata (title, tags, etc.)
  let result = artifacts.filter((artifact) => {
    const searchable = [
      artifact.title,
      artifact.tags.join(' '),
      artifact.type,
      artifact.department,
      artifact.chainPhase,
    ]
      .join(' ')
      .toLowerCase();

    return terms.every((term) => searchable.includes(term));
  });

  // If full-text IDs provided, also include those results
  if (fullTextIds && fullTextIds.length > 0) {
    const metadataIds = new Set(result.map((a) => a.id));
    const fullTextArtifacts = artifacts.filter((a) => 
      fullTextIds.includes(a.id) && !metadataIds.has(a.id)
    );
    result = [...result, ...fullTextArtifacts];
  }

  return result;
}

/**
 * Filter artifacts by department
 */
export function filterByDepartment(
  department: string,
  artifacts: CanonicalArtifactIndex[]
): CanonicalArtifactIndex[] {
  if (department === 'all') return artifacts;
  return artifacts.filter((a) => a.department === department);
}

/**
 * Filter artifacts by time range
 */
export function filterByTimeRange(
  range: string,
  artifacts: CanonicalArtifactIndex[]
): CanonicalArtifactIndex[] {
  if (range === 'all') return artifacts;

  const now = new Date();
  now.setHours(23, 59, 59, 999);

  return artifacts.filter((a) => {
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

// ============================================================
// 全文搜索 API（客户端通过 fetch 调用）
// ============================================================

/**
 * 客户端全文搜索状态（简化版：使用元数据搜索替代 FlexSearch）
 */
export async function initSearchIndex(): Promise<void> {
  // 不需要在客户端初始化 FlexSearch
  // 全文搜索通过 metadata 过滤实现
  return Promise.resolve();
}

/**
 * 客户端全文搜索（简化版：返回空数组）
 * 全文搜索功能暂时禁用，使用元数据搜索替代
 */
export async function searchFullText(
  query: string,
  limit: number = 20
): Promise<string[]> {
  // 暂时禁用 FlexSearch 全文搜索
  // 如果需要全文搜索，可以创建 API route 在服务端执行
  return [];
}
