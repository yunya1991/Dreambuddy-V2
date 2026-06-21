/** 精确复现 contract.ts 中 createCompressor 的逻辑 */

import { createBlueprint } from '../../../6-图结构上下文压缩/blueprint.ts';
import { expandToArchitecture } from '../../../6-图结构上下文压缩/architecture.ts';
import { expandToChronicle } from '../../../6-图结构上下文压缩/chronicle.ts';
import { compress as runCompress } from '../../../6-图结构上下文压缩/compressor.ts';
import { semanticCompress } from '../../../6-图结构上下文压缩/semantic-compressor.ts';
import { shardedCompress } from '../../../6-图结构上下文压缩/sharded-compressor.ts';
import { blueprintRegistry } from '../../../6-图结构上下文压缩/blueprint-registry.ts';
import { createCompressor } from '../../../6-图结构上下文压缩/contract.ts';

function estimateTokens(text: string): number {
  let chineseChars = 0;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code >= 0x4e00 && code <= 0x9fff) chineseChars++;
  }
  const asciiChars = text.length - chineseChars;
  return Math.ceil(chineseChars / 2) + Math.ceil(asciiChars / 4);
}

(async () => {
  try {
    const sessionCache = new Map<string, { blueprint: any; architecture: any }>();
    const sessionId = 'debug';
    const payload = [
      { id: '1', type: 'message', content: 'BTC 趋势分析' },
      { id: '2', type: 'message', content: 'RSI 超卖' },
      { id: '3', type: 'tool_call', content: '分析工具调用' },
    ];
    const targetRatio = 0.5;

    console.log('  -> routeByIntent');
    const intentText = payload.map((p) => p.content).join(' ').slice(0, 100);
    const matched = blueprintRegistry.routeByIntent(intentText);
    console.log('    matched:', matched?.name);

    let cached = sessionCache.get(sessionId);
    if (!cached) {
      if (matched) {
        console.log('  -> using matched blueprint');
        cached = {
          blueprint: matched.blueprint,
          architecture: matched.architectureFactory(),
        };
      } else {
        console.log('  -> creating fallback blueprint');
        const bp = createBlueprint(`Session ${sessionId}`);
        const arch = expandToArchitecture(bp);
        cached = { blueprint: bp, architecture: arch };
      }
      sessionCache.set(sessionId, cached);
    }
    console.log('    ✓ architecture nodes:', cached.architecture.nodes.size);

    console.log('  -> expandToChronicle');
    const chronicle = expandToChronicle(cached.architecture, sessionId);
    console.log('    ✓ chronicle nodes:', chronicle.nodes.size);

    console.log('  -> inject user messages');
    const extraNodes = payload.map((item, idx) => ({
      id: `user-${item.id}`,
      architectureNodeId: `user_${item.type}_${idx}`,
      name: item.content.slice(0, 60),
      tokens: item.tokens ?? estimateTokens(item.content),
      timestamp: Date.now() + idx,
    }));
    console.log('    extra nodes:', extraNodes.length);
    extraNodes.forEach((item) => {
      chronicle.nodes.set(item.id, {
        id: item.id,
        architectureNodeId: item.architectureNodeId,
        executionId: sessionId,
        startTime: item.timestamp,
        endTime: item.timestamp + 1,
        metadata: {
          tokenCost: item.tokens,
          latencyMs: 1,
          status: 'completed',
          outputSummary: item.name,
          timestamp: item.timestamp,
          tags: ['user'],
        },
        inputs: {},
        outputs: { content: item.name },
        logs: [],
      });
    });
    console.log('    ✓ total nodes:', chronicle.nodes.size);

    console.log('  -> semanticCompress');
    const result = semanticCompress(chronicle, cached.architecture, cached.blueprint, {
      targetRatio,
      semanticWeight: 0.4,
    });
    console.log('    ✓ result ratio:', result.compressionRatio);

    console.log('  -> call createCompressor directly');
    const c = createCompressor({ mode: 'semantic' });
    const out = await c.compress({
      sessionId: 'direct',
      payload: [{ id: '1', type: 'message', content: '测试内容' }],
    });
    console.log('    ✓ out ratio:', out.compressionRatio);
    console.log('    ✓ strategy:', out.report?.strategy);

    console.log('\n  ✅ 手动模拟全部成功');
  } catch (err) {
    console.error('\n  ❌ 错误：', err);
    if (err instanceof Error) console.error('  Stack:', err.stack);
    process.exit(1);
  }
})();
