'use client';

// ============================================================
// RecordExperienceForm (P3 Step 3)
// 用户填写 content + quality + tags → 写入新 VM
// 提交调 useMemoryStore.recordExperience → POST /api/cognitive/record
// 提交后 store 自动 fetchRecall + fetchStats 刷新
// FAIL-OPEN: 失败显示降级 banner + 错误信息
// ============================================================

import { useState } from 'react';
import { V3Card } from '@/components';
import { useMemoryStore, type QualityLevel } from '@/stores';

const QUALITY_OPTIONS: QualityLevel[] = ['S', 'A', 'B', 'C', 'D'];
const QUALITY_HINT: Record<QualityLevel, string> = {
  S: 'S 公理级',
  A: 'A 可信级',
  B: 'B 待验证',
  C: 'C 假设级',
  D: 'D 已证伪',
};

export function RecordExperienceForm() {
  const { recordExperience, degraded, error } = useMemoryStore();
  const [content, setContent] = useState('');
  const [quality, setQuality] = useState<QualityLevel>('B');
  const [tags, setTags] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [lastVmId, setLastVmId] = useState<string | null>(null);

  const handleSubmit = async () => {
    const trimmed = content.trim();
    if (!trimmed) return;
    setSubmitting(true);
    setLastVmId(null);
    const vmId = await recordExperience(trimmed, quality, tags);
    setSubmitting(false);
    if (vmId) {
      setLastVmId(vmId);
      setContent('');
      setTags('');
    }
  };

  return (
    <V3Card title="记录新经验 (P3 双向交互)" padding="sm">
      <div className="space-y-2">
        {degraded && (
          <div className="flex items-center gap-2 text-[10px] text-amber-300 bg-amber-900/10 border border-amber-500/30 rounded p-2">
            <span>⚠</span>
            <span>认知后端降级 — {error || '记录失败, 请检查 /api/cognitive/health'}</span>
          </div>
        )}
        {lastVmId && !degraded && (
          <div className="flex items-center gap-2 text-[10px] text-emerald-300 bg-emerald-900/10 border border-emerald-500/30 rounded p-2">
            <span>✓</span>
            <span>已写入 {lastVmId}</span>
          </div>
        )}
        <textarea
          placeholder="经验内容 (必填): 描述发现的反模式 / 解决方案 / 决策依据"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={3}
          className="w-full px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
        />
        <div className="flex gap-2">
          <select
            value={quality}
            onChange={(e) => setQuality(e.target.value as QualityLevel)}
            className="px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
          >
            {QUALITY_OPTIONS.map(q => (
              <option key={q} value={q}>{QUALITY_HINT[q]}</option>
            ))}
          </select>
          <input
            type="text"
            placeholder="tags (逗号分隔, 如: bug修复,交易,硬约束)"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            className="flex-1 px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
          />
          <button
            onClick={handleSubmit}
            disabled={!content.trim() || submitting}
            className="px-3 py-1 text-xs rounded bg-blue-600/30 hover:bg-blue-600/50 text-blue-200 disabled:opacity-50"
          >
            {submitting ? '提交中…' : '提交'}
          </button>
        </div>
      </div>
    </V3Card>
  );
}
