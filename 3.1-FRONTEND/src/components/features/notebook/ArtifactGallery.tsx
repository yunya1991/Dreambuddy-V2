'use client';

import React, { useEffect, useState } from 'react';
import { V3Badge } from '@/components';

interface ArtifactMeta {
  artifact_id: string;
  artifact_type: string;
  title: string;
  created_at: number;
  created_at_iso: string;
  tags: string[];
  source?: string;
  summary?: string;
}

const TYPE_COLORS: Record<string, string> = {
  briefing: 'bg-blue-500',
  mood_board: 'bg-purple-500',
  insight_card: 'bg-green-500',
  bull_bear_debate: 'bg-amber-500',
  report: 'bg-cyan-500',
  chart: 'bg-pink-500',
};

/**
 * 产物中台展示组件 (F7.5)
 * 列出 DreamOS 产物中台的所有产物，支持按类型筛选
 */
export function ArtifactGallery() {
  const [artifacts, setArtifacts] = useState<ArtifactMeta[]>([]);
  const [filter, setFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const url = filter === 'all' ? '/api/artifacts?limit=50' : `/api/artifacts?type=${filter}&limit=50`;
    setLoading(true);
    // TODO: migrate to domain client — query params (?limit=50, ?type=) not supported by artifactApi.list()
    fetch(url)
      .then(r => r.json())
      .then(d => {
        if (d.success) setArtifacts(d.items || []);
      })
      .catch(() => setArtifacts([]))
      .finally(() => setLoading(false));
  }, [filter]);

  const types = ['all', 'briefing', 'mood_board', 'insight_card', 'bull_bear_debate', 'report', 'chart'];

  return (
    <div className="rounded-lg border border-v3-border bg-v3-bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-v3-text-primary">产物中台</h3>
        <V3Badge variant="default">{artifacts.length} 个产物</V3Badge>
      </div>

      {/* 类型筛选 */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {types.map(t => (
          <button
            key={t}
            onClick={() => setFilter(t)}
            className={`px-2 py-0.5 rounded text-xs transition-colors ${
              filter === t ? 'bg-v3-accent-blue text-white' : 'bg-v3-bg-subtle text-v3-text-secondary hover:bg-v3-bg-hover'
            }`}
          >
            {t === 'all' ? '全部' : t}
          </button>
        ))}
      </div>

      {/* 产物列表 */}
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {loading && <div className="text-xs text-v3-text-tertiary">加载中...</div>}
        {!loading && artifacts.length === 0 && (
          <div className="text-xs text-v3-text-tertiary">暂无产物</div>
        )}
        {artifacts.map(a => (
          <div
            key={a.artifact_id}
            className="p-2.5 rounded bg-v3-bg-subtle hover:bg-v3-bg-hover transition-colors cursor-pointer"
          >
            <div className="flex items-start gap-2">
              <span className={`inline-block w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${TYPE_COLORS[a.artifact_type] || 'bg-gray-500'}`} />
              <div className="min-w-0 flex-1">
                <div className="text-sm text-v3-text-primary truncate">{a.title}</div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-v3-text-tertiary">
                    {new Date(a.created_at_iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                  </span>
                  {a.tags?.slice(0, 2).map(tag => (
                    <span key={tag} className="text-[10px] px-1 rounded bg-v3-bg-hover text-v3-text-tertiary">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
