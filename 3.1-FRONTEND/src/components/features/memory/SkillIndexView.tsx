'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';

interface SkillItem {
  name: string;
  description: string;
  version: string;
  status: string;
  category: string;
  triggers: string[];
  cognitive_links: string[];
  confidence: number;
  apply_count: number;
  last_verified: string | null;
  path: string;
}

interface SkillStats {
  total_count: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  roots_scanned: number;
}

const statusColor: Record<string, string> = {
  active: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
  shadow: 'bg-amber-900/40 text-amber-300 border-amber-700/40',
  deprecated: 'bg-rose-900/40 text-rose-300 border-rose-700/40',
  proposed: 'bg-blue-900/40 text-blue-300 border-blue-700/40',
  archived: 'bg-slate-700/40 text-slate-400 border-slate-600/40',
};

export function SkillIndexView() {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [stats, setStats] = useState<SkillStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [degraded, setDegraded] = useState(false);
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [filterCategory, setFilterCategory] = useState<string>('');

  useEffect(() => {
    Promise.all([
      fetch('/api/skills/index').then(r => r.ok ? r.json() : null).catch(() => null),
      // stats 走单独 adapter 命令（轻量化，避免重复扫描）
      fetch('/api/skills/index?status=active').then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([listData]) => {
      if (!listData || !listData.skills) {
        setDegraded(true);
        setLoading(false);
        return;
      }
      // 用 listData 推导 stats（避免多次扫描）
      const byStatus: Record<string, number> = {};
      const byCategory: Record<string, number> = {};
      listData.skills.forEach((s: SkillItem) => {
        byStatus[s.status] = (byStatus[s.status] || 0) + 1;
        byCategory[s.category] = (byCategory[s.category] || 0) + 1;
      });
      setSkills(listData.skills);
      setStats({
        total_count: listData.total_count ?? listData.count ?? listData.skills.length,
        by_status: byStatus,
        by_category: byCategory,
        roots_scanned: 0,
      });
      setDegraded(false);
      setLoading(false);
    });
  }, []);

  const filtered = skills.filter(s => {
    if (filterStatus && s.status !== filterStatus) return false;
    if (filterCategory && s.category !== filterCategory) return false;
    return true;
  });

  return (
    <div className="space-y-4">
      {degraded && (
        <V3Card padding="sm" className="border-amber-500/40 bg-amber-900/10">
          <div className="flex items-center gap-2 text-xs text-amber-300">
            <span>⚠</span>
            <span className="flex-1">Skill 索引后端不可达。请检查 <code className="text-amber-200">scripts/skill_index_adapter.py</code></span>
          </div>
        </V3Card>
      )}

      <V3Card title="Skill 索引统计" padding="sm">
        <div className="grid grid-cols-4 gap-3 text-center">
          <div>
            <p className="text-lg font-semibold text-blue-400">{stats?.total_count ?? '-'}</p>
            <p className="text-[10px] text-slate-500">总 Skill 数</p>
          </div>
          <div>
            <p className="text-lg font-semibold text-emerald-400">{stats?.by_status?.active ?? 0}</p>
            <p className="text-[10px] text-slate-500">Active</p>
          </div>
          <div>
            <p className="text-lg font-semibold text-amber-400">{stats?.by_status?.shadow ?? 0}</p>
            <p className="text-[10px] text-slate-500">Shadow</p>
          </div>
          <div>
            <p className="text-lg font-semibold text-rose-400">{stats?.by_status?.deprecated ?? 0}</p>
            <p className="text-[10px] text-slate-500">Deprecated</p>
          </div>
        </div>
        {stats?.by_category && Object.keys(stats.by_category).length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-700/30">
            <p className="text-[10px] text-slate-500 mb-1.5">分类分布</p>
            <div className="flex flex-wrap gap-1">
              {Object.entries(stats.by_category)
                .sort((a, b) => b[1] - a[1])
                .map(([cat, count]) => (
                  <span key={cat} className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800/40 text-slate-300 border border-slate-700/40">
                    {cat}: {count}
                  </span>
                ))}
            </div>
          </div>
        )}
      </V3Card>

      <V3Card title={`Skill 列表（${filtered.length} / ${skills.length}）`} padding="sm">
        <div className="flex gap-2 mb-3 text-xs">
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200"
          >
            <option value="">所有状态</option>
            <option value="active">Active</option>
            <option value="shadow">Shadow</option>
            <option value="deprecated">Deprecated</option>
            <option value="proposed">Proposed</option>
            <option value="archived">Archived</option>
          </select>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200"
          >
            <option value="">所有分类</option>
            {Object.keys(stats?.by_category || {}).sort().map(cat => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        </div>

        {loading ? (
          <p className="text-xs text-slate-500 text-center py-6">加载中...</p>
        ) : filtered.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-6">无匹配 Skill</p>
        ) : (
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
            {filtered.slice(0, 100).map(skill => (
              <div key={skill.path} className="flex items-start gap-2 p-2 rounded-lg bg-slate-900/30 border border-slate-700/20">
                <span className={`px-1.5 py-0.5 rounded text-[9px] border font-bold ${statusColor[skill.status] || statusColor.archived}`}>
                  {skill.status}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-slate-200 truncate">{skill.name}</p>
                  <p className="text-[10px] text-slate-500 line-clamp-1">{skill.description || '-'}</p>
                  {skill.triggers.length > 0 && (
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {skill.triggers.slice(0, 3).map(t => (
                        <span key={t} className="text-[9px] text-slate-600">#{t}</span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex flex-col items-end gap-0.5 shrink-0">
                  <span className="text-[9px] text-slate-400">conf {skill.confidence.toFixed(2)}</span>
                  <span className="text-[9px] text-slate-600">v{skill.version}</span>
                  {skill.cognitive_links.length > 0 && (
                    <V3Badge variant="success" label={`VM ${skill.cognitive_links.length}`} />
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </V3Card>
    </div>
  );
}
