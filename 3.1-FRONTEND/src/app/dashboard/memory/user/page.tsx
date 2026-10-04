'use client';

// ============================================================
// /dashboard/memory/user 用户层记忆页 (P3 Step 6)
// P3 新增: 笔记沉淀审批流
//  - 每条笔记旁加"沉淀为平台经验"按钮 (仅当 promoted_to 为空)
//  - 点击展开内联审批表单 (quality select + tags input)
//  - 提交调 useUserMemoryStore.promoteNote → POST /api/user-memory/notes/[id]/promote
//  - 成功后笔记显示"已沉淀 VM-xxx"徽章 (原笔记保留不删除)
// 硬约束 (SPEC-COG-P1P3 §4.4): 必须用户主动点击, 禁止定时任务自动迁移
// ============================================================

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { MemoryTabNav } from '@/components/features/memory/MemoryTabNav';
import { useUserMemoryStore } from '@/stores/user-memory-store';

const QUALITY_OPTIONS = ['S', 'A', 'B', 'C', 'D'] as const;
const QUALITY_HINT: Record<string, string> = {
  S: 'S 公理级',
  A: 'A 可信级',
  B: 'B 待验证 (推荐)',
  C: 'C 假设级',
  D: 'D 已证伪',
};

export default function UserMemoryPage() {
  const {
    preferences, notes, health, degraded, loading,
    fetchPreferences, setPreference, fetchNotes, createNote, deleteNote, fetchHealth,
    promoteNote,
  } = useUserMemoryStore();

  const [newPrefKey, setNewPrefKey] = useState('');
  const [newPrefValue, setNewPrefValue] = useState('');
  const [newNoteTitle, setNewNoteTitle] = useState('');
  const [newNoteContent, setNewNoteContent] = useState('');
  const [newNoteTags, setNewNoteTags] = useState('');

  // P3 审批表单 state
  const [promotingId, setPromotingId] = useState<string | null>(null);
  const [promoteQuality, setPromoteQuality] = useState<string>('B');
  const [promoteTags, setPromoteTags] = useState<string>('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    Promise.all([fetchPreferences(), fetchHealth()]).then(() => fetchNotes());
  }, [fetchPreferences, fetchNotes, fetchHealth]);

  const handlePromote = async (id: string) => {
    setSubmitting(true);
    const vmId = await promoteNote(id, promoteQuality, promoteTags);
    setSubmitting(false);
    if (vmId) {
      setPromotingId(null);
      setPromoteQuality('B');
      setPromoteTags('');
    }
  };

  const cancelPromote = () => {
    setPromotingId(null);
    setPromoteQuality('B');
    setPromoteTags('');
  };

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">用户层记忆</h1>
        <p className="text-xs text-slate-500">用户偏好 / 笔记（与平台 VM 物理隔离） · P3 沉淀审批流</p>
      </div>
      <MemoryTabNav />

      {degraded && (
        <V3Card padding="sm" className="border-amber-500/40 bg-amber-900/10">
          <div className="flex items-center gap-2 text-xs text-amber-300">
            <span>⚠</span>
            <span>用户层后端降级 — 检查 /api/user-memory/health</span>
          </div>
        </V3Card>
      )}

      {/* 健康状态 + 物理隔离 */}
      <V3Card title="物理隔离验证" padding="sm">
        <div className="grid grid-cols-4 gap-3 text-center text-[10px]">
          <div>
            <p className="text-slate-500">状态</p>
            <p className={`font-semibold ${health?.status === 'healthy' ? 'text-emerald-400' : 'text-rose-400'}`}>
              {health?.status ?? '-'}
            </p>
          </div>
          <div>
            <p className="text-slate-500">物理隔离</p>
            <p className={`font-semibold ${health?.physical_isolation ? 'text-emerald-400' : 'text-rose-400'}`}>
              {health?.physical_isolation ? '✓' : '✗'}
            </p>
          </div>
          <div>
            <p className="text-slate-500">偏好数</p>
            <p className="font-semibold text-blue-400">{health?.preferences_count ?? '-'}</p>
          </div>
          <div>
            <p className="text-slate-500">笔记数</p>
            <p className="font-semibold text-purple-400">{health?.notes_count ?? '-'}</p>
          </div>
        </div>
        {health?.vm_leak_count === 0 && (
          <p className="mt-2 text-[10px] text-emerald-500">✓ 物理隔离正常：user_memory.db 内无 VM- 前缀记录</p>
        )}
      </V3Card>

      {/* 用户偏好 */}
      <V3Card title={`用户偏好（${preferences.length}）`} padding="sm">
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            placeholder="key（如 risk_tolerance）"
            value={newPrefKey}
            onChange={(e) => setNewPrefKey(e.target.value)}
            className="flex-1 px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
          />
          <input
            type="text"
            placeholder="value"
            value={newPrefValue}
            onChange={(e) => setNewPrefValue(e.target.value)}
            className="flex-1 px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
          />
          <button
            onClick={async () => {
              if (newPrefKey) {
                await setPreference(newPrefKey, newPrefValue);
                setNewPrefKey('');
                setNewPrefValue('');
              }
            }}
            className="px-3 py-1 text-xs rounded bg-blue-600/30 hover:bg-blue-600/50 text-blue-200"
          >
            保存
          </button>
        </div>
        {preferences.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-4">暂无偏好</p>
        ) : (
          <div className="space-y-1">
            {preferences.map(p => (
              <div key={p.pref_key} className="flex items-center justify-between p-2 rounded bg-slate-900/30 border border-slate-700/20">
                <div>
                  <span className="text-xs font-medium text-slate-200">{p.pref_key}</span>
                  <span className="ml-2 text-xs text-slate-400">= {p.pref_value}</span>
                </div>
                <span className="text-[9px] text-slate-600">{new Date(p.updated_at * 1000).toLocaleString()}</span>
              </div>
            ))}
          </div>
        )}
      </V3Card>

      {/* 用户笔记 + P3 沉淀审批流 */}
      <V3Card title={`用户笔记（${notes.length}）· P3 沉淀审批流`} padding="sm">
        <div className="space-y-2 mb-3">
          <input
            type="text"
            placeholder="标题"
            value={newNoteTitle}
            onChange={(e) => setNewNoteTitle(e.target.value)}
            className="w-full px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
          />
          <textarea
            placeholder="内容（用户经验/操作流程/环境事实）"
            value={newNoteContent}
            onChange={(e) => setNewNoteContent(e.target.value)}
            rows={3}
            className="w-full px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
          />
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="tags（逗号分隔）"
              value={newNoteTags}
              onChange={(e) => setNewNoteTags(e.target.value)}
              className="flex-1 px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
            />
            <button
              onClick={async () => {
                if (newNoteContent) {
                  await createNote(newNoteTitle, newNoteContent, newNoteTags);
                  setNewNoteTitle('');
                  setNewNoteContent('');
                  setNewNoteTags('');
                }
              }}
              className="px-3 py-1 text-xs rounded bg-purple-600/30 hover:bg-purple-600/50 text-purple-200"
            >
              添加
            </button>
          </div>
        </div>
        {notes.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-4">暂无笔记</p>
        ) : (
          <div className="space-y-1.5 max-h-[500px] overflow-y-auto">
            {notes.map(n => (
              <div key={n.id} className="p-2 rounded bg-slate-900/30 border border-slate-700/20">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-slate-200">{n.title || '(无标题)'}</p>
                    <p className="text-[10px] text-slate-400 line-clamp-2 mt-0.5">{n.content}</p>
                    {n.tags && (
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {n.tags.split(',').filter(Boolean).map(t => (
                          <span key={t} className="text-[9px] text-slate-500">#{t.trim()}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    {n.promoted_to ? (
                      <V3Badge variant="success" label={`已沉淀 ${n.promoted_to.slice(0, 12)}`} />
                    ) : (
                      <button
                        onClick={() => setPromotingId(n.id === promotingId ? null : n.id)}
                        className="text-[9px] px-2 py-0.5 rounded bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300"
                      >
                        沉淀为平台经验
                      </button>
                    )}
                    <button
                      onClick={() => n.id && deleteNote(n.id)}
                      className="text-[9px] text-rose-400 hover:text-rose-300"
                    >
                      删除
                    </button>
                  </div>
                </div>
                {/* P3 审批表单 */}
                {promotingId === n.id && !n.promoted_to && (
                  <div className="mt-2 p-2 rounded bg-slate-800/50 border border-emerald-700/30 space-y-2">
                    <p className="text-[10px] text-emerald-300">沉淀审批：将此笔记写入认知系统 VM-*（原笔记保留不删除）</p>
                    <div className="flex gap-2">
                      <select
                        value={promoteQuality}
                        onChange={(e) => setPromoteQuality(e.target.value)}
                        className="px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
                      >
                        {QUALITY_OPTIONS.map(q => (
                          <option key={q} value={q}>{QUALITY_HINT[q]}</option>
                        ))}
                      </select>
                      <input
                        type="text"
                        placeholder="tags (逗号分隔, 如: 用户决策,偏好,经验)"
                        value={promoteTags}
                        onChange={(e) => setPromoteTags(e.target.value)}
                        className="flex-1 px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-200"
                      />
                    </div>
                    <div className="flex gap-2 justify-end">
                      <button
                        onClick={cancelPromote}
                        disabled={submitting}
                        className="text-[10px] px-2 py-0.5 rounded bg-slate-700/50 hover:bg-slate-700 text-slate-300 disabled:opacity-50"
                      >
                        取消
                      </button>
                      <button
                        onClick={() => n.id && handlePromote(n.id)}
                        disabled={submitting}
                        className="text-[10px] px-2 py-0.5 rounded bg-emerald-600/30 hover:bg-emerald-600/50 text-emerald-200 disabled:opacity-50"
                      >
                        {submitting ? '提交中…' : '确认沉淀'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </V3Card>
    </div>
  );
}
