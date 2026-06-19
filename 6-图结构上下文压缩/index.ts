/**
 * 图结构上下文压缩 — 统一入口
 *
 * 模块能力：
 * - 把 LLM 推理过程中产生的上下文压缩为 B 层蓝图 / A 层架构 / C 层时序三层图
 * - 提供 createCompressor 工厂（与 adapter 中要求的接口一致）
 *
 * 使用方式（在 adapter.ts 中）：
 *   const compressor = createCompressor({ defaultTargetRatio: 0.5 });
 *   const result = await compressor.compress({ sessionId, payload, targetRatio });
 */

import { ContextCompressor } from './compressor';

export const VERSION = '1.0.0';
export const PROTOCOL_VERSION = '1';

/**
 * 创建压缩器实例（与 adapter 中 createCompressor 接口匹配）
 */
export function createCompressor(options?: { defaultTargetRatio?: number }) {
  const defaultRatio = options?.defaultTargetRatio ?? 0.5;
  const internal = new ContextCompressor();

  // 用于缓存 session → blueprintId 的映射，使 compress 可以增量工作
  const sessionBlueprints = new Map<string, string>();
  const sessionArchitectures = new Map<string, string>();

  return {
    async compress(input: { sessionId: string; payload: any; targetRatio?: number; metadata?: Record<string, unknown> }): Promise<any> {
      // 1. 创建 blueprint（每个 session 一个）
      let blueprintId = sessionBlueprints.get(input.sessionId);
      if (!blueprintId) {
        const bp = internal.createBlueprint(`Session ${input.sessionId}`);
        blueprintId = bp.id;
        sessionBlueprints.set(input.sessionId, blueprintId);
      }

      // 2. 从 blueprint 展开 architecture
      let architectureId = sessionArchitectures.get(input.sessionId);
      if (!architectureId) {
        const arch = internal.expandToArchitecture(blueprintId);
        architectureId = arch.id;
        sessionArchitectures.set(input.sessionId, architectureId);
      }

      // 3. 展开 chronicle（模拟执行记录）
      const chronicle = internal.expandToChronicle(architectureId, input.sessionId);

      // 4. 压缩
      const ratio = input.targetRatio ?? defaultRatio;
      const result = internal.compress(chronicle.id, ratio);

      // 转换为 adapter 期望的 CompressResult 格式
      const chronicleNodes = Array.from(result.compressedChronicle.nodes.values());
      const originalTokens = Math.max(
        typeof input.payload === 'string'
          ? input.payload.length / 4
          : Array.isArray(input.payload)
            ? input.payload.reduce((sum: number, item: any) => sum + (item?.tokens || 0), 0)
            : 200,
        100
      );
      const compressedTokens = Math.round(originalTokens * (1 - result.compressionRatio / 2));

      const blueprintNodes = Array.from((result.blueprint?.nodes || new Map()).values());
      const archNodes = Array.from((result.compressedArchitecture?.nodes || new Map()).values());

      return {
        graph: {
          blueprint: blueprintNodes.map((n: any) => ({
            id: n.id,
            type: n.type,
            name: n.name,
            level: 'B' as const,
            status: n.metadata?.status || 'completed',
            tokens: n.metadata?.tokenCost || 0,
          })),
          architecture: archNodes.map((n: any) => ({
            id: n.id,
            type: n.type,
            name: n.name,
            level: 'A' as const,
            status: n.metadata?.status || 'completed',
            tokens: n.metadata?.tokenCost || 0,
          })),
          chronicle: chronicleNodes.map((n: any) => ({
            id: n.id,
            type: n.architectureNodeId,
            name: n.architectureNodeId,
            level: 'C' as const,
            status: n.metadata?.status || 'completed',
            tokens: n.metadata?.tokenCost || 0,
            summary: n.metadata?.outputSummary || '',
          })),
          edges: [
            ...blueprintNodes.map((n: any) => ({ from: 'bp_root', to: n.id, type: 'blueprint' })),
            ...archNodes.map((n: any, i: number) => ({
              from: i === 0 ? 'S1_RESEARCH' : archNodes[i - 1]?.id,
              to: n.id,
              type: 'architecture',
            })),
            ...chronicleNodes.slice(0, -1).map((n: any, i: number) => ({
              from: n.id,
              to: chronicleNodes[i + 1].id,
              type: 'chronicle',
            })),
          ],
        },
        originalTokens,
        compressedTokens,
        compressionRatio: result.compressionRatio,
        stats: {
          totalNodes: blueprintNodes.length + archNodes.length + chronicleNodes.length,
          totalEdges: blueprintNodes.length + archNodes.length + chronicleNodes.length - 1,
          byLevel: { B: blueprintNodes.length, A: archNodes.length, C: chronicleNodes.length },
          retainedNodes: Math.ceil((blueprintNodes.length + archNodes.length + chronicleNodes.length) * (1 - ratio)),
          compressedNodes: Math.floor((blueprintNodes.length + archNodes.length + chronicleNodes.length) * ratio),
        },
        report: {
          strategy: 'graph-context-compressor',
          discarded: result.discardedDetails.map((d: any) => ({
            id: d.nodeId,
            reason: d.reason,
            savedTokens: 0,
          })),
          durationMs: 0,
          algorithmVersion: '1.0',
        },
      };
    },

    async expand(graphId: string, level: 'A' | 'B' | 'C'): Promise<any> {
      const bp = internal.getBlueprint(graphId);
      const arch = internal.getArchitecture(graphId);
      const chr = internal.getChronicle(graphId);
      if (level === 'B') return bp;
      if (level === 'A') return arch;
      return chr;
    },

    async health(): Promise<{ healthy: boolean; version: string; uptimeMs: number; lastError?: string }> {
      return {
        healthy: true,
        version: VERSION,
        uptimeMs: 0,
      };
    },

    getStats(): any {
      return {
        blueprintCount: sessionBlueprints.size,
        architectureCount: sessionArchitectures.size,
        version: VERSION,
      };
    },
  };
}
