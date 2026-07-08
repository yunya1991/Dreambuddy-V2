/**
 * ============================================================
 *  WorkBuddy OS 模块注册表加载器 (TS 侧)
 * ============================================================
 *
 * 位置: 6-图结构上下文压缩/planner/module-registry.ts
 *
 * 功能:
 * 1. 从 JSON 文件加载模块注册表（双端唯一真相源）
 * 2. 内存缓存 + 索引加速
 * 3. 热更新（文件监听，Node.js 环境）
 * 4. 统一查询接口（按ID/链/分类/标签/阶段等）
 *
 * 设计原则:
 * - 单一真相源: 1-ARCHITECTURE/registry/module_registry.json
 * - 只读加载: 注册表是配置，运行时不修改
 * - 索引加速: 按多种维度建立索引，查询O(1)
 * - 执行器分离: 只加载元数据，执行逻辑保持在现有 SkillsRegistry
 */

import * as fs from 'fs';
import * as path from 'path';

// ============================================================
// 类型定义
// ============================================================

export interface Lifecycle {
  status: 'active' | 'inactive' | 'deprecated' | 'experimental';
  phase: 'prototype' | 'beta' | 'production' | 'eol';
  deprecated: boolean;
  replaced_by: string | null;
}

export interface Adapter {
  type: 'skill' | 'api' | 'local' | 'external' | 'mcp';
  execution_engine: 'python' | 'typescript' | 'both' | 'external';
  skill_md?: string;
  base_url?: string;
  endpoint?: string;
  ts_path?: string;
  py_path?: string;
  py_module?: string;
  skill_path?: string;
  factory_function?: string;
}

export interface Fallback {
  enabled: boolean;
  fallback_module?: string;
  fallback_type?: string;
  fallback_reason?: string;
}

export interface ModuleInfo {
  id: string;
  name: string;
  description: string;
  version: string;
  chain: 'A' | 'C' | 'F' | 'G' | 'T';
  category: string;
  tags: string[];
  lifecycle: Lifecycle;
  security_level: 'R0' | 'R1' | 'R2' | 'R3';
  estimated_tokens: number;
  estimated_latency_ms: number;
  confidence_range: [number, number];
  applicable_stages: Array<'research' | 'analysis' | 'design' | 'validate' | 'execute'>;
  applicable_intents: string[];
  market_conditions: string[];
  historical_accuracy: number;
  historical_calls: number;
  dependencies: string[];
  adapter: Adapter;
  fallback: Fallback;
  domain: string;
  category_name: string;
}

export interface ModuleRegistryRaw {
  version: string;
  updated_at: string;
  schema_version: string;
  total_modules: number;
  domains: Record<string, {
    name: string;
    description: string;
    color: string;
    categories: Record<string, {
      name: string;
      description: string;
      modules: Record<string, any>;
    }>;
  }>;
}

export interface ModuleQueryParams {
  chain?: ModuleInfo['chain'] | ModuleInfo['chain'][];
  category?: string | string[];
  domain?: string | string[];
  stage?: ModuleInfo['applicable_stages'][number] | ModuleInfo['applicable_stages'][number][];
  tag?: string | string[];
  security_level?: ModuleInfo['security_level'];
  min_accuracy?: number;
  max_tokens?: number;
  intent?: string;
  market_condition?: string;
}

// ============================================================
// 注册表路径
// ============================================================

const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
const REGISTRY_JSON_PATH = path.join(
  PROJECT_ROOT,
  '1-ARCHITECTURE',
  'registry',
  'module_registry.json'
);

// ============================================================
// 模块注册表加载器
// ============================================================

export class ModuleRegistry {
  private modules: Map<string, ModuleInfo> = new Map();
  private rawData: ModuleRegistryRaw | null = null;
  private lastLoadTime: number = 0;
  private lastFileMtime: number = 0;

  private byChain: Map<string, Set<string>> = new Map();
  private byCategory: Map<string, Set<string>> = new Map();
  private byDomain: Map<string, Set<string>> = new Map();
  private byStage: Map<string, Set<string>> = new Map();
  private byTag: Map<string, Set<string>> = new Map();

  private watchInterval: ReturnType<typeof setInterval> | null = null;
  private registryPath: string;

  constructor(registryPath?: string) {
    this.registryPath = registryPath || REGISTRY_JSON_PATH;
    this.load();
  }

  // ============================================================
  // 加载与刷新
  // ============================================================

  load(): boolean {
    try {
      if (!fs.existsSync(this.registryPath)) {
        console.warn(`[ModuleRegistry] 注册表文件不存在: ${this.registryPath}`);
        return false;
      }

      const stat = fs.statSync(this.registryPath);
      const fileMtime = stat.mtimeMs;
      if (fileMtime === this.lastFileMtime && this.modules.size > 0) {
        return true;
      }

      const raw = fs.readFileSync(this.registryPath, 'utf-8');
      const data: ModuleRegistryRaw = JSON.parse(raw);

      if (!data || !data.domains) {
        console.warn('[ModuleRegistry] 注册表格式错误');
        return false;
      }

      const modules = new Map<string, ModuleInfo>();
      const domains = data.domains;

      for (const [domainKey, domainData] of Object.entries(domains)) {
        const categories = domainData.categories || {};
        for (const [catKey, catData] of Object.entries(categories)) {
          const modMap = catData.modules || {};
          for (const [modKey, modData] of Object.entries(modMap)) {
            const info: ModuleInfo = {
              ...modData,
              domain: domainKey,
              category_name: catKey,
            } as ModuleInfo;
            modules.set(info.id, info);
          }
        }
      }

      this.rawData = data;
      this.modules = modules;
      this.lastLoadTime = Date.now();
      this.lastFileMtime = fileMtime;
      this.buildIndexes();

      console.log(`[ModuleRegistry] 加载成功，共 ${modules.size} 个模块`);
      return true;
    } catch (e) {
      console.error('[ModuleRegistry] 加载失败:', e);
      return false;
    }
  }

  private buildIndexes(): void {
    this.byChain.clear();
    this.byCategory.clear();
    this.byDomain.clear();
    this.byStage.clear();
    this.byTag.clear();

    for (const [id, mod] of this.modules) {
      if (!this.byChain.has(mod.chain)) {
        this.byChain.set(mod.chain, new Set());
      }
      this.byChain.get(mod.chain)!.add(id);

      if (!this.byCategory.has(mod.category)) {
        this.byCategory.set(mod.category, new Set());
      }
      this.byCategory.get(mod.category)!.add(id);

      if (!this.byDomain.has(mod.domain)) {
        this.byDomain.set(mod.domain, new Set());
      }
      this.byDomain.get(mod.domain)!.add(id);

      for (const stage of mod.applicable_stages) {
        if (!this.byStage.has(stage)) {
          this.byStage.set(stage, new Set());
        }
        this.byStage.get(stage)!.add(id);
      }

      for (const tag of mod.tags) {
        if (!this.byTag.has(tag)) {
          this.byTag.set(tag, new Set());
        }
        this.byTag.get(tag)!.add(id);
      }
    }
  }

  reload(): boolean {
    return this.load();
  }

  checkForUpdates(): boolean {
    try {
      if (!fs.existsSync(this.registryPath)) {
        return false;
      }
      const stat = fs.statSync(this.registryPath);
      if (stat.mtimeMs > this.lastFileMtime) {
        console.log('[ModuleRegistry] 检测到文件更新，重新加载...');
        return this.load();
      }
      return false;
    } catch {
      return false;
    }
  }

  startWatching(intervalMs: number = 5000): void {
    if (this.watchInterval) return;

    this.watchInterval = setInterval(() => {
      this.checkForUpdates();
    }, intervalMs);

    console.log(`[ModuleRegistry] 文件监听已启动，间隔 ${intervalMs}ms`);
  }

  stopWatching(): void {
    if (this.watchInterval) {
      clearInterval(this.watchInterval);
      this.watchInterval = null;
    }
  }

  // ============================================================
  // 查询接口
  // ============================================================

  get(moduleId: string): ModuleInfo | undefined {
    return this.modules.get(moduleId);
  }

  has(moduleId: string): boolean {
    return this.modules.has(moduleId);
  }

  getAll(): ModuleInfo[] {
    return Array.from(this.modules.values());
  }

  count(): number {
    return this.modules.size;
  }

  query(params: ModuleQueryParams): ModuleInfo[] {
    let candidates = new Set(this.modules.keys());

    if (params.chain) {
      const chains = Array.isArray(params.chain) ? params.chain : [params.chain];
      const chainSet = new Set<string>();
      for (const c of chains) {
        const s = this.byChain.get(c);
        if (s) s.forEach(id => chainSet.add(id));
      }
      if (chainSet.size > 0) {
        candidates = new Set([...candidates].filter(x => chainSet.has(x)));
      }
    }

    if (params.category) {
      const cats = Array.isArray(params.category) ? params.category : [params.category];
      const catSet = new Set<string>();
      for (const c of cats) {
        const s = this.byCategory.get(c);
        if (s) s.forEach(id => catSet.add(id));
      }
      if (catSet.size > 0) {
        candidates = new Set([...candidates].filter(x => catSet.has(x)));
      }
    }

    if (params.domain) {
      const domains = Array.isArray(params.domain) ? params.domain : [params.domain];
      const domainSet = new Set<string>();
      for (const d of domains) {
        const s = this.byDomain.get(d);
        if (s) s.forEach(id => domainSet.add(id));
      }
      if (domainSet.size > 0) {
        candidates = new Set([...candidates].filter(x => domainSet.has(x)));
      }
    }

    if (params.stage) {
      const stages = Array.isArray(params.stage) ? params.stage : [params.stage];
      const stageSet = new Set<string>();
      for (const st of stages) {
        const s = this.byStage.get(st);
        if (s) s.forEach(id => stageSet.add(id));
      }
      if (stageSet.size > 0) {
        candidates = new Set([...candidates].filter(x => stageSet.has(x)));
      }
    }

    if (params.tag) {
      const tags = Array.isArray(params.tag) ? params.tag : [params.tag];
      const tagSet = new Set<string>();
      for (const t of tags) {
        const s = this.byTag.get(t);
        if (s) s.forEach(id => tagSet.add(id));
      }
      if (tagSet.size > 0) {
        candidates = new Set([...candidates].filter(x => tagSet.has(x)));
      }
    }

    const results: ModuleInfo[] = [];
    for (const id of candidates) {
      const mod = this.modules.get(id)!;

      if (params.security_level && mod.security_level !== params.security_level) {
        continue;
      }

      if (params.min_accuracy !== undefined && mod.historical_accuracy < params.min_accuracy) {
        continue;
      }

      if (params.max_tokens !== undefined && mod.estimated_tokens > params.max_tokens) {
        continue;
      }

      if (params.intent && !mod.applicable_intents.includes(params.intent)) {
        continue;
      }

      if (params.market_condition && !mod.market_conditions.includes(params.market_condition)) {
        continue;
      }

      results.push(mod);
    }

    return results;
  }

  getByChain(chain: ModuleInfo['chain']): ModuleInfo[] {
    return this.query({ chain });
  }

  getByDomain(domain: string): ModuleInfo[] {
    return this.query({ domain });
  }

  getDependencies(moduleId: string): ModuleInfo[] {
    const mod = this.get(moduleId);
    if (!mod) return [];
    return mod.dependencies
      .map(id => this.get(id))
      .filter((m): m is ModuleInfo => m !== undefined);
  }

  getFallback(moduleId: string): ModuleInfo | undefined {
    const mod = this.get(moduleId);
    if (!mod || !mod.fallback?.enabled) return undefined;
    const fallbackId = mod.fallback.fallback_module;
    if (!fallbackId) return undefined;
    return this.get(fallbackId);
  }

  getRaw(): ModuleRegistryRaw | null {
    return this.rawData;
  }

  getDomains(): string[] {
    return Array.from(this.byDomain.keys());
  }

  getChains(): string[] {
    return Array.from(this.byChain.keys());
  }

  getCategories(): string[] {
    return Array.from(this.byCategory.keys());
  }

  getStats() {
    return {
      total: this.modules.size,
      byChain: Object.fromEntries(
        Array.from(this.byChain.entries()).map(([k, v]) => [k, v.size])
      ),
      byDomain: Object.fromEntries(
        Array.from(this.byDomain.entries()).map(([k, v]) => [k, v.size])
      ),
      byCategory: Object.fromEntries(
        Array.from(this.byCategory.entries()).map(([k, v]) => [k, v.size])
      ),
      lastLoad: this.lastLoadTime,
    };
  }

  isActive(moduleId: string): boolean {
    const mod = this.get(moduleId);
    if (!mod) return false;
    return mod.lifecycle?.status === 'active' && !mod.lifecycle?.deprecated;
  }

  getRegistryPath(): string {
    return this.registryPath;
  }
}

// ============================================================
// 单例
// ============================================================

let globalRegistry: ModuleRegistry | null = null;

export function getModuleRegistry(): ModuleRegistry {
  if (!globalRegistry) {
    globalRegistry = new ModuleRegistry();
  }
  return globalRegistry;
}

export function reloadModuleRegistry(): boolean {
  return getModuleRegistry().reload();
}
