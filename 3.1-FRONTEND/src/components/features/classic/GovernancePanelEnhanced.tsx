'use client';

import { useState, useEffect, useCallback } from 'react';
import { V3Card } from '@/components';
import { useClassicStore, type ClassicPhase } from '@/stores';
import { ClassicPhasePanel } from '@/components/features/classic/ClassicPhasePanel';
import { M27_API } from '@/lib/module-api-client';

const C0_C8: { id: ClassicPhase; label: string }[] = [
  { id: 'C0', label: 'C0 环境扫描' },
  { id: 'C1', label: 'C1 品种筛选' },
  { id: 'C2', label: 'C2 信号识别' },
  { id: 'C3', label: 'C3 回测验证' },
  { id: 'C4', label: 'C4 风险评估' },
  { id: 'C5', label: 'C5 参数优化' },
  { id: 'C6', label: 'C6 计划生成' },
  { id: 'C7', label: 'C7 执行监控' },
  { id: 'C8', label: 'C8 绩效归因' },
];

export function GovernancePanelEnhanced() {
  const { activePhase, setActivePhase } = useClassicStore();
  const [health, setHealth] = useState<any>(null);
  const [subView, setSubView] = useState<'pipeline' | 'changeset' | 'approval' | 'audit' | 'gate'>('pipeline');
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [approvals, setApprovals] = useState<any[]>([]);
  const [auditEvents, setAuditEvents] = useState<any[]>([]);
  const [auditVerify, setAuditVerify] = useState<any>(null);
  const [gateResult, setGateResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  // 流水线创建
  const [strategyId, setStrategyId] = useState('');
  const [creating, setCreating] = useState(false);

  // 变更包草稿
  const [draftData, setDraftData] = useState('');
  const [draftResult, setDraftResult] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [pl, ap, au] = await Promise.all([
      M27_API.pipelineList(),
      M27_API.approvalList().catch(() => ({ ok: false })),
      M27_API.auditQuery(),
    ]);
    setPipelines(Array.isArray(pl) ? pl : (pl?.pipelines || pl?.items || []));
    const apSafe = ap as any;
    setApprovals(Array.isArray(ap) ? ap : (apSafe?.approvals || apSafe?.items || []));
    setAuditEvents(Array.isArray(au) ? au : (au?.events || au?.items || []));
    setLoading(false);
  }, []);

  useEffect(() => {
    M27_API.health().then(setHealth);
    load();
  }, [load]);

  const createPipeline = async () => {
    if (!strategyId.trim()) return;
    setCreating(true);
    await M27_API.pipelineCreate(strategyId);
    setStrategyId('');
    setCreating(false);
    load();
  };

  const createDraft = async () => {
    if (!draftData.trim()) return;
    let parsed: Record<string, any>;
    try { parsed = JSON.parse(draftData); } catch { parsed = { raw: draftData }; }
    const res = await M27_API.changesetDraft(parsed);
    setDraftResult(res);
  };

  const runGateEvaluate = async () => {
    const res = await M27_API.gateEvaluate({ strategy_id: strategyId || 'test', checks: ['backtest', 'risk', 'quality'] });
    setGateResult(res);
  };

  const verifyAudit = async () => {
    const res = await M27_API.auditVerify();
    setAuditVerify(res);
  };

  return (
    <V3Card title="治理审批系统" badge="M27" padding="lg"
      actions={<span className={`text-[10px] px-1.5 py-0.5 rounded-full ${health?.ok ? 'bg-emerald-600/20 text-emerald-400' : 'bg-rose-600/20 text-rose-400'}`}>
        {health?.ok ? 'ONLINE' : 'OFFLINE'}
      </span>}
    >
      <div className="space-y-4">
        <p className="text-xs text-slate-500">C0-C8 流水线 + 变更包 + 审批 + 审计链</p>

        {/* C0-C8 阶段条 */}
        <div className="flex items-center gap-1 p-2 rounded-xl bg-slate-900/50 border border-slate-700/30 flex-wrap">
          {C0_C8.map((phase, i) => {
            const isActive = activePhase === phase.id;
            return (
              <div key={phase.id} className="flex items-center gap-1">
                <button onClick={() => setActivePhase(phase.id)}
                  className={`px-2 py-1 rounded-full text-[10px] font-medium transition-colors ${
                    isActive ? 'bg-emerald-600/20 text-emerald-400 border border-emerald-500/30'
                    : 'bg-slate-800 text-slate-400 border border-transparent hover:text-slate-300'
                  }`}>
                  {phase.label}
                </button>
                {i < C0_C8.length - 1 && <span className="text-slate-700 text-[10px]">→</span>}
              </div>
            );
          })}
        </div>

        <ClassicPhasePanel />

        {/* 子视图切换 */}
        <div className="flex gap-1 p-1 rounded-lg bg-slate-900/50 border border-slate-700/30 overflow-x-auto">
          {[
            { id: 'pipeline' as const, label: '流水线' },
            { id: 'changeset' as const, label: '变更包' },
            { id: 'approval' as const, label: '审批' },
            { id: 'audit' as const, label: '审计' },
            { id: 'gate' as const, label: 'Gate评估' },
          ].map(v => (
            <button key={v.id} onClick={() => setSubView(v.id)}
              className={`flex-shrink-0 px-2.5 py-1 rounded text-[10px] font-medium ${subView === v.id ? 'bg-emerald-600/20 text-emerald-400' : 'text-slate-500'}`}>
              {v.label}
            </button>
          ))}
        </div>

        {loading && subView !== 'changeset' && subView !== 'gate' ? (
          <div className="text-center py-4 text-xs text-slate-500">加载中...</div>
        ) : subView === 'pipeline' ? (
          <div className="space-y-3">
            <div className="flex gap-2">
              <input value={strategyId} onChange={e => setStrategyId(e.target.value)}
                placeholder="策略ID..."
                className="flex-1 px-2.5 py-1.5 rounded-lg bg-slate-900/50 border border-slate-700/50 text-xs text-slate-300 placeholder:text-slate-600 focus:outline-none focus:border-emerald-500/50"
              />
              <button onClick={createPipeline} disabled={creating || !strategyId.trim()}
                className="px-3 py-1.5 rounded-lg bg-emerald-600/20 border border-emerald-500/30 text-xs text-emerald-300 hover:bg-emerald-600/30 disabled:opacity-40">
                {creating ? '创建中...' : '创建流水线'}
              </button>
            </div>
            {pipelines.length === 0 ? (
              <div className="text-center py-3 text-xs text-slate-600">暂无流水线</div>
            ) : (
              <div className="space-y-1.5 max-h-40 overflow-y-auto">
                {pipelines.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-slate-900/30 border border-slate-700/20 text-xs">
                    <span className="text-slate-300 font-mono truncate">{p.trace_id || p.id || '?'}</span>
                    <span className="text-[10px] text-slate-500 ml-2">{p.current_stage || p.stage || p.status || '-'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : subView === 'changeset' ? (
          <div className="space-y-2">
            <textarea value={draftData} onChange={e => setDraftData(e.target.value)}
              placeholder='输入变更包JSON...'
              className="w-full px-2.5 py-1.5 rounded-lg bg-slate-900/50 border border-slate-700/50 text-xs text-slate-300 placeholder:text-slate-600 focus:outline-none focus:border-emerald-500/50 font-mono"
              rows={3}
            />
            <button onClick={createDraft} disabled={!draftData.trim()}
              className="px-3 py-1.5 rounded-lg bg-emerald-600/20 border border-emerald-500/30 text-xs text-emerald-300 hover:bg-emerald-600/30 disabled:opacity-40">
              创建草稿
            </button>
            {draftResult && (
              <pre className="text-[10px] text-slate-400 font-mono overflow-auto max-h-30 p-2 rounded bg-slate-900/50 border border-slate-700/30">
                {JSON.stringify(draftResult, null, 2)}
              </pre>
            )}
          </div>
        ) : subView === 'approval' ? (
          <div className="space-y-2">
            {approvals.length === 0 ? (
              <div className="text-center py-3 text-xs text-slate-600">暂无审批请求</div>
            ) : (
              <div className="space-y-1.5">
                {approvals.map((a, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-slate-900/30 border border-slate-700/20 text-xs">
                    <span className="text-slate-300 font-mono">{a.approval_id || a.id || '?'}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                      a.status === 'approved' ? 'bg-emerald-600/20 text-emerald-400' :
                      a.status === 'rejected' ? 'bg-rose-600/20 text-rose-400' :
                      'bg-amber-600/20 text-amber-400'
                    }`}>{a.status || 'pending'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : subView === 'audit' ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">审计事件 ({auditEvents.length})</span>
              <button onClick={verifyAudit} className="text-[10px] text-emerald-400 hover:text-emerald-300">
                验证哈希链
              </button>
            </div>
            {auditVerify && (
              <div className={`p-2 rounded-lg border text-xs ${
                auditVerify.ok ? 'bg-emerald-600/10 border-emerald-500/30 text-emerald-300' : 'bg-rose-600/10 border-rose-500/30 text-rose-300'
              }`}>
                {auditVerify.ok ? '✓ 链完整' : '✗ 链断裂'} (total: {auditVerify.total}, verified: {auditVerify.verified})
              </div>
            )}
            <div className="space-y-1 max-h-30 overflow-y-auto">
              {auditEvents.map((e, i) => (
                <div key={i} className="flex items-center justify-between p-1.5 rounded bg-slate-900/30 border border-slate-700/20 text-[10px]">
                  <span className="text-slate-400 truncate">{e.event_type || e.type || '?'}</span>
                  <span className="text-slate-600 font-mono ml-2">{e.hash ? e.hash.slice(0, 8) : '-'}</span>
                </div>
              ))}
            </div>
          </div>
        ) : subView === 'gate' ? (
          <div className="space-y-2">
            <p className="text-xs text-slate-400">Gate 评估 — 对策略执行准入检查（回测/风险/质量）</p>
            <button onClick={runGateEvaluate}
              className="px-3 py-1.5 rounded-lg bg-emerald-600/20 border border-emerald-500/30 text-xs text-emerald-300 hover:bg-emerald-600/30">
              执行 Gate 评估
            </button>
            {gateResult && (
              <pre className="text-[10px] text-slate-400 font-mono overflow-auto max-h-30 p-2 rounded bg-slate-900/50 border border-slate-700/30">
                {JSON.stringify(gateResult, null, 2)}
              </pre>
            )}
          </div>
        ) : null}
      </div>
    </V3Card>
  );
}
