/**
 * Compressor Adapter — 降级处理器
 *
 * 当图文压缩模块不可用时（未初始化/崩溃/协议不兼容），
 * 使用文本摘要作为降级策略，保证主流程不中断。
 *
 * @stability internal
 */

import type {
  CompressInput,
  CompressResult,
  GraphData,
  SerializedNode,
  SerializedEdge,
  GraphStats,
} from './types';

// ==================== 文本摘要降级 ====================

/**
 * 生成文本摘要作为降级结果
 *
 * 策略：
 * - 保留头部消息（最近 2-3 条）
 * - 中间部分做高度压缩
 * - 生成单层图结构（只有 C 层）
 */
export function createFallbackResult(
  input: CompressInput,
  originalTokens: number,
  targetRatio: number
): CompressResult {
  const items = normalizeItems(input);
  const retained = items.slice(-3); // 保留最近 3 条
  const compressedCount = Math.max(0, items.length - retained.length);

  // 估算压缩后 token 数
  const compressedTokens = Math.round(originalTokens * targetRatio);

  // 构建单层图（C 层）
  const chronicleNodes: SerializedNode[] = retained.map((item, idx) => ({
    id: item.id,
    type: item.type,
    name: truncateText(item.content, 50),
    level: 'C' as const,
    status: 'completed' as const,
    tokens: item.tokens ?? estimateTokens(item.content),
    compressed: idx < retained.length - 2, // 倒数第 3 条开始标记为压缩
    summary: truncateText(item.content, 120),
    meta: item.meta,
  }));

  // 构建边（线性链）
  const edges: SerializedEdge[] = [];
  for (let i = 0; i < chronicleNodes.length - 1; i++) {
    edges.push({
      from: chronicleNodes[i].id,
      to: chronicleNodes[i + 1].id,
      type: 'sequence',
    });
  }

  const graph: GraphData = {
    chronicle: chronicleNodes,
    edges,
  };

  const stats: GraphStats = {
    totalNodes: chronicleNodes.length,
    totalEdges: edges.length,
    byLevel: { B: 0, A: 0, C: chronicleNodes.length },
    retainedNodes: retained.length,
    compressedNodes: compressedCount,
  };

  return {
    graph,
    originalTokens,
    compressedTokens,
    compressionRatio: targetRatio,
    stats,
    report: {
      strategy: 'text-summarize-fallback',
      discarded: items
        .slice(0, -3)
        .map((item) => ({
          id: item.id,
          reason: '降级模式：超出保留窗口',
          savedTokens: item.tokens ?? estimateTokens(item.content),
        })),
      durationMs: 0,
      algorithmVersion: 'fallback-v1',
    },
  };
}

/**
 * 规范化输入为 CompressItem[]
 */
function normalizeItems(input: CompressInput): CompressItem[] {
  if (typeof input.payload === 'string') {
    // 字符串按行拆分
    return input.payload
      .split('\n')
      .filter((line) => line.trim())
      .map((line, idx) => ({
        id: `line-${idx}`,
        type: 'message' as const,
        content: line,
        tokens: estimateTokens(line),
      }));
  }
  return input.payload;
}

/**
 * 估算 token 数量
 * 规则: 中文 ≈ 2 chars/token，英文 ≈ 4 chars/token
 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  let chineseChars = 0;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code >= 0x4e00 && code <= 0x9fff) chineseChars++;
  }
  const asciiChars = text.length - chineseChars;
  return Math.ceil(chineseChars / 2) + Math.ceil(asciiChars / 4);
}

/** 文本截断 */
function truncateText(text: string, maxLen: number): string {
  if (!text || text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + '...';
}

// ==================== 类型补全（复用上面的） ====================
import type { CompressItem } from './types';
