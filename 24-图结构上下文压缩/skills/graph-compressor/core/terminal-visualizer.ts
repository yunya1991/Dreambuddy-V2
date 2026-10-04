/**
 * ============================================================
 *  📊  终端可视化渲染引擎（ASCII 架构图）
 * ============================================================
 *
 *  设计理念：核心是"展示压缩节点架构"，不是做美观的 UI
 *    • 三层架构图（Blueprint → Architecture → Chronicle）
 *    • 压缩前后对比（节点数/评分对比）
 *    • 关键路径高亮
 *    • 节点评分分布图
 *    • 语义标签云（ASCII 形式）
 *
 *  输出方式：
 *    • printToConsole() → 直接打印到终端
 *    • renderToText() → 返回纯文本，可保存/嵌入
 *    • renderToJson() → 返回结构化数据，便于程序处理
 */

import {
  semanticCompress,
  type SemanticCompressResult,
  type SemanticScoredNode,
  type SemanticCompressOptions,
} from './semantic-compressor-advanced.ts';

import { type CompressMessage } from './graph-compress.ts';

// ============================================================
// ==================== ASCII 字符集 ==========================
// ============================================================

const BOX = {
  tl: '┌', tr: '┐', bl: '└', br: '┘',
  h: '─', v: '│',
  tj: '┬', bj: '┴', lj: '├', rj: '┤', cross: '┼',
  dot: '•', star: '★', arrow: '→', thick: '━',
};

const SCORE_BARS = ['░', '▒', '▓', '█'];
const STATUS_ICONS = {
  kept: '✅',
  compressed: '🔻',
  decision: '🎯',
  analysis: '🔍',
  data: '📊',
  question: '❓',
  risk: '⚠️',
  generic: '•',
};

// ============================================================
// ==================== 辅助函数 ==============================
// ============================================================

function padRight(str: string, len: number): string {
  if (str.length >= len) return str.slice(0, len);
  return str + ' '.repeat(len - str.length);
}

function padCenter(str: string, len: number): string {
  if (str.length >= len) return str.slice(0, len);
  const totalPad = len - str.length;
  const left = Math.floor(totalPad / 2);
  return ' '.repeat(left) + str + ' '.repeat(totalPad - left);
}

function scoreBar(score: number, width: number = 20): string {
  const filled = Math.min(1, Math.max(0, score));
  const filledChars = Math.round(filled * width);
  const bars = SCORE_BARS[3].repeat(filledChars) + SCORE_BARS[0].repeat(width - filledChars);
  return bars;
}

function wrapText(text: string, width: number): string[] {
  const lines: string[] = [];
  const paragraphs = text.split('\n');
  for (const para of paragraphs) {
    if (para.length <= width) {
      lines.push(para);
      continue;
    }
    // 按标点/空格断行
    let current = '';
    const parts = para.split(/([，。！？；：、,.\s])/);
    for (const part of parts) {
      if ((current + part).length > width) {
        if (current) lines.push(current.trim());
        current = part;
      } else {
        current += part;
      }
    }
    if (current.trim()) lines.push(current.trim());
  }
  return lines;
}

// ============================================================
// ==================== 1. 三层架构图 ==========================
// ============================================================

interface LayerRenderOptions {
  width?: number;
  showScores?: boolean;
  showTags?: boolean;
}

function renderThreeLayerDiagram(
  result: SemanticCompressResult,
  options: LayerRenderOptions = {}
): string {
  const width = options.width || 70;
  const lines: string[] = [];

  lines.push(BOX.tl + BOX.h.repeat(width - 2) + BOX.tr);
  lines.push(BOX.v + padCenter('📐 三层图结构（B / A / C）', width - 2) + BOX.v);
  lines.push(BOX.lj + BOX.thick.repeat(width - 2) + BOX.rj);

  // ====== 层 B: Blueprint ======
  const bp = result.threeLayer.blueprint;
  lines.push(BOX.v + padRight('  B · Blueprint（顶层蓝图）', width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`    ID: ${bp.id}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`    主题: ${bp.name}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`    组件: ${bp.components.join(' · ') || '通用'}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`    标签: ${bp.topTags.join(' | ') || '-'}`, width - 2) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // B → A 的连线
  lines.push(BOX.v + '      ↓' + ' '.repeat(width - 9) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // ====== 层 A: Architecture ======
  const arch = result.threeLayer.architecture;
  lines.push(BOX.v + padRight(`  A · Architecture（执行步骤 · ${arch.length} 步）`, width - 2) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  arch.slice(0, 8).forEach((step, idx) => {
    const scoreColor = step.score > 0.7 ? '★' : step.score > 0.5 ? '●' : '○';
    const tagText = step.tags.slice(0, 2).join('/');
    const content = `    ${idx + 1}. ${scoreColor} [${(step.score * 100).toFixed(0)}分] ${step.type.padEnd(10)} ${step.name.slice(0, 40)}`;
    lines.push(BOX.v + padRight(content, width - 2) + BOX.v);
    if (idx < arch.length - 1) {
      lines.push(BOX.v + '         ↓' + ' '.repeat(width - 12) + BOX.v);
    }
  });

  if (arch.length > 8) {
    lines.push(BOX.v + padRight(`      ... 还有 ${arch.length - 8} 个步骤 ...`, width - 2) + BOX.v);
  }
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // A → C 的连线
  lines.push(BOX.v + '      ↓' + ' '.repeat(width - 9) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // ====== 层 C: Chronicle ======
  const chron = result.threeLayer.chronicle;
  const keptCount = chron.filter((c) => c.status === 'kept').length;
  lines.push(BOX.v + padRight(`  C · Chronicle（执行记录 · ${chron.length} 条 · 保留 ${keptCount} 条）`, width - 2) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // 前 5 条保留 + 3 条压缩作为示例
  chron.slice(0, 8).forEach((c) => {
    const icon = c.status === 'kept' ? STATUS_ICONS.kept : STATUS_ICONS.compressed;
    const scoreText = (c.score * 100).toFixed(0).padStart(3);
    const name = c.name.slice(0, 50);
    const content = `    ${icon} [${scoreText}分] [${c.tag.padEnd(8)}] ${name}`;
    lines.push(BOX.v + padRight(content, width - 2) + BOX.v);
  });
  if (chron.length > 8) {
    lines.push(BOX.v + padRight(`      ... 共 ${chron.length} 条（${chron.length - 8} 条省略）...`, width - 2) + BOX.v);
  }

  lines.push(BOX.bl + BOX.h.repeat(width - 2) + BOX.br);
  return lines.join('\n');
}

// ============================================================
// ==================== 2. 压缩前后对比图 =====================
// ============================================================

function renderCompressionComparison(
  result: SemanticCompressResult,
  width: number = 70
): string {
  const lines: string[] = [];
  const total = result.summary.totalMessages;
  const kept = result.summary.keptCount;
  const compressed = result.summary.compressedCount;

  lines.push(BOX.tl + BOX.h.repeat(width - 2) + BOX.tr);
  lines.push(BOX.v + padCenter('📊 压缩前后对比', width - 2) + BOX.v);
  lines.push(BOX.lj + BOX.thick.repeat(width - 2) + BOX.rj);

  // "前" 的柱状图（完整消息列表）
  lines.push(BOX.v + padRight('  压缩前（Before）', width - 2) + BOX.v);

  const colWidth = Math.floor((width - 8) / 3);
  let allBefore = '';
  result.timeline.forEach((n) => {
    allBefore += '█';
  });
  const beforeBar = allBefore.slice(0, width - 10);
  lines.push(BOX.v + padRight(`    节点: ${total} 个`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`    ${beforeBar}`, width - 2) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // "后" 的柱状图（保留/压缩分开显示）
  lines.push(BOX.v + padRight('  压缩后（After）', width - 2) + BOX.v);
  let afterBar = '';
  result.timeline.forEach((n) => {
    afterBar += n.kept ? '🟩' : '🔹';
  });
  afterBar = afterBar.slice(0, Math.floor((width - 10) / 2));
  lines.push(BOX.v + padRight(`    保留: ${kept} 个  ${STATUS_ICONS.kept.repeat(Math.min(kept, 20))}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`    压缩: ${compressed} 个  ${STATUS_ICONS.compressed.repeat(Math.min(compressed, 20))}`, width - 2) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // 时间线按顺序
  lines.push(BOX.v + padCenter('⏱  时间线（按消息顺序）', width - 2) + BOX.v);
  const timelineBar = result.timeline.map((n) => {
    if (n.kept) {
      if (n.role === 'user') return '👤';
      if (n.role === 'assistant') return '🤖';
      return '•';
    }
    return '·';
  }).join('');
  const barWidth = Math.floor((width - 8) / 2);
  lines.push(BOX.v + padRight(`    ${timelineBar.slice(0, barWidth)}`, width - 2) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // 压缩率 + 评分
  const ratio = result.summary.compressionRatio;
  lines.push(BOX.v + padRight(`  压缩率: ${(ratio * 100).toFixed(0)}%   ${scoreBar(ratio, Math.floor(width / 2 - 5))}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  平均保留评分: ${(result.summary.avgKeptScore * 100).toFixed(0)}/100`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  平均压缩评分: ${(result.summary.avgCompressedScore * 100).toFixed(0)}/100`, width - 2) + BOX.v);

  lines.push(BOX.bl + BOX.h.repeat(width - 2) + BOX.br);
  return lines.join('\n');
}

// ============================================================
// ==================== 3. 节点评分分布图 ======================
// ============================================================

function renderScoreDistribution(
  nodes: SemanticScoredNode[],
  width: number = 70
): string {
  const lines: string[] = [];
  // 10 个桶：0-0.1, 0.1-0.2, ... 0.9-1.0
  const buckets = new Array(10).fill(0);
  nodes.forEach((n) => {
    const idx = Math.min(9, Math.floor(n.score * 10));
    buckets[idx] += 1;
  });

  lines.push(BOX.tl + BOX.h.repeat(width - 2) + BOX.tr);
  lines.push(BOX.v + padCenter('📈 节点评分分布直方图', width - 2) + BOX.v);
  lines.push(BOX.lj + BOX.thick.repeat(width - 2) + BOX.rj);

  const maxCount = Math.max(...buckets, 1);
  const maxBarWidth = width - 20;

  for (let i = 0; i < 10; i++) {
    const rangeLow = (i * 0.1).toFixed(1);
    const rangeHigh = ((i + 1) * 0.1).toFixed(1);
    const count = buckets[i];
    const barLength = Math.round((count / maxCount) * maxBarWidth);
    const bar = SCORE_BARS[3].repeat(barLength);
    const label = `${rangeLow}-${rangeHigh}`;
    const status = i >= 6 ? '→ 保留' : i >= 3 ? '→ 临界' : '→ 压缩';
    lines.push(BOX.v + padRight(`  ${label}  ${count.toString().padStart(2)}  ${bar}  ${status}`, width - 2) + BOX.v);
  }

  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // 5 维评分对比（前 5 个高分节点）
  lines.push(BOX.v + padCenter('🎯 Top 节点 5 维评分详情', width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  ${'节点'.padEnd(12)} TF-IDF 关键词  信息熵 标签 元数据 总分`, width - 2) + BOX.v);
  nodes.slice().sort((a, b) => b.score - a.score).slice(0, 5).forEach((node, i) => {
    const bd = node.semanticBreakdown;
    const barW = 4;
    const shortId = (i + 1).toString();
    lines.push(BOX.v + padRight(
      `  N${shortId.padEnd(10)} ${scoreBar(bd.tfIdf, barW)} ${scoreBar(bd.keyword, barW)} ${scoreBar(bd.entropy, barW)} ${scoreBar(bd.tag, barW)} ${scoreBar(bd.metadata, barW)} ${scoreBar(node.score, barW)}`,
      width - 2
    ) + BOX.v);
  });

  lines.push(BOX.bl + BOX.h.repeat(width - 2) + BOX.br);
  return lines.join('\n');
}

// ============================================================
// ==================== 4. 关键路径图 =========================
// ============================================================

function renderCriticalPath(
  nodes: SemanticScoredNode[],
  width: number = 70
): string {
  const lines: string[] = [];

  // 按时间排序的保留节点（这是推理链）
  const keptTimeline = nodes.filter((n) => n.kept).sort((a, b) => a.timestamp - b.timestamp);

  lines.push(BOX.tl + BOX.h.repeat(width - 2) + BOX.tr);
  lines.push(BOX.v + padCenter('🛤️  关键推理路径（压缩后的信息链）', width - 2) + BOX.v);
  lines.push(BOX.lj + BOX.thick.repeat(width - 2) + BOX.rj);
  lines.push(BOX.v + padRight(`  路径长度: ${keptTimeline.length} 个节点`, width - 2) + BOX.v);
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  keptTimeline.forEach((node, idx) => {
    const isLast = idx === keptTimeline.length - 1;
    const tagText = node.tags[0]?.tag || 'GENERIC';
    const scoreText = (node.score * 100).toFixed(0);
    const nameText = node.name.slice(0, 50);

    // 节点框
    lines.push(BOX.v + `    ${BOX.tl + BOX.h.repeat(8) + BOX.tr}` + ' '.repeat(width - 14) + BOX.v);
    lines.push(BOX.v + `    ${BOX.v}[${tagText.padEnd(6)}]${BOX.v} ${nameText}` + ' '.repeat(Math.max(0, width - nameText.length - 16)) + BOX.v);
    lines.push(BOX.v + `    ${BOX.lj}${scoreText.padStart(4)}分${'─'.repeat(2)}${BOX.rj}` + ' '.repeat(Math.max(0, width - 14 - scoreText.length - nameText.length)) + BOX.v);
    if (!isLast) {
      lines.push(BOX.v + `         │` + ' '.repeat(width - 12) + BOX.v);
      lines.push(BOX.v + `         ↓` + ' '.repeat(width - 12) + BOX.v);
    }
  });

  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);
  lines.push(BOX.v + padCenter(`💡 从 ${nodes.length} 个消息压缩到 ${keptTimeline.length} 个关键节点`, width - 2) + BOX.v);
  lines.push(BOX.bl + BOX.h.repeat(width - 2) + BOX.br);

  return lines.join('\n');
}

// ============================================================
// ==================== 5. 语义标签云（ASCII） =================
// ============================================================

function renderTagCloud(
  result: SemanticCompressResult,
  width: number = 70
): string {
  const lines: string[] = [];

  lines.push(BOX.tl + BOX.h.repeat(width - 2) + BOX.tr);
  lines.push(BOX.v + padCenter('☁️  语义标签云', width - 2) + BOX.v);
  lines.push(BOX.lj + BOX.thick.repeat(width - 2) + BOX.rj);

  // 语义标签
  const tags = Object.entries(result.globalStats.tagDistribution)
    .sort((a, b) => b[1] - a[1]);
  lines.push(BOX.v + padRight('  语义标签:', width - 2) + BOX.v);
  tags.forEach(([tag, count]) => {
    const fontSize = count > 3 ? '🔵' : count > 1 ? '●' : '•';
    lines.push(BOX.v + padRight(`    ${fontSize} ${tag.padEnd(15)} × ${count}`, width - 2) + BOX.v);
  });
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // 关键词桶
  lines.push(BOX.v + padRight('  主题关键词桶:', width - 2) + BOX.v);
  Object.entries(result.globalStats.bucketHits).slice(0, 6).forEach(([bucket, hits]) => {
    const bar = SCORE_BARS[3].repeat(Math.min(hits * 2, 30));
    lines.push(BOX.v + padRight(`    ${bucket.padEnd(12)} ${bar} ${hits}`, width - 2) + BOX.v);
  });
  lines.push(BOX.v + ' '.repeat(width - 2) + BOX.v);

  // 高权重词汇（TF-IDF top）
  lines.push(BOX.v + padRight('  高权重词汇（TF-IDF）:', width - 2) + BOX.v);
  const vocabLine = result.globalStats.topGlobalTerms
    .slice(0, 12)
    .map((t) => t.term)
    .join(' · ');
  const wrapped = wrapText(vocabLine, width - 8);
  wrapped.forEach((line) => {
    lines.push(BOX.v + padRight(`    ${line}`, width - 2) + BOX.v);
  });

  lines.push(BOX.bl + BOX.h.repeat(width - 2) + BOX.br);
  return lines.join('\n');
}

// ============================================================
// ==================== 主渲染入口 ============================
// ============================================================

export interface VisualizerOptions {
  width?: number;
  sections?: Array<'overview' | 'threeLayer' | 'comparison' | 'distribution' | 'criticalPath' | 'tagCloud' | 'summary'>;
}

export function renderVisualization(
  result: SemanticCompressResult,
  options: VisualizerOptions = {}
): string {
  const width = options.width || 72;
  const sections = options.sections || [
    'overview', 'threeLayer', 'comparison', 'distribution',
    'criticalPath', 'tagCloud', 'summary'
  ];

  const output: string[] = [];

  // 标题
  output.push('\n' + '═'.repeat(width));
  output.push(padCenter(`📊 图结构上下文压缩 · 可视化报告`, width));
  output.push(padCenter(`会话: ${result.blueprint.id} · 共 ${result.summary.totalMessages} 条消息`, width));
  output.push('═'.repeat(width));

  // 概览
  if (sections.includes('overview')) {
    output.push('');
    output.push(renderOverviewSection(result, width));
  }

  // 三层架构图
  if (sections.includes('threeLayer')) {
    output.push('');
    output.push(renderThreeLayerDiagram(result, { width }));
  }

  // 压缩前后对比
  if (sections.includes('comparison')) {
    output.push('');
    output.push(renderCompressionComparison(result, width));
  }

  // 评分分布
  if (sections.includes('distribution')) {
    output.push('');
    output.push(renderScoreDistribution(result.semanticNodes, width));
  }

  // 关键路径
  if (sections.includes('criticalPath')) {
    output.push('');
    output.push(renderCriticalPath(result.semanticNodes, width));
  }

  // 标签云
  if (sections.includes('tagCloud')) {
    output.push('');
    output.push(renderTagCloud(result, width));
  }

  // 总结
  if (sections.includes('summary')) {
    output.push('');
    output.push(renderSummarySection(result, width));
  }

  output.push('═'.repeat(width));
  output.push('');
  return output.join('\n');
}

function renderOverviewSection(result: SemanticCompressResult, width: number): string {
  const lines: string[] = [];
  const s = result.summary;

  lines.push(BOX.tl + BOX.h.repeat(width - 2) + BOX.tr);
  lines.push(BOX.v + padCenter('📋 压缩概览', width - 2) + BOX.v);
  lines.push(BOX.lj + BOX.thick.repeat(width - 2) + BOX.rj);
  lines.push(BOX.v + padRight(`  总消息数:      ${s.totalMessages}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  保留节点:      ${s.keptCount}  ${scoreBar(1 - s.compressionRatio, 30)}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  压缩节点:      ${s.compressedCount}  ${scoreBar(s.compressionRatio, 30)}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  压缩率:        ${(s.compressionRatio * 100).toFixed(0)}%`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  识别意图:      ${s.intentDetected}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  总 tokens:     ${s.totalTokens}`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  处理耗时:      ${s.latencyMs}ms`, width - 2) + BOX.v);
  lines.push(BOX.v + padRight(`  词汇量:        ${result.globalStats.totalVocab}`, width - 2) + BOX.v);
  lines.push(BOX.bl + BOX.h.repeat(width - 2) + BOX.br);
  return lines.join('\n');
}

function renderSummarySection(result: SemanticCompressResult, width: number): string {
  const lines: string[] = [];

  lines.push(BOX.tl + BOX.h.repeat(width - 2) + BOX.tr);
  lines.push(BOX.v + padCenter('🎯 关键发现 & 建议', width - 2) + BOX.v);
  lines.push(BOX.lj + BOX.thick.repeat(width - 2) + BOX.rj);

  const highScoreNodes = result.kept.filter((n) => n.score > 0.7).length;
  lines.push(BOX.v + padRight(`  📌 发现 1: 高价值节点占保留节点的 ${((highScoreNodes / Math.max(result.kept.length, 1)) * 100).toFixed(0)}%`, width - 2) + BOX.v);

  const topTags = Object.entries(result.globalStats.tagDistribution)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([t]) => t);
  lines.push(BOX.v + padRight(`  📌 发现 2: 主要语义标签为 ${topTags.join(' / ')}`, width - 2) + BOX.v);

  const highRiskKeywords = Object.keys(result.globalStats.bucketHits)
    .filter((k) => ['risk', 'decision'].includes(k));
  lines.push(BOX.v + padRight(`  📌 发现 3: ${highRiskKeywords.length > 0 ? '含风险/决策类关键信息' : '以分析/数据为主'}`, width - 2) + BOX.v);

  const ratio = result.summary.compressionRatio;
  if (ratio > 0.7) {
    lines.push(BOX.v + padRight(`  💡 建议: 压缩率较高，考虑降低 targetRatio 以保留更多上下文`, width - 2) + BOX.v);
  } else if (ratio < 0.3) {
    lines.push(BOX.v + padRight(`  💡 建议: 压缩率较低，可以接受更激进的压缩`, width - 2) + BOX.v);
  } else {
    lines.push(BOX.v + padRight(`  💡 建议: 当前压缩率适中，压缩质量良好`, width - 2) + BOX.v);
  }

  lines.push(BOX.bl + BOX.h.repeat(width - 2) + BOX.br);
  return lines.join('\n');
}

// ============================================================
// ==================== 便捷 API ==============================
// ============================================================

export function printCompressVisualization(
  options: SemanticCompressOptions,
  vizOptions?: VisualizerOptions
): SemanticCompressResult {
  const result = semanticCompress(options);
  console.log(renderVisualization(result, vizOptions));
  return result;
}

export function renderCompressVisualization(
  messages: CompressMessage[],
  targetRatio: number = 0.5,
  width: number = 72
): {
  text: string;
  result: SemanticCompressResult;
} {
  const result = semanticCompress({ messages, targetRatio });
  return { text: renderVisualization(result, { width }), result };
}

export function printToConsole(
  messages: CompressMessage[],
  targetRatio: number = 0.5
): void {
  printCompressVisualization({ messages, targetRatio });
}

// ============================================================
// ==================== CLI 演示 ==============================
// ============================================================

if (typeof process !== 'undefined' && process.argv && process.argv[1]?.includes('terminal-visualizer.ts')) {
  console.log('\n' + '═'.repeat(72));
  console.log(padCenter('📊 终端可视化渲染引擎 - 演示模式', 72));
  console.log('═'.repeat(72));

  // 模拟对话消息
  const messages: CompressMessage[] = [
    { id: 'u1', role: 'user', content: '帮我分析 BTC 的短线交易机会', timestamp: Date.now() - 10000 },
    { id: 'a1', role: 'assistant', content: 'BTC 当前价格 65,200 USDT，RSI 55，MACD 金叉，均线多头排列，趋势向上。', timestamp: Date.now() - 9000 },
    { id: 'u2', role: 'user', content: '入场和止损应该怎么设置？', timestamp: Date.now() - 8000 },
    { id: 'a2', role: 'assistant', content: '建议：入场 64,800（回调支撑位），止损 64,200（近期低点下方），第一止盈 65,800。风险收益比约 1:1.67。', importance: 'high', timestamp: Date.now() - 7000 },
    { id: 'u3', role: 'user', content: '仓位呢？用多大杠杆比较合适？', timestamp: Date.now() - 6000 },
    { id: 'a3', role: 'assistant', content: '资金管理建议：仓位总资金的 3%，不超过 5x 杠杆。中等风险、胜率可接受的配置。', importance: 'high', timestamp: Date.now() - 5000 },
    { id: 'u4', role: 'user', content: '有没有历史回测？', timestamp: Date.now() - 4000 },
    { id: 'a4', role: 'assistant', content: '快速回测：过去 30 天类似信号出现 7 次，胜率 71%，平均持仓 3.2 天，最大回撤 4.2%。整体表现稳健。', timestamp: Date.now() - 3000 },
    { id: 'u5', role: 'user', content: '好的，那就按这个方案执行。', importance: 'high', timestamp: Date.now() - 2000 },
    { id: 'a5', role: 'assistant', content: '✅ 已确认方案，等待 BTC 价格触发入场条件。执行参数：入场 64,800 / 止损 64,200 / 止盈 65,800 / 仓位 3%。', importance: 'high', timestamp: Date.now() - 1000 },
  ];

  // 压缩 + 可视化
  printCompressVisualization({ messages, targetRatio: 0.5 });
}
