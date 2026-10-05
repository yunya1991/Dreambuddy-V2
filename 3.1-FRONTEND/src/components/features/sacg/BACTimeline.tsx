'use client';

import { useState, useEffect } from 'react';
import { V3Card, V3Badge, V3Empty } from '@/components';
import api from '@/lib/api-client';

type BACLevel = 'B' | 'A' | 'C';
const levelLabels = { B: 'Blueprint 蓝图', A: 'Architecture 架构', C: 'Chronicle 编年' };
const levelColors = { B: 'border-blue-500/30 bg-blue-900/10', A: 'border-purple-500/30 bg-purple-900/10', C: 'border-amber-500/30 bg-amber-900/10' };
const levelVariant = { B: 'sacg-a' as const, A: 'sacg-s' as const, C: 'sacg-g' as const };

interface CompressionStats {
  totalCompressions: number;
  graphCompressions: number;
  fallbackCompressions: number;
  averageCompressionRatio: number;
  averageLatencyMs: number;
  totalTokensSaved: number;
}

interface SessionMeta {
  sessionId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
  tokenEstimate: number;
  tag?: string[];
}

interface CompressionResponse {
  stats: CompressionStats;
  sessions: SessionMeta[];
}

export function BACTimeline() {
  const [selectedLevel, setSelectedLevel] = useState<BACLevel>('B');
  const [stats, setStats] = useState<CompressionStats | null>(null);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const data = await api.get<CompressionResponse>('/api/compression/stats');
        if (!cancelled && data) {
          setStats(data.stats);
          setSessions(data.sessions || []);
        }
      } catch {
        // FAIL-OPEN: 静默失败，显示空状态
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => { cancelled = true; };
  }, []);

  // 按 messageCount 规模将会话映射到 BAC 层（B=大/全量, A=中/结构化, C=小/压缩）
  const levelOf = (s: SessionMeta): BACLevel => {
    if (s.messageCount >= 10) return 'B';
    if (s.messageCount >= 4) return 'A';
    return 'C';
  };

  const visibleSessions = sessions
    .filter(s => levelOf(s) === selectedLevel)
    .sort((a, b) => b.updatedAt - a.updatedAt);

  return (
    <div className="space-y-4">
      {/* 压缩统计总览 */}
      <V3Card title="BAC 压缩统计" padding="sm">
        {loading ? (
          <p className="text-xs text-slate-500 text-center py-4">加载中…</p>
        ) : stats ? (
          <div className="grid grid-cols-4 gap-3">
            <div className="text-center">
              <p className="text-lg font-bold text-slate-200">{stats.totalCompressions}</p>
              <p className="text-[10px] text-slate-500">总压缩次数</p>
            </div>
            <div className="text-center">
              <p className="text-lg font-bold text-emerald-400">{stats.graphCompressions}</p>
              <p className="text-[10px] text-slate-500">图压缩</p>
            </div>
            <div className="text-center">
              <p className="text-lg font-bold text-blue-400">{(stats.averageCompressionRatio * 100).toFixed(0)}%</p>
              <p className="text-[10px] text-slate-500">平均压缩率</p>
            </div>
            <div className="text-center">
              <p className="text-lg font-bold text-amber-400">{stats.totalTokensSaved}</p>
              <p className="text-[10px] text-slate-500">节省 tokens</p>
            </div>
          </div>
        ) : (
          <V3Empty title="暂无压缩统计" description="等待压缩器运行" />
        )}
      </V3Card>

      {/* BAC 层选择器 */}
      <div className="flex items-center gap-2 mb-4">
        {(Object.keys(levelLabels) as BACLevel[]).map(level => (
          <button key={level} onClick={() => setSelectedLevel(level)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs transition-colors ${selectedLevel === level ? levelColors[level] : 'border-slate-700/30 bg-slate-800/30 text-slate-500 hover:text-slate-300'}`}>
            <V3Badge variant={levelVariant[level]} dot label={level} />
            <span>{levelLabels[level]}</span>
          </button>
        ))}
      </div>

      {/* 会话检查点列表 */}
      <V3Card title={`${levelLabels[selectedLevel]} 层（${visibleSessions.length}）`} padding="sm">
        {loading ? (
          <p className="text-xs text-slate-500 text-center py-4">加载中…</p>
        ) : visibleSessions.length > 0 ? (
          <div className="space-y-2">
            {visibleSessions.map(s => {
              const lv = levelOf(s);
              return (
                <div key={s.sessionId} className={`flex items-center justify-between p-3 rounded-lg border ${levelColors[lv]}`}>
                  <div className="flex items-center gap-3">
                    <V3Badge variant={levelVariant[lv]} label={lv} />
                    <div>
                      <p className="text-xs text-slate-300 truncate max-w-[200px]">{s.title || s.sessionId}</p>
                      <p className="text-[10px] text-slate-500">
                        {s.messageCount} 条消息 · ~{s.tokenEstimate} tokens
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    {stats && stats.totalCompressions > 0 && (
                      <V3Badge variant="success" label="已压缩" />
                    )}
                    <p className="text-[10px] text-slate-500 mt-1">
                      {new Date(s.updatedAt).toLocaleString('zh-CN')}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <V3Empty title={`暂无 ${levelLabels[selectedLevel]} 会话`} description="等待图架构上下文压缩产生会话" />
        )}
      </V3Card>

      {/* 压缩方向说明 */}
      <div className="p-3 rounded-lg bg-slate-800/30 border border-slate-700/20">
        <p className="text-[10px] text-slate-500 mb-1">压缩方向</p>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-blue-400">B (全量)</span>
          <span className="text-slate-600">→</span>
          <span className="text-purple-400">A (结构化)</span>
          <span className="text-slate-600">→</span>
          <span className="text-amber-400">C (压缩)</span>
        </div>
        <p className="text-[10px] text-slate-600 mt-1">正向展开: C→A→B / 反向压缩: B→A→C</p>
      </div>
    </div>
  );
}
