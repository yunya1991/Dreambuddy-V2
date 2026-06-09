'use client';

import { useParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import DebatePanel from '@/components/DebatePanel';
import type { Statement } from '@/lib/meeting-types';

export default function MeetingDetailPage() {
  const params = useParams();
  const meetingId = params.id as string;
  const [archiveText, setArchiveText] = useState('');
  const [statements, setStatements] = useState<Statement[]>([]);

  const handleComplete = (stmts: Statement[]) => {
    setStatements(stmts);
    // Generate archive text
    const lines = ['# 大师辩论纪要\n'];
    const conclusion = stmts.length > 0 ? '辩论已结束，结论见上方面板' : '';
    lines.push(`## 结论\n${conclusion}\n`);
    lines.push('## 辩论记录\n');
    for (const s of stmts) {
      const campNames: Record<string, string> = { bullish: '多头', neutral: '中立', bearish: '空头' };
      lines.push(`### R${s.round} ${s.type === 'opening' ? '开场' : s.type === 'rebuttal' ? '质询' : '结辩'} | ${campNames[s.campId] || s.campId} | ${s.master}\n`);
      lines.push(`${s.content}\n`);
    }
    setArchiveText(lines.join('\n'));
  };

  return (
    <div className="space-y-4">
      <nav className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/meeting" className="flex items-center gap-1 hover:text-blue-600">
          <ArrowLeft className="h-4 w-4" /> 会议室
        </Link>
        <span>/</span>
        <span className="text-gray-700 font-medium">{meetingId === 'quick-start' ? '快速研讨' : meetingId}</span>
      </nav>

      <DebatePanel meetingId={meetingId} onComplete={handleComplete} />

      {/* Archive section */}
      {archiveText && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-gray-900">会议纪要</h3>
            <button
              onClick={() => {
                navigator.clipboard?.writeText(archiveText);
                alert('已复制到剪贴板');
              }}
              className="text-xs px-3 py-1 rounded bg-gray-100 text-gray-600 hover:bg-gray-200"
            >
              复制导出
            </button>
          </div>
          <pre className="text-xs text-gray-600 bg-gray-50 rounded-lg p-3 max-h-60 overflow-y-auto whitespace-pre-wrap">{archiveText}</pre>
        </div>
      )}
    </div>
  );
}
