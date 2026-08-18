'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import type { Statement, Camp } from '@/lib/meeting-types';
import { CAMPS } from '@/lib/meeting-types';

interface Props {
  meetingId: string;
  onComplete?: (statements: Statement[]) => void;
}

export default function DebatePanel({ meetingId, onComplete }: Props) {
  const [statements, setStatements] = useState<Statement[]>([]);
  const [status, setStatus] = useState<'idle' | 'streaming' | 'paused' | 'done'>('idle');
  const [progress, setProgress] = useState(0);
  const [conclusion, setConclusion] = useState<any>(null);
  const [activeCamp, setActiveCamp] = useState<string>('');
  const eventSourceRef = useRef<EventSource | null>(null);

  const totalSteps = 13; // 12 debate statements + 1 conclusion

  const startDebate = useCallback(() => {
    setStatements([]);
    setProgress(0);
    setConclusion(null);
    setStatus('streaming');

    const es = new EventSource('/api/meeting/stream');
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      if (event.data === '[DONE]') {
        es.close();
        setStatus('done');
        return;
      }
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'conclusion') {
          setConclusion(data);
        } else {
          setActiveCamp(data.campId);
          setStatements(prev => {
            const updated = [...prev, data];
            setProgress(updated.length);
            if (onComplete && updated.length === 12 && data.type === 'final') {
              // All statements received, will get conclusion next
            }
            return updated;
          });
        }
      } catch {}
    };

    es.onerror = () => {
      es.close();
      setStatus('done');
    };
  }, [onComplete]);

  const pauseResume = useCallback(() => {
    if (status === 'streaming') {
      eventSourceRef.current?.close();
      setStatus('paused');
    } else if (status === 'paused') {
      setStatus('streaming');
      startDebate();
    }
  }, [status, startDebate]);

  useEffect(() => {
    return () => eventSourceRef.current?.close();
  }, []);

  const camps: Camp[] = CAMPS;

  const getCampStatements = (campId: string) =>
    statements.filter(s => s.campId === campId);

  const progressPct = Math.round((progress / totalSteps) * 100);

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3">
        {status === 'idle' && (
          <button onClick={startDebate} className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-500 text-white hover:bg-blue-600">
            开始辩论
          </button>
        )}
        {(status === 'streaming' || status === 'paused') && (
          <button onClick={pauseResume} className="px-4 py-2 rounded-lg text-sm font-medium bg-amber-500 text-white hover:bg-amber-600">
            {status === 'streaming' ? '暂停' : '继续'}
          </button>
        )}
        {status === 'done' && (
          <button onClick={startDebate} className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-600 hover:bg-gray-200">
            重新开始
          </button>
        )}

        {/* Progress */}
        {status !== 'idle' && (
          <div className="flex-1 flex items-center gap-2">
            <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500 rounded-full transition-all duration-300" style={{ width: `${progressPct}%` }} />
            </div>
            <span className="text-xs text-gray-400 w-12 text-right">{progressPct}%</span>
          </div>
        )}

        <span className="text-xs px-2 py-1 rounded" style={{
          background: status === 'streaming' ? '#EAF3DE' : status === 'done' ? '#F3F4F6' : status === 'paused' ? '#FAEEDA' : '#F3F4F6',
          color: status === 'streaming' ? '#3B6D11' : status === 'done' ? '#6B7280' : status === 'paused' ? '#854F0B' : '#6B7280',
        }}>
          {status === 'idle' ? '就绪' : status === 'streaming' ? '辩论中' : status === 'paused' ? '已暂停' : '已完成'}
        </span>
      </div>

      {/* Three-column debate output */}
      <div className="grid grid-cols-3 gap-3">
        {camps.map(camp => {
          const campStmts = getCampStatements(camp.id);
          const isActive = activeCamp === camp.id;
          return (
            <div key={camp.id} className="rounded-xl border p-3" style={{ borderColor: camp.borderColor, background: camp.bgColor }}>
              <h3 className="text-sm font-semibold mb-2" style={{ color: camp.color }}>
                {camp.name}
                <span className="text-xs font-normal ml-1" style={{ color: camp.color, opacity: 0.6 }}>
                  ({camp.masters.length}位大师)
                </span>
              </h3>
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {campStmts.map((s, i) => (
                  <div
                    key={i}
                    className="rounded-lg bg-white/70 p-2 text-xs border animate-fadeIn"
                    style={{
                      borderColor: camp.borderColor,
                      animation: 'fadeIn 0.3s ease-in',
                    }}
                  >
                    <div className="flex items-center gap-1.5 mb-1">
                      <span className="font-medium text-gray-800">{s.master}</span>
                      <span className="text-gray-400 scale-75">
                        {s.type === 'opening' ? '开场' : s.type === 'rebuttal' ? '质询' : '结辩'}
                      </span>
                      <span className="text-gray-300 scale-75 ml-auto">R{s.round}</span>
                    </div>
                    <p className="text-gray-600 leading-relaxed">{s.content}</p>
                  </div>
                ))}
                {campStmts.length === 0 && (
                  <div className="text-xs text-gray-400 py-4 text-center">等待发言...</div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Conclusion */}
      {conclusion && (
        <div className="rounded-xl border-2 border-blue-200 bg-blue-50 p-4">
          <h3 className="text-sm font-semibold text-blue-700 mb-2">辩论结论</h3>
          <p className="text-sm text-gray-700 mb-3">{conclusion.summary}</p>
          <div className="flex gap-2 text-xs mb-2">
            <span className="px-2 py-0.5 rounded bg-white border">偏向: {conclusion.bias > 0.5 ? '偏多' : '偏空'} ({(conclusion.bias * 100).toFixed(0)}%)</span>
            <span className="px-2 py-0.5 rounded bg-white border">置信度: {(conclusion.confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {conclusion.actionable.map((a: string, i: number) => (
              <div key={i} className="flex items-start gap-1.5 text-xs bg-white rounded-lg p-2 border">
                <span className="text-blue-500 font-medium shrink-0">{i + 1}.</span>
                <span className="text-gray-700">{a}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <style jsx>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
