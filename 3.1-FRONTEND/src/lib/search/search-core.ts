/**
 * search-core.ts — 全局搜索核心逻辑
 * ====================================
 * 前端搜索优化方案 v1.0 阶段一（P0）
 * 职责：
 *   1. 统一搜索条目结构（报告/策略/记忆/文档四大模块）
 *   2. minisearch 内存倒排索引构建与增量更新
 *   3. 模糊搜索（大小写容错、部分匹配）
 *   4. 命中高亮片段生成
 *   5. 最近搜索记录（localStorage）
 * 权限：索引与过滤均在前端会话内，API 层统一走 NextAuth 会话过滤（方案 §3.3）
 */

import MiniSearch from "minisearch";

/** 搜索条目来源模块 */
export type SearchModule = "report" | "strategy" | "memory" | "doc";

/** 统一搜索条目（四大模块归一化结构） */
export interface SearchItem {
  id: string;
  moduleId: string;
  module: SearchModule;
  title: string;
  subtitle?: string;
  keywords?: string;
  href: string;
}

/** 搜索结果条目（含高亮信息） */
export interface SearchResultItem extends SearchItem {
  score: number;
  highlight: string;
}

/** 索引字段配置 */
const INDEX_FIELDS = ["title", "subtitle", "keywords"];

function cjkTokenize(text: string): string[] {
  const tokens: string[] = [];
  const latin = text.toLowerCase().match(/[a-z0-9]+/g) || [];
  tokens.push(...latin);
  const cjk = text.match(/[\u4e00-\u9fff]+/g) || [];
  for (const seg of cjk) {
    for (let i = 0; i < seg.length; i++) {
      tokens.push(seg[i]);
      if (i + 1 < seg.length) tokens.push(seg.slice(i, i + 2));
    }
  }
  return tokens;
}

class SearchIndex {
  private mini: MiniSearch<SearchItem>;
  private itemsById: Map<string, SearchItem> = new Map();

  constructor() {
    this.mini = new MiniSearch<SearchItem>({
      fields: INDEX_FIELDS,
      storeFields: ["id", "moduleId", "module", "title", "subtitle", "keywords", "href"],
      tokenize: cjkTokenize,
      processTerm: (term: string) => (term.length > 0 ? term.toLowerCase() : null),

      searchOptions: {
        prefix: true,
        fuzzy: 0.2,
        boost: { title: 3, subtitle: 1, keywords: 2 },
      },
    });
  }

  /** 全量替换索引（清空后重建） */
  replaceAll(items: SearchItem[]): void {
    this.mini.removeAll();
    this.itemsById.clear();
    this.add(items);
  }

  /** 增量添加/更新（同 id 覆盖） */
  add(items: SearchItem[]): void {
    const fresh = items.filter((it) => {
      if (this.itemsById.has(it.id)) {
        this.mini.discard(it.id);
      }
      this.itemsById.set(it.id, it);
      return true;
    });
    if (fresh.length > 0) {
      this.mini.addAll(fresh);
    }
  }

  /** 按 id 移除条目 */
  remove(ids: string[]): void {
    for (const id of ids) {
      if (this.itemsById.has(id)) {
        this.mini.discard(id);
        this.itemsById.delete(id);
      }
    }
  }

  /** 当前索引条目数 */
  get size(): number {
    return this.itemsById.size;
  }

  /**
   * 搜索：返回按相关性排序的结果（含高亮片段）
   * @param query 查询词（支持中英文、部分输入）
   * @param limit 返回条数上限（默认 20）
   * @param moduleFilter 按模块过滤（分面导航）
   */
  search(query: string, limit = 20, moduleFilter?: SearchModule): SearchResultItem[] {
    const trimmed = query.trim();
    if (!trimmed) return [];
    const raw = this.mini.search(trimmed).slice(0, limit * 3);
    const seen = new Set<string>();
    const results: SearchResultItem[] = [];
    for (const r of raw) {
      const item = this.itemsById.get(r.id as string);
      if (!item) continue;
      if (moduleFilter && item.module !== moduleFilter) continue;
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      results.push({
        ...item,
        score: r.score,
        highlight: buildHighlight(item, r.terms),
      });
      if (results.length >= limit) break;
    }
    return results;
  }
}

/**
 * buildHighlight — 生成命中高亮片段
 * 对 title/subtitle 中命中的词以 mark 标签包裹；未命中时返回原 title。
 */
export function buildHighlight(item: SearchItem, terms: string[]): string {
  const source = item.title || item.subtitle || "";
  if (!source || terms.length === 0) return escapeHtml(source);
  const escapedTerms = terms
    .filter((t) => t && t.length > 0)
    .sort((a, b) => b.length - a.length);
  let html = escapeHtml(source);
  for (const term of escapedTerms) {
    const safe = escapeHtml(term).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    html = html.replace(new RegExp("(" + safe + ")", "gi"), "<mark>$1</mark>");
  }
  return html;
}

/** HTML 转义（防注入） */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 模块级单例（进程内共享同一索引） */
let instance: SearchIndex | null = null;

export function getSearchIndex(): SearchIndex {
  if (!instance) {
    instance = new SearchIndex();
  }
  return instance;
}

// ---------- 最近搜索记录（localStorage，方案 §3.2 阶段一） ----------

const RECENT_KEY = "global-search-recent";
const RECENT_MAX = 8;

export function getRecentSearches(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const list = raw ? (JSON.parse(raw) as string[]) : [];
    return Array.isArray(list) ? list.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

export function addRecentSearch(query: string): void {
  if (typeof window === "undefined") return;
  const trimmed = query.trim();
  if (!trimmed) return;
  const list = getRecentSearches().filter((q) => q !== trimmed);
  list.unshift(trimmed);
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch {
    /* localStorage 不可用时静默降级 */
  }
}

export function clearRecentSearches(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(RECENT_KEY);
  } catch {
    /* 静默降级 */
  }
}
