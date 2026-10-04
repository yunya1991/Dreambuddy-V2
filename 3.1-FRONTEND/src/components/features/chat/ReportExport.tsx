'use client';

// ============================================
// ReportExport — 深度分析报告导出 (Markdown / PDF)
// ============================================

import React from 'react';
import type { FinalSynthesisData } from '@/stores/session-store';

interface ReportExportProps {
  synthesis: FinalSynthesisData;
  symbol?: string;
}

function escapeMd(text: string): string {
  return text.replace(/\|/g, '\\|').replace(/\n/g, '<br>');
}

function buildMarkdown(synthesis: FinalSynthesisData, symbol = 'BTC'): string {
  const now = new Date().toLocaleString('zh-CN');
  const lines: string[] = [];

  lines.push(`# ${symbol} 深度分析报告`);
  lines.push('');
  lines.push(`> 生成时间: ${now}`);
  lines.push('');

  // 摘要
  if (synthesis.final_summary) {
    lines.push('## 报告摘要');
    lines.push('');
    lines.push(synthesis.final_summary);
    lines.push('');
  }

  // 洞察
  if (synthesis.insights && synthesis.insights.length > 0) {
    lines.push('## 分析洞察');
    lines.push('');
    for (const ins of synthesis.insights) {
      const sev = ins.severity ? ` [${ins.severity.toUpperCase()}]` : '';
      lines.push(`### ${ins.title}${sev}`);
      lines.push('');
      if (ins.content) {
        lines.push(ins.content);
        lines.push('');
      }
      if (ins.source_modules && ins.source_modules.length > 0) {
        lines.push(`*数据来源: ${ins.source_modules.join(', ')}*`);
        lines.push('');
      }
    }
  }

  // 建议
  if (synthesis.recommendations && synthesis.recommendations.length > 0) {
    lines.push('## 操作建议');
    lines.push('');
    for (const rec of synthesis.recommendations) {
      const pri = rec.priority ? ` [${rec.priority.toUpperCase()}]` : '';
      lines.push(`- **${rec.action}**${pri}: ${rec.reason}`);
      if (rec.confidence !== undefined) {
        lines.push(`  - 置信度: ${(rec.confidence * 100).toFixed(0)}%`);
      }
    }
    lines.push('');
  }

  // 增强提示
  if (synthesis.enhancement_hints && synthesis.enhancement_hints.length > 0) {
    lines.push('## 深度增强建议');
    lines.push('');
    for (const h of synthesis.enhancement_hints) {
      lines.push(`- **${h.skill_name}** (${h.priority}): ${h.reason}`);
    }
    lines.push('');
  }

  lines.push('---');
  lines.push('*本报告由 DreamBuddy 深度分析系统自动生成, 仅供参考, 不构成投资建议*');

  return lines.join('\n');
}

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function buildPrintHtml(synthesis: FinalSynthesisData, symbol = 'BTC'): string {
  const now = new Date().toLocaleString('zh-CN');
  const insightsHtml = (synthesis.insights || [])
    .map(ins => `
      <div class="insight">
        <h3>${escapeMd(ins.title)}${ins.severity ? ` <span class="sev-${ins.severity}">[${ins.severity.toUpperCase()}]</span>` : ''}</h3>
        <p>${escapeMd(ins.content || '').replace(/\n/g, '<br>')}</p>
        ${ins.source_modules?.length ? `<p class="source">数据来源: ${ins.source_modules.join(', ')}</p>` : ''}
      </div>
    `).join('');

  const recsHtml = (synthesis.recommendations || [])
    .map(rec => `
      <li><strong>${escapeMd(rec.action)}</strong>${rec.priority ? ` <span class="pri-${rec.priority}">[${rec.priority}]</span>` : ''}: ${escapeMd(rec.reason)}${rec.confidence !== undefined ? ` <em>置信度: ${(rec.confidence * 100).toFixed(0)}%</em>` : ''}</li>
    `).join('');

  const hintsHtml = (synthesis.enhancement_hints || [])
    .map(h => `<li><strong>${escapeMd(h.skill_name)}</strong> (${h.priority}): ${escapeMd(h.reason)}</li>`)
    .join('');

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>${symbol} 深度分析报告</title>
<style>
  body { font-family: -apple-system, "PingFang SC", sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #1f2937; }
  h1 { border-bottom: 2px solid #a78bfa; padding-bottom: 8px; }
  h2 { color: #4b5563; margin-top: 24px; }
  h3 { color: #374151; margin-top: 16px; }
  .meta { color: #6b7280; font-size: 12px; }
  .insight { background: #f9fafb; border-left: 3px solid #a78bfa; padding: 12px 16px; margin: 12px 0; border-radius: 4px; }
  .source { color: #9ca3af; font-size: 11px; }
  .sev-high { color: #dc2626; } .sev-warning { color: #d97706; } .sev-info { color: #2563eb; }
  .pri-high { color: #dc2626; } .pri-medium { color: #d97706; } .pri-low { color: #6b7280; }
  ul { line-height: 1.8; }
  .footer { margin-top: 40px; border-top: 1px solid #e5e7eb; padding-top: 12px; color: #9ca3af; font-size: 11px; }
  @media print { body { margin: 0; } }
</style></head>
<body>
  <h1>${symbol} 深度分析报告</h1>
  <p class="meta">生成时间: ${now}</p>
  ${synthesis.final_summary ? `<h2>报告摘要</h2><p>${escapeMd(synthesis.final_summary)}</p>` : ''}
  ${insightsHtml ? `<h2>分析洞察</h2>${insightsHtml}` : ''}
  ${recsHtml ? `<h2>操作建议</h2><ul>${recsHtml}</ul>` : ''}
  ${hintsHtml ? `<h2>深度增强建议</h2><ul>${hintsHtml}</ul>` : ''}
  <div class="footer">本报告由 DreamBuddy 深度分析系统自动生成, 仅供参考, 不构成投资建议</div>
</body></html>`;
}

export function ReportExport({ synthesis, symbol = 'BTC' }: ReportExportProps) {
  const hasContent = (synthesis.insights?.length || 0) > 0 || (synthesis.recommendations?.length || 0) > 0;
  if (!hasContent) return null;

  const handleMd = () => {
    const md = buildMarkdown(synthesis, symbol);
    const date = new Date().toISOString().slice(0, 10);
    downloadFile(md, `${symbol}_深度分析_${date}.md`, 'text/markdown;charset=utf-8');
  };

  const handlePdf = () => {
    const html = buildPrintHtml(synthesis, symbol);
    const win = window.open('', '_blank');
    if (!win) {
      // 弹窗被拦截, 用 iframe 方式
      const iframe = document.createElement('iframe');
      iframe.style.position = 'fixed';
      iframe.style.right = '0';
      iframe.style.bottom = '0';
      iframe.style.width = '0';
      iframe.style.height = '0';
      iframe.style.border = '0';
      document.body.appendChild(iframe);
      const doc = iframe.contentWindow?.document;
      if (doc) {
        doc.open();
        doc.write(html);
        doc.close();
        setTimeout(() => {
          iframe.contentWindow?.focus();
          iframe.contentWindow?.print();
          setTimeout(() => document.body.removeChild(iframe), 1000);
        }, 300);
      }
      return;
    }
    win.document.open();
    win.document.write(html);
    win.document.close();
    setTimeout(() => {
      win.focus();
      win.print();
    }, 300);
  };

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handleMd}
        className="text-[11px] px-2.5 py-1 rounded bg-gray-700/50 text-gray-300 hover:bg-gray-600/50 transition-colors flex items-center gap-1"
        title="导出为 Markdown"
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
        </svg>
        MD
      </button>
      <button
        onClick={handlePdf}
        className="text-[11px] px-2.5 py-1 rounded bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 transition-colors flex items-center gap-1"
        title="导出为 PDF (打印)"
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6.72 13.829c-.24.03-.48.062-.72.096m.72-.096a42.415 42.415 0 0 1 10.56 0m-10.56 0L6.34 18m10.94-4.171c.24.03.48.062.72.096m-.72-.096L17.66 18m0 0 .229 2.523a1.125 1.125 0 0 1-1.12 1.227H7.231c-.662 0-1.18-.568-1.12-1.227L6.34 18m11.318 0h1.091A2.25 2.25 0 0 0 21 15.75V9.456c0-1.081-.768-2.015-1.837-2.175a48.055 48.055 0 0 0-1.913-.247M6.34 18H5.25A2.25 2.25 0 0 1 3 15.75V9.456c0-1.081.768-2.015 1.837-2.175a48.041 48.041 0 0 1 1.913-.247m10.5 0a48.536 48.536 0 0 0-10.5 0m10.5 0V3.375c0-.621-.504-1.125-1.125-1.125h-8.25c-.621 0-1.125.504-1.125 1.125v3.659M18 10.5h.008v.008H18V10.5Zm-3 0h.008v.008H15V10.5Z" />
        </svg>
        PDF
      </button>
    </div>
  );
}

export default ReportExport;
