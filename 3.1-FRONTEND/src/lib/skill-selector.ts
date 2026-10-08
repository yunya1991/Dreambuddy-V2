/**
 * SkillSelector — 意图→SKILL 选择器
 * ====================================
 * 接收意图识别结果 + 认知上下文，选择最匹配的 SKILL，输出执行计划。
 *
 * 设计原则（HC-1: SKILL 选择不使用 LLM）：
 *   1. 规则优先：trigger 关键词精确匹配 → category 过滤 → intent_type 路由
 *   2. 向量兜底：规则无命中时，TF-IDF + cosine similarity 语义匹配
 *   3. 零依赖：TF-IDF 纯内存计算，不引入外部向量数据库
 *   4. 可解释：match_reasons 记录命中的 triggers / 向量分数
 *
 * 性能目标（SPEC §3.2）：
 *   - 规则匹配 ≤ 50ms
 *   - 向量匹配 ≤ 100ms
 *
 * 位置: 3.1-FRONTEND/src/lib/skill-selector.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import type { CognitiveContext } from './cognitive-context-builder';

// ============================================================
// 1. 类型定义（对齐 SPEC §4.3）
// ============================================================

/** 意图识别结果（兼容 fallback-engine 的 IntentRecognitionResult） */
export interface IntentResult {
  type: string;               // 意图类型 (market_query / deep_analysis / ...)
  entities: Record<string, string>; // 提取的实体
  confidence: number;          // 意图识别置信度
  raw_text: string;            // 原始用户消息
}

/** 单个 SKILL 的选择结果 */
export interface SkillSelection {
  skill_id: string;
  match_score: number;       // 0~1，综合匹配分数
  match_reasons: string[];    // 选择理由（可解释性）
  confidence: number;        // 选择置信度
}

/** SKILL 执行计划（SPEC §4.3 SkillExecutionPlan） */
export interface SkillExecutionPlan {
  skill_ids: string[];             // 选中的 SKILL ID 列表
  order: string[];                 // 执行顺序
  params: Record<string, any>;     // 传递给 SKILL 的参数
  match_reasons: string[];         // 整体选择理由
  context: CognitiveContext;       // 认知上下文（注入执行）
  selections: SkillSelection[];    // 详细选择信息
  /** SIE-SPEC §3.2.1: 无匹配时返回 true，触发路径 B 模仿 */
  imitation_required: boolean;
}

/** registry.json 中的 SKILL 条目 */
interface RegistryEntry {
  name: string;
  description: string;
  category: string;
  triggers: string[];
  facets: {
    domain: string;
    task_type: string;
    potency: string;
    resource_cost: string;
    execution_mode: string;
  };
  confidence: number;
  status: string;
}

// ============================================================
// 2. 配置
// ============================================================

const SELECTOR_CONFIG = {
  registry_path: '1-ARCHITECTURE/skills/_registry/registry.json',
  vector_threshold: 0.30,       // SIE-SPEC §2.1: cosine ≥ 0.30 视为匹配（m-1 修复，统一阈值）
  max_candidates: 5,           // 返回最多 5 个候选
  min_rule_matches: 1,         // trigger 命中 ≥1 个即返回
  fallback_skill: 'simple_qa',  // 保留为最终降级（SIE-SPEC §3.1 m-4: 三层降级链末端）
};

/**
 * 意图类型 → SKILL category 粗筛映射
 * 用于第一步过滤，缩小候选集
 */
const INTENT_CATEGORY_MAP: Record<string, string[]> = {
  // 交易相关
  market_query: ['trading', 'trigger', 'orchestration', 'uncategorized'],
  execute_trade: ['trading', 'trigger', 'orchestration'],
  risk_alert_response: ['trading', 'trigger', 'orchestration'],
  // 分析相关
  deep_analysis: ['research', 'orchestration', 'trading', 'uncategorized'],
  scenario_sim: ['research', 'orchestration', 'trading'],
  strategy_verify: ['research', 'orchestration', 'uncategorized'],
  triple_chain: ['research', 'orchestration', 'trading', 'uncategorized'],
  // 通用
  simple_qa: [],  // 不过滤
  command: [],
  system_config: ['tooling', 'system-kernel', 'uncategorized'],
  credits_query: [],
  artifact_query: ['research', 'uncategorized'],
  // 开发
  developer: ['tooling', 'meta', 'orchestration', 'uncategorized'],
  // 其他
  need_clarification: [],
  clarification_result: [],
};

// ============================================================
// 3. TF-IDF 向量索引
// ============================================================

/**
 * 简易 TF-IDF 实现（纯内存，零依赖）
 * 支持 中英文混合文本
 * - 中文：bigram (2-char sliding window)
 * - 英文：word-level (split by non-alphanumeric)
 */
class TFIDFIndex {
  private skillIds: string[] = [];
  private documents: Map<string, string[]> = new Map(); // skill_id → tokens
  private idf: Map<string, number> = new Map();           // token → IDF value
  private docVectors: Map<string, Map<string, number>> = new Map(); // skill_id → tf-idf vector

  /** 分词：中文 bigram + 英文 word */
  tokenize(text: string): string[] {
    const tokens: string[] = [];
    const lower = text.toLowerCase();

    // 英文词（含数字）
    const englishWords = lower.match(/[a-z0-9_]{2,}/g) || [];
    tokens.push(...englishWords);

    // 中文 bigram
    const chineseChars = text.match(/[\u4e00-\u9fff]/g) || [];
    for (let i = 0; i < chineseChars.length - 1; i++) {
      tokens.push(chineseChars[i] + chineseChars[i + 1]);
    }

    // 单个中文字也作为 token（覆盖短文本）
    tokens.push(...chineseChars);

    return tokens;
  }

  /** 构建 TF-IDF 索引 */
  build(skills: RegistryEntry[]): void {
    this.skillIds = [];
    this.documents = new Map();
    this.idf = new Map();
    this.docVectors = new Map();

    const docCount = skills.length;
    const docFreq: Map<string, number> = new Map(); // token → 出现在多少文档中

    // 1. 分词 + 统计 DF
    for (const skill of skills) {
      const text = `${skill.name} ${skill.description} ${(skill.triggers || []).join(' ')}`;
      const tokens = this.tokenize(text);
      this.skillIds.push(skill.name);
      this.documents.set(skill.name, tokens);

      const uniqueTokens = Array.from(new Set(tokens));
      for (const token of uniqueTokens) {
        docFreq.set(token, (docFreq.get(token) || 0) + 1);
      }
    }

    // 2. 计算 IDF: log(N / df)
    for (const [token, df] of Array.from(docFreq)) {
      this.idf.set(token, Math.log((docCount + 1) / (df + 1)) + 1);
    }

    // 3. 构建 TF-IDF 向量
    for (const skillId of this.skillIds) {
      const tokens = this.documents.get(skillId) || [];
      const tokenFreq: Map<string, number> = new Map();
      for (const token of tokens) {
        tokenFreq.set(token, (tokenFreq.get(token) || 0) + 1);
      }

      const vector: Map<string, number> = new Map();
      const maxFreq = Math.max(...Array.from(tokenFreq.values()), 1);
      for (const [token, freq] of Array.from(tokenFreq)) {
        const tf = freq / maxFreq;
        const idf = this.idf.get(token) || 0;
        vector.set(token, tf * idf);
      }
      this.docVectors.set(skillId, vector);
    }
  }

  /** 计算 query 与某个 SKILL 的 cosine 相似度 */
  cosineSimilarity(query: string, skillId: string): number {
    const queryTokens = this.tokenize(query);
    if (queryTokens.length === 0) return 0;

    // query TF
    const queryFreq: Map<string, number> = new Map();
    for (const token of queryTokens) {
      queryFreq.set(token, (queryFreq.get(token) || 0) + 1);
    }
    const maxFreq = Math.max(...Array.from(queryFreq.values()), 1);

    // query TF-IDF vector
    const queryVector: Map<string, number> = new Map();
    for (const [token, freq] of Array.from(queryFreq)) {
      const tf = freq / maxFreq;
      const idf = this.idf.get(token) || 0;
      queryVector.set(token, tf * idf);
    }

    // doc vector
    const docVector = this.docVectors.get(skillId);
    if (!docVector) return 0;

    // dot product + magnitudes
    let dotProduct = 0;
    let queryMag = 0;
    let docMag = 0;

    for (const [token, weight] of Array.from(queryVector)) {
      queryMag += weight * weight;
      const docWeight = docVector.get(token);
      if (docWeight !== undefined) {
        dotProduct += weight * docWeight;
      }
    }
    for (const weight of Array.from(docVector.values())) {
      docMag += weight * weight;
    }

    if (queryMag === 0 || docMag === 0) return 0;
    return dotProduct / (Math.sqrt(queryMag) * Math.sqrt(docMag));
  }

  /** 对所有 SKILL 做 cosine 排序，返回 top-k */
  search(query: string, topK: number, candidateIds?: string[]): Array<{ skill_id: string; score: number }> {
    const searchIds = candidateIds && candidateIds.length > 0
      ? candidateIds
      : this.skillIds;

    const results: Array<{ skill_id: string; score: number }> = [];
    for (const skillId of searchIds) {
      const score = this.cosineSimilarity(query, skillId);
      results.push({ skill_id: skillId, score });
    }

    results.sort((a, b) => b.score - a.score);
    return results.slice(0, topK);
  }
}

// ============================================================
// 4. SkillSelector 主类
// ============================================================

export class SkillSelector {
  private skills: RegistryEntry[] = [];
  private skillMap: Map<string, RegistryEntry> = new Map();
  private tfidf: TFIDFIndex;
  private loaded = false;

  constructor() {
    this.tfidf = new TFIDFIndex();
  }

  /** 懒加载 registry.json */
  private load(): void {
    if (this.loaded) return;

    // 多路径查找 registry.json（兼容从项目根目录或 3.1-FRONTEND 运行）
    const candidatePaths = [
      path.resolve(process.cwd(), SELECTOR_CONFIG.registry_path),
      path.resolve(process.cwd(), '..', SELECTOR_CONFIG.registry_path),
      path.resolve(__dirname, '..', '..', '..', SELECTOR_CONFIG.registry_path),
    ];

    let registryPath: string | null = null;
    for (const p of candidatePaths) {
      if (fs.existsSync(p)) {
        registryPath = p;
        break;
      }
    }

    if (!registryPath) {
      console.error('[SkillSelector] registry.json not found in candidates:', candidatePaths);
      this.loaded = true;
      return;
    }

    try {
      const raw = fs.readFileSync(registryPath, 'utf-8');
      const data = JSON.parse(raw);
      this.skills = (data.skills || []).filter(
        (s: RegistryEntry) => s.status === 'active',
      );
      for (const s of this.skills) {
        this.skillMap.set(s.name, s);
      }
      this.tfidf.build(this.skills);
      this.loaded = true;
    } catch (err) {
      console.error('[SkillSelector] Failed to load registry:', err);
      this.loaded = true;
    }
  }

  /**
   * 选择 SKILL（SPEC §3.2 执行流程）
   *
   * @param intent 意图识别结果
   * @param context 认知上下文
   * @returns SkillExecutionPlan
   */
  select(intent: IntentResult, context: CognitiveContext): SkillExecutionPlan {
    this.load();
    const startTime = Date.now();

    // 意图置信度 < 0.7 → 返回 top-3 候选 + 澄清请求
    const lowConfidence = intent.confidence < 0.7;
    if (lowConfidence) {
      // 先尝试规则匹配（trigger 可能仍然命中）
      const ruleCandidates = this.matchByRules(intent, this.coarseFilter(intent.type));
      if (ruleCandidates.length > 0) {
        return this.buildPlan(ruleCandidates.slice(0, 3), context, [
          `intent_confidence=${intent.confidence.toFixed(2)} < 0.7, 返回 top-3 候选请求澄清`,
        ]);
      }
      // 规则无命中 → 向量匹配 top-3
      const vectorCandidates = this.matchByVector(intent.raw_text, 3);
      if (vectorCandidates.length > 0) {
        return this.buildPlan(vectorCandidates, context, [
          `intent_confidence=${intent.confidence.toFixed(2)} < 0.7, 返回 top-3 候选请求澄清`,
        ]);
      }
      // 向量也无命中 → SIE-SPEC §3.2.1: 返回 imitation_required 信号（不再 fallback simple_qa）
      return this.buildImitationPlan(context, [
        `intent_confidence=${intent.confidence.toFixed(2)} < 0.7, 无规则/向量命中`,
        'imitation_required: 触发路径 B 模仿',
      ]);
    }

    // Step 1: 粗筛 — 按 category 缩小候选集
    const candidateIds = this.coarseFilter(intent.type);

    // Step 2: 规则匹配 — trigger 关键词
    const ruleMatches = this.matchByRules(intent, candidateIds);

    let selections: SkillSelection[];
    let reasons: string[];

    if (ruleMatches.length >= SELECTOR_CONFIG.min_rule_matches) {
      // 规则命中 → 按命中数排序
      selections = ruleMatches.slice(0, SELECTOR_CONFIG.max_candidates);
      reasons = [`rule_match: ${ruleMatches.length} SKILLs matched triggers`];
    } else {
      // Step 3: 向量兜底 — TF-IDF cosine
      const vectorMatches = this.matchByVector(intent.raw_text, SELECTOR_CONFIG.max_candidates, candidateIds);

      if (vectorMatches.length > 0) {
        selections = vectorMatches;
        reasons = [`vector_match: top-${vectorMatches.length} by TF-IDF cosine`];
      } else {
        // SIE-SPEC §3.2.1: 完全无匹配 → 返回 imitation_required 信号（不再 fallback simple_qa）
        return this.buildImitationPlan(context, [
          'no rule or vector match',
          'imitation_required: 触发路径 B 模仿',
        ]);
      }
    }

    // 认知上下文加权（经验匹配度 > 知识相关性）
    selections = this.applyContextBoost(selections, context);

    const elapsed = Date.now() - startTime;
    reasons.push(`latency=${elapsed}ms`);

    return this.buildPlan(selections, context, reasons);
  }

  // ============================================================
  // 5. 内部方法
  // ============================================================

  /**
   * Step 1: 粗筛 — 按 intent_type → category 映射过滤
   * 如果映射为空或无匹配，返回全部（不阻塞）
   */
  private coarseFilter(intentType: string): string[] | undefined {
    const categories = INTENT_CATEGORY_MAP[intentType];
    if (!categories || categories.length === 0) {
      return undefined; // 不过滤
    }

    const ids = this.skills
      .filter(s => categories.includes(s.category))
      .map(s => s.name);

    // 如果粗筛后候选 < 3，说明 category 映射不够，返回全部
    return ids.length >= 3 ? ids : undefined;
  }

  /**
   * Step 2: 规则匹配 — trigger 关键词
   * 检查 intent text 和 entities 中是否包含 SKILL 的 trigger 关键词
   */
  private matchByRules(
    intent: IntentResult,
    candidateIds?: string[],
  ): SkillSelection[] {
    // 去空格归一化，让 "TDD 开发" 匹配 "TDD开发"
    const normalize = (s: string) => s.toLowerCase().replace(/\s+/g, '');
    const searchText = normalize([
      intent.raw_text,
      ...Object.values(intent.entities),
    ].join(' '));

    const searchPool = candidateIds
      ? this.skills.filter(s => candidateIds.includes(s.name))
      : this.skills;

    const matches: SkillSelection[] = [];

    for (const skill of searchPool) {
      if (!skill.triggers || skill.triggers.length === 0) continue;

      const matchedTriggers: string[] = [];
      for (const trigger of skill.triggers) {
        // 清理 trigger 中的格式噪音（引号、cron 表达式等）
        const cleanTrigger = trigger.replace(/^["'`]|["'`]$/g, '').trim();
        if (!cleanTrigger || cleanTrigger.startsWith('{')) continue;

        if (searchText.includes(normalize(cleanTrigger))) {
          matchedTriggers.push(cleanTrigger);
        }
      }

      if (matchedTriggers.length > 0) {
        const score = Math.min(matchedTriggers.length / 3, 1); // 3个trigger命中=满分
        matches.push({
          skill_id: skill.name,
          match_score: score,
          match_reasons: [`trigger_hit: ${matchedTriggers.join(', ')}`],
          confidence: 0.6 + score * 0.3, // 0.6~0.9
        });
      }
    }

    // 排序：trigger 命中数 > autonomy_boundary 优先级
    matches.sort((a, b) => b.match_score - a.match_score);
    return matches;
  }

  /**
   * Step 3: 向量兜底 — TF-IDF cosine similarity
   * 阈值 ≥ 0.3 视为匹配
   */
  private matchByVector(
    query: string,
    topK: number,
    candidateIds?: string[],
  ): SkillSelection[] {
    const results = this.tfidf.search(query, topK, candidateIds);

    return results
      .filter(r => r.score >= SELECTOR_CONFIG.vector_threshold)
      .map(r => ({
        skill_id: r.skill_id,
        match_score: r.score,
        match_reasons: [`vector_cosine: ${r.score.toFixed(3)}`],
        confidence: r.score * 0.7, // 向量匹配置信度较低
      }));
  }

  /**
   * 认知上下文加权
   * 如果 context 中的经验/知识提到某个 SKILL，提升其分数
   */
  private applyContextBoost(
    selections: SkillSelection[],
    context: CognitiveContext,
  ): SkillSelection[] {
    if (!context) return selections;

    // 从认知上下文中提取相关 SKILL 名称
    const contextSkillNames = new Set<string>();
    for (const exp of context.experiences || []) {
      const content = exp.content || '';
      // 在经验内容中查找已选 SKILL 名称的提及
      for (const sel of selections) {
        if (content.includes(sel.skill_id)) {
          contextSkillNames.add(sel.skill_id);
        }
      }
    }

    // 从 references 中提取
    for (const ref of context.references || []) {
      if (ref.category === 'skill' && ref.title) {
        contextSkillNames.add(ref.title);
      }
    }

    // 加权
    for (const sel of selections) {
      if (contextSkillNames.has(sel.skill_id)) {
        sel.match_score = Math.min(sel.match_score * 1.15, 1);
        sel.confidence = Math.min(sel.confidence * 1.1, 1);
        sel.match_reasons.push('context_boost: cognitive context mentions this SKILL');
      }
    }

    // 重新排序
    selections.sort((a, b) => b.match_score - a.match_score);
    return selections;
  }

  /** 构建 SkillExecutionPlan */
  private buildPlan(
    selections: SkillSelection[],
    context: CognitiveContext,
    baseReasons: string[],
  ): SkillExecutionPlan {
    const skillIds = selections.map(s => s.skill_id);
    const allReasons = [
      ...baseReasons,
      ...selections.flatMap(s => s.match_reasons),
    ];

    return {
      skill_ids: skillIds,
      order: skillIds, // 执行顺序 = 排序后的顺序
      params: {},      // 参数由 DSH 执行引擎填充
      match_reasons: allReasons,
      context,
      selections,
      imitation_required: false, // SIE-SPEC §3.2.1: 命中路径 A，不触发模仿
    };
  }

  /**
   * SIE-SPEC §3.2.1: 构建 imitation_required 计划
   * 无匹配时返回，触发路径 B 模仿执行
   */
  private buildImitationPlan(
    context: CognitiveContext,
    reasons: string[],
  ): SkillExecutionPlan {
    const elapsed = Date.now() - 1; // 近似
    reasons.push(`latency=${elapsed}ms`);
    return {
      skill_ids: [],        // 空：无 SKILL 命中
      order: [],
      params: {},
      match_reasons: reasons,
      context,
      selections: [],
      imitation_required: true,
    };
  }

  /** 获取 SKILL 详情 */
  getSkill(skillId: string): RegistryEntry | undefined {
    this.load();
    return this.skillMap.get(skillId);
  }

  /** 获取所有 SKILL 数量 */
  getSkillCount(): number {
    this.load();
    return this.skills.length;
  }

  /** 重新加载 registry（热更新） */
  reload(): void {
    this.loaded = false;
    this.skills = [];
    this.skillMap = new Map();
    this.load();
  }
}

// ============================================================
// 6. 单例导出
// ============================================================

let _instance: SkillSelector | null = null;

export function getSkillSelector(): SkillSelector {
  if (!_instance) _instance = new SkillSelector();
  return _instance;
}

export default SkillSelector;
