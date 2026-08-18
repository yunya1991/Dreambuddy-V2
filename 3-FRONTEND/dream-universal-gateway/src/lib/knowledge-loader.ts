/**
 * 知识库加载器（升级为 RAG 版本）
 * ==========================================
 *
 * 变更说明:
 *   之前版本: 关键词 + 正则匹配，人工定义 KEYWORD_GROUPS
 *   当前版本: 真正的 RAG（向量语义检索）
 *           → 文档切片 + DeepSeek Embeddings + 余弦相似度 + 关键词加权
 *
 * 启用状态: 默认启用（无条件），知识库 RAG 始终参与上下文构建
 *           如需禁用可通过环境变量控制（见 knowledge-rag.ts）
 *
 * 模块依赖: src/lib/knowledge-rag.ts（核心实现）
 *
 * 本文件仅提供简化 API（供 route.ts 调用），核心逻辑见 knowledge-rag.ts
 */

import {
  buildRAGContext,
  getRAGStats,
  clearRAGCache,
  retrieveRelevantChunks,
  type RetrievalResult,
  type RAGStats,
} from './knowledge-rag';

/**
 * 预热：检查知识库文件数量（不必预先向量化，检索时会自动处理）
 */
export function loadAllKnowledge(): { loaded: number; failed: number } {
  const stats = getRAGStats();
  return { loaded: stats.totalChunks || stats.totalFiles, failed: 0 };
}

/**
 * 核心 API：基于用户查询 & 意图，生成 RAG 知识上下文文本
 *
 * @param userMessage 用户原始消息（用于做向量检索）
 * @param intentType  意图类型（用于关键词加权、意图敏感的检索）
 * @param maxChars    返回文本的最大字符数（避免 prompt 过长）
 * @returns 结构化的 RAG 文本，可直接拼接到 LLM system prompt 中
 */
export async function getKnowledgeContext(
  userMessage: string,
  intentType: string = '',
  maxChars: number = 3500,
): Promise<string> {
  return await buildRAGContext(userMessage, intentType, maxChars);
}

/**
 * 同步版本 — 当调用方不方便使用 async 时
 * 如果首次调用且没有缓存，则返回一段简短的默认方法论框架
 * （在首次 API 请求预热后，异步请求会填充缓存）
 */
export function getKnowledgeContextSync(
  userMessage: string,
  intentType: string = '',
  maxChars: number = 3500,
): string {
  // 同步模式下直接触发异步检索（非阻塞，结果在下一次请求生效）
  buildRAGContext(userMessage, intentType, maxChars).catch((e) => {
    console.warn('[knowledge-loader-sync] async prefetch:', e);
  });

  // 同步返回默认框架（保证即时可用）
  return `
【方法论参考 — 默认框架（向量检索正在后台预加载）】

■ 三屏分析体系 (3-Screen System)
  1. 第一屏：周线周期 — 长期趋势判断 + 跨市场相关性分析
  2. 第二屏：日线周期 — 关键支撑/阻力位 + 入场信号触发
  3. 第三屏：小时/分钟 — 精确入场点位 + 止损设置

■ 风险管理核心
  - 单笔风险 = 账户资金 × 1%（建议）
  - 单笔最大风险 ≤ 2%
  - 连续亏损 3 次强制平仓 + 冷静期
  - 盈亏比 ≥ 2:1 才开仓
  - 凯利仓位公式优化

■ 技术分析框架
  - 趋势识别：200MA / 50MA + ADX(>25)
  - 震荡指标：RSI 14 期（超买 70 / 超卖 30）
  - 波动率：ATR 14 期，止损 = 2×ATR
  - 关键位：最近 20 根 K 线高低点 + 斐波那契
  - 多周期确认：周线→日线→小时线，三周期同向才开仓

■ 策略类型框架
  - 趋势跟随型：MA 交叉 + 突破，胜率约 40%，盈亏比 3:1
  - 均值回归型：RSI 超买超卖 + 布林带，适合震荡市
  - 波动率突破型：ATR 扩张 + 成交量确认

■ 反方观点验证（矛盾分析法核心）
  - 每次开仓前，先列出 3 条反方理由
  - 检查"锚定偏误"、"确认偏误"、"幸存者偏差"
  - 压力测试：若当前仓位亏损 50%，核心逻辑是否仍成立？

■ 事件驱动分析
  - 美联储加息/降息周期
  - BTC 减半周期（每 4 年一次）
  - ETF 资金流向 + 机构持仓变化
  - 监管事件影响
`;
}

/**
 * 获取知识库 / 向量缓存的诊断信息
 */
export function getKnowledgeStats(): RAGStats {
  return getRAGStats();
}

/**
 * 清除向量缓存（知识库内容变更后调用）
 */
export function resetKnowledgeCache(): boolean {
  return clearRAGCache();
}

// ============================================================
// 低层 API — 直接返回检索结果（用于更复杂的重排逻辑）
// ============================================================

export async function rawRetrieve(
  query: string,
  intentHint: string = '',
  topK: number = 5,
): Promise<RetrievalResult[]> {
  return await retrieveRelevantChunks(query, intentHint, topK);
}

export { type RetrievalResult, type RAGStats };
