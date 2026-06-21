import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, Circle, XCircle } from 'lucide-react';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
import { fetchAgentChangesetDraftGet, fetchApprovalBriefGet, fetchApprovalBriefHealth, fetchApprovalDetail, fetchApprovalsHistory, fetchApprovalsSummary, generateApprovalBrief, hasOperatorToken, logApprovalDecision } from '../lib/api';
import { toErrorReasonZh } from '../lib/errorLabels';

type ApprovalDecision = 'approved' | 'reject';

type Recommendation = {
  level: 'approve' | 'warn' | 'reject';
  reasons: string[];
  blockers: string[];
};

const _fmtTs = (v?: number | null) => {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n) || n <= 0) return '-';
  const ms = n < 1e11 ? n * 1000 : n;
  return new Date(ms).toLocaleString();
};

const _jsonParseMaybe = (s: unknown): unknown => {
  const raw = String(s ?? '').trim();
  if (!raw) return null;
  if (!(raw.startsWith('{') || raw.startsWith('['))) return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
};

const _asRecord = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return {};
  return v as Record<string, unknown>;
};

const _asArray = <T,>(v: unknown): T[] => {
  if (!Array.isArray(v)) return [];
  return v as T[];
};

const _recommend = (approval: Record<string, unknown> | null | undefined, draft: Record<string, unknown> | null | undefined): Recommendation => {
  const ap = _asRecord(approval);
  const dr = _asRecord(draft);

  const cbd = _asRecord(dr.change_bundle_draft);
  const changeset = _asRecord(dr.changeset);
  const governance = _asRecord(cbd.governance);
  const baselineJudge = _asRecord(governance.baseline_judge);

  const docRefs = _asArray<Record<string, unknown>>(dr.doc_refs);
  const rollbackPointId = String(changeset.rollback_point_id ?? cbd.rollback_point_id ?? '').trim();
  const gate = _asRecord(dr.gate_result);
  const gatePass = Boolean(gate.pass ?? (String(gate.decision ?? '').toLowerCase() === 'pass'));

  const blockers: string[] = [];
  if (!docRefs.length) blockers.push('缺少 doc_refs（无法对齐 SSoT）');
  if (!rollbackPointId) blockers.push('缺少 rollback_point_id（不可回滚）');
  if (!gatePass) blockers.push('沙箱门禁未通过（gate_result=fail）');

  const tags = _asArray<string>(cbd.change_tags).map((x) => String(x || '').trim()).filter(Boolean);
  const baselineDecision = String(baselineJudge.decision ?? '').trim().toLowerCase();
  if (baselineDecision === 'hard_reject') blockers.push('基线对比触发 hard_reject');

  const reasons: string[] = [];
  if (tags.includes('tighten')) reasons.push('变更方向为 tighten（降风险/收敛暴露）');
  if (tags.includes('loosen')) reasons.push('变更方向为 loosen（可能扩大暴露）');
  if (tags.includes('exposure_increase')) reasons.push('检测到 exposure_increase（仓位/杠杆/名义金额上调）');
  if (baselineDecision === 'soft_warn') reasons.push('基线对比为 soft_warn（需要谨慎灰度/补证据）');

  const action = String(ap.action ?? changeset.action ?? '').trim();
  if (action) reasons.push(`action=${action}`);

  if (blockers.length) return { level: 'reject', reasons, blockers };
  if (tags.includes('exposure_increase') || tags.includes('loosen') || baselineDecision === 'soft_warn') return { level: 'warn', reasons, blockers };
  if (tags.includes('tighten')) return { level: 'approve', reasons, blockers };
  return { level: 'warn', reasons: ['未能归类为 tighten-only，默认建议谨慎灰度'], blockers };
};

const _briefRecommend = (brief: Record<string, unknown> | null | undefined): Recommendation | null => {
  const b = _asRecord(brief);
  const rec = _asRecord(b.recommendation);
  const decision = String(rec.decision ?? '').trim().toLowerCase();
  const level: Recommendation['level'] = decision === 'pass' ? 'approve' : decision === 'fail' ? 'reject' : decision === 'warn' ? 'warn' : 'warn';
  const blockers = _asArray<string>(rec.blockers).map((x) => String(x || '').trim()).filter(Boolean);
  const reasons = _asArray<string>(rec.reasons).map((x) => String(x || '').trim()).filter(Boolean);
  if (!decision && !blockers.length && !reasons.length) return null;
  return { level, blockers, reasons };
};

const _decisionBadge = (level: Recommendation['level']) => {
  if (level === 'approve') return <Badge className="bg-emerald-600 hover:bg-emerald-600">建议通过</Badge>;
  if (level === 'reject') return <Badge className="bg-rose-600 hover:bg-rose-600">建议拒绝</Badge>;
  return <Badge className="bg-amber-600 hover:bg-amber-600">建议谨慎</Badge>;
};

const _decisionIcon = (level: Recommendation['level']) => {
  if (level === 'approve') return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
  if (level === 'reject') return <XCircle className="h-4 w-4 text-rose-600" />;
  return <AlertTriangle className="h-4 w-4 text-amber-600" />;
};

export const ApprovalReviewPage: React.FC = () => {
  const nav = useNavigate();
  const params = useParams();
  const queryClient = useQueryClient();
  const approvalId = String(params.id ?? '').trim();

  const [reason, setReason] = useState<string>('');

  const briefHealthQuery = useQuery({
    queryKey: ['approvals', 'brief', 'health'],
    queryFn: () => fetchApprovalBriefHealth(),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
  });
  const briefHealth = useMemo(() => {
    const d = briefHealthQuery.data as Record<string, unknown> | undefined;
    return _asRecord(d);
  }, [briefHealthQuery.data]);
  const briefSelectedTier = String(briefHealth.selected_tier ?? '').trim().toLowerCase() || 'rule';
  const briefTiers = useMemo(() => _asRecord(briefHealth.tiers), [briefHealth.tiers]);
  const briefRemote = useMemo(() => _asRecord(briefTiers.remote), [briefTiers.remote]);
  const briefLocal = useMemo(() => _asRecord(briefTiers.local), [briefTiers.local]);
  const briefOrder = useMemo(() => _asArray<string>(briefHealth.order).map((x) => String(x || '').trim()).filter(Boolean), [briefHealth.order]);
  const remoteTip = useMemo(() => {
    const provider = String(briefRemote.provider ?? '').trim() || '-';
    const model = String(briefRemote.model ?? '').trim() || '-';
    const reason = String(briefRemote.reason ?? '').trim() || 'unknown';
    const reasonCn = toErrorReasonZh(reason);
    const available = Boolean(briefRemote.available);
    return `remote | provider=${provider} | model=${model} | status=${available ? 'up' : 'down'} | reason_cn=${reasonCn} | reason=${reason}`;
  }, [briefRemote.available, briefRemote.model, briefRemote.provider, briefRemote.reason]);
  const localTip = useMemo(() => {
    const provider = String(briefLocal.provider ?? '').trim() || '-';
    const model = String(briefLocal.model ?? '').trim() || '-';
    const reason = String(briefLocal.reason ?? '').trim() || 'unknown';
    const reasonCn = toErrorReasonZh(reason);
    const available = Boolean(briefLocal.available);
    return `local | provider=${provider} | model=${model} | status=${available ? 'up' : 'down'} | reason_cn=${reasonCn} | reason=${reason}`;
  }, [briefLocal.available, briefLocal.model, briefLocal.provider, briefLocal.reason]);
  const tierTip = useMemo(() => {
    const order = briefOrder.length ? briefOrder.join(' -> ') : 'remote -> local -> rule';
    return `selected=${briefSelectedTier} | order=${order}`;
  }, [briefOrder, briefSelectedTier]);

  const approvalsSummaryQuery = useQuery({
    queryKey: ['approvals', 'summary', { max_lines: 3000, max_bytes: 8_000_000 }],
    queryFn: () => fetchApprovalsSummary({ max_lines: 3000, max_bytes: 8_000_000 }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
  });

  const pendingItems = useMemo(() => {
    const d = approvalsSummaryQuery.data as { pending?: unknown } | undefined;
    const pending = _asArray<Record<string, unknown>>(d?.pending);
    return pending.map((it) => ({
      id: String(it.id ?? '').trim(),
      trace_id: String(it.trace_id ?? '').trim(),
      action: String(it.action ?? '').trim(),
      reason: String(it.reason ?? '').trim(),
      ts: Number(it.ts ?? 0) || 0,
      expires_at: (it.expires_at == null ? null : Number(it.expires_at)) || null,
      ttl_ms: (it.ttl_ms == null ? null : Number(it.ttl_ms)) || null,
      is_explore: Boolean(it.is_explore ?? false),
    })).filter((x) => x.id);
  }, [approvalsSummaryQuery.data]);

  const approvalsHistoryQuery = useQuery({
    queryKey: ['approvals', 'history', { limit: 50, offset: 0, days: 30 }],
    queryFn: () => fetchApprovalsHistory({ limit: 50, offset: 0, days: 30 }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });

  const historyItems = useMemo(() => {
    const d = approvalsHistoryQuery.data as { items?: unknown } | undefined;
    const items = _asArray<Record<string, unknown>>(d?.items);
    return items.map((it) => ({
      id: String(it.id ?? '').trim(),
      trace_id: String(it.trace_id ?? '').trim(),
      action: String(it.action ?? '').trim(),
      reason: String(it.reason ?? '').trim(),
      ts: Number(it.ts ?? 0) || 0,
      decision: String(it.decision ?? '').trim().toLowerCase(),
    })).filter((x) => x.id);
  }, [approvalsHistoryQuery.data]);

  const queueItems = useMemo(() => {
    if (pendingItems.length) return pendingItems;
    const pendingLike = historyItems.filter((x) => x.decision.startsWith('pending'));
    return pendingLike.length ? pendingLike : historyItems;
  }, [historyItems, pendingItems]);

  useEffect(() => {
    if (approvalId) return;
    if (!queueItems.length) return;
    nav(`/agent/approvals/${encodeURIComponent(queueItems[0].id)}`, { replace: true });
  }, [approvalId, nav, queueItems]);

  const approvalDetailQuery = useQuery({
    queryKey: ['approvals', 'detail', { id: approvalId }],
    queryFn: () => fetchApprovalDetail({ id: approvalId }),
    enabled: Boolean(approvalId),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
  });

  const approval = useMemo(() => {
    const d = approvalDetailQuery.data as { approval?: unknown } | undefined;
    return _asRecord(d?.approval);
  }, [approvalDetailQuery.data]);

  const approvalBriefQuery = useQuery({
    queryKey: ['approvals', 'brief', { id: approvalId }],
    queryFn: () => fetchApprovalBriefGet({ id: approvalId }),
    enabled: Boolean(approvalId),
    retry: false,
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
  });
  const approvalBrief = useMemo(() => {
    const d = approvalBriefQuery.data as { brief?: unknown } | undefined;
    return _asRecord(d?.brief);
  }, [approvalBriefQuery.data]);

  const draftId = String(approval.draft_id ?? '').trim();
  const draftQuery = useQuery({
    queryKey: ['agent', 'changeset', 'draft', { id: draftId }],
    queryFn: () => fetchAgentChangesetDraftGet({ id: draftId }),
    enabled: Boolean(draftId),
    refetchInterval: false,
    refetchOnWindowFocus: false,
  });

  const draftEntry = useMemo(() => {
    const d = draftQuery.data as { entry?: unknown } | undefined;
    return _asRecord(d?.entry);
  }, [draftQuery.data]);

  const draft = useMemo(() => {
    const d = _asRecord(draftEntry.draft);
    return d;
  }, [draftEntry.draft]);

  const cbd = useMemo(() => _asRecord(draft.change_bundle_draft), [draft.change_bundle_draft]);
  const changeset = useMemo(() => _asRecord(draft.changeset), [draft.changeset]);
  const configDiff = useMemo(() => {
    const cd = _asRecord(cbd.config_diff);
    return _asArray<Record<string, unknown>>(cd.changes);
  }, [cbd.config_diff]);
  const deltaMetrics = useMemo(() => _asRecord(cbd.delta_metrics), [cbd.delta_metrics]);
  const requiredGates = useMemo(() => _asRecord(cbd.required_gates), [cbd.required_gates]);
  const requiredGateItems = useMemo(() => _asArray<string>(requiredGates.items).map((x) => String(x || '').trim()).filter(Boolean), [requiredGates.items]);
  const requiredGateLevel = useMemo(() => (requiredGates.P3 ? 'P3' : '-'), [requiredGates.P3]);

  const recommendation = useMemo(() => _briefRecommend(approvalBrief) ?? _recommend(approval, draft), [approval, approvalBrief, draft]);

  const generateBriefMutation = useMutation({
    mutationFn: async (payload: { id: string; force?: boolean }) => await generateApprovalBrief(payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['approvals', 'brief'] });
    },
  });

  const doDecisionMutation = useMutation({
    mutationFn: async (payload: { id: string; decision: ApprovalDecision; reason?: string }) => {
      const trace_id = String(approval.trace_id ?? '').trim() || undefined;
      const action = (approval.action == null ? undefined : String(approval.action ?? '').trim()) || undefined;
      const baseline_version = (changeset.baseline_version == null ? undefined : String(changeset.baseline_version ?? '').trim()) || undefined;
      const gate_results = _asRecord(approval.gate_results);
      const evidence: Record<string, unknown> = {
        ui: { source: 'ApprovalReviewPage', draft_id: draftId || null, recommendation: recommendation.level },
        brief: {
          id: (approvalBrief.id == null ? null : String(approvalBrief.id)),
          idempotency_key: (approvalBrief.idempotency_key == null ? null : String(approvalBrief.idempotency_key)),
          decision: (String(_asRecord(_asRecord(approvalBrief).recommendation).decision ?? '').trim() || null),
        },
        change_id: (cbd.change_id == null ? null : String(cbd.change_id)),
        change_tags: _asArray<string>(cbd.change_tags),
      };

      return await logApprovalDecision({
        id: payload.id,
        trace_id,
        approver: 'ui',
        decision: payload.decision,
        action,
        reason: payload.reason,
        baseline_version,
        gate_results,
        evidence,
        doc_refs: _asArray<Record<string, unknown>>(draft.doc_refs),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['approvals', 'summary'] });
      await queryClient.invalidateQueries({ queryKey: ['approvals', 'history'] });
      await queryClient.invalidateQueries({ queryKey: ['approvals', 'detail'] });
    },
  });

  const operatorOk = hasOperatorToken();

  const behaviorSummary = useMemo(() => _jsonParseMaybe(changeset.behavior_summary), [changeset.behavior_summary]);
  const objectiveProfile = String(changeset.objective_profile ?? '').trim();
  const label = String(changeset.label ?? '').trim();
  const purpose = String(changeset.reason ?? '').trim();

  const headerTitle = useMemo(() => {
    const strategyKey = String(changeset.strategy_key ?? '').trim();
    const action = String(approval.action ?? '').trim();
    if (strategyKey && action) return `${action} · ${strategyKey}`;
    return action || strategyKey || '草案审批';
  }, [approval.action, changeset.strategy_key]);

  const changeTags = useMemo(() => _asArray<string>(cbd.change_tags).map((x) => String(x || '').trim()).filter(Boolean), [cbd.change_tags]);
  const levelInfo = useMemo(() => _asRecord(changeset.level_info), [changeset.level_info]);
  const changeLevel = String(changeset.change_level ?? '').trim() || '-';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="text-2xl font-bold truncate">草案审批</div>
          <div className="text-sm text-slate-600 truncate">{headerTitle}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline" title={tierTip}>analyst tier={briefSelectedTier}</Badge>
            <Badge title={remoteTip} className={briefRemote.available ? 'bg-emerald-600 hover:bg-emerald-600' : 'bg-slate-500 hover:bg-slate-500'}>
              remote {briefRemote.available ? 'up' : 'down'} · {toErrorReasonZh(briefRemote.reason)}
            </Badge>
            <Badge title={localTip} className={briefLocal.available ? 'bg-emerald-600 hover:bg-emerald-600' : 'bg-slate-500 hover:bg-slate-500'}>
              local {briefLocal.available ? 'up' : 'down'} · {toErrorReasonZh(briefLocal.reason)}
            </Badge>
            {briefHealthQuery.isError ? <Badge className="bg-rose-600 hover:bg-rose-600">probe unavailable</Badge> : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">/agent/approvals</Badge>
          <Link to="/agent/ops">
            <Button variant="outline">回到运维</Button>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-4 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>待审批队列</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {approvalsSummaryQuery.isError ? (
                <div className="rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
                  审批摘要加载失败（可能是鉴权失败或后端不可达）。正在回退历史接口。
                </div>
              ) : null}
              {queueItems.length ? (
                <div className="space-y-2">
                  {queueItems.slice(0, 50).map((it) => {
                    const active = approvalId && it.id === approvalId;
                    return (
                      <Link key={it.id} to={`/agent/approvals/${encodeURIComponent(it.id)}`}>
                        <div className={active ? 'rounded border bg-slate-50 p-2' : 'rounded border bg-white p-2 hover:bg-slate-50'}>
                          <div className="flex items-center justify-between gap-2">
                            <div className="min-w-0">
                              <div className="text-sm font-semibold truncate">{it.action || 'approval'}</div>
                              <div className="text-xs text-slate-600 truncate">{it.reason || it.trace_id}</div>
                            </div>
                            <div className="text-right">
                              <div className="text-xs text-slate-500">{_fmtTs(it.ts)}</div>
                              {'ttl_ms' in it && (it as Record<string, unknown>).ttl_ms != null ? <div className="text-xs text-slate-500">{Math.max(0, Math.floor(Number((it as Record<string, unknown>).ttl_ms ?? 0) / 60000))}m TTL</div> : null}
                            </div>
                          </div>
                        </div>
                      </Link>
                    );
                  })}
                </div>
              ) : (
                <div className="text-sm text-slate-600">暂无审批数据（请检查 operator token 与后端连接）</div>
              )}
              <div className="pt-2">
                <Button variant="outline" className="w-full" onClick={() => approvalsSummaryQuery.refetch()} disabled={approvalsSummaryQuery.isFetching}>
                  刷新
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-8 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>分析简报</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {!approvalId ? (
                <div className="text-sm text-slate-600">请选择一个待审批项</div>
              ) : approvalDetailQuery.isLoading ? (
                <div className="text-sm text-slate-600">加载审批详情中…</div>
              ) : approvalDetailQuery.isError ? (
                <div className="text-sm text-rose-700">审批详情加载失败</div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    {_decisionIcon(recommendation.level)}
                    {_decisionBadge(recommendation.level)}
                    <Badge variant="outline">approval_id={approvalId}</Badge>
                    {draftId ? <Badge variant="outline">draft_id={draftId}</Badge> : <Badge className="bg-amber-600 hover:bg-amber-600">缺少 draft_id</Badge>}
                    <Badge variant="outline">level={changeLevel}</Badge>
                    {changeTags.length ? changeTags.map((t) => <Badge key={t} variant="outline">{t}</Badge>) : <Badge variant="outline">neutral</Badge>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => generateBriefMutation.mutate({ id: approvalId, force: true })}
                      disabled={!approvalId || generateBriefMutation.isPending}
                    >
                      生成/刷新简报
                    </Button>
                    {approvalBrief.id ? <Badge variant="outline">brief_id={String(approvalBrief.id)}</Badge> : <Badge variant="outline">brief=none</Badge>}
                    {approvalBrief.idempotency_key ? <Badge variant="outline">idem={String(approvalBrief.idempotency_key).slice(0, 16)}</Badge> : null}
                    {generateBriefMutation.isError ? <Badge className="bg-rose-600 hover:bg-rose-600">简报生成失败</Badge> : null}
                    {generateBriefMutation.isSuccess ? <Badge className="bg-emerald-600 hover:bg-emerald-600">简报已落库</Badge> : null}
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="rounded border bg-white p-3">
                      <div className="text-xs text-slate-500">目的</div>
                      <div className="text-sm font-semibold">{purpose || '-'}</div>
                      {label ? <div className="mt-1 text-xs text-slate-600">label: {label}</div> : null}
                      {objectiveProfile ? <div className="mt-1 text-xs text-slate-600">profile: {objectiveProfile}</div> : null}
                    </div>
                    <div className="rounded border bg-white p-3">
                      <div className="text-xs text-slate-500">变更与回滚</div>
                      <div className="text-sm font-semibold truncate">rollback_point_id: {String(changeset.rollback_point_id ?? '-')}</div>
                      <div className="mt-1 text-xs text-slate-600">expires_at: {_fmtTs(Number(changeset.expires_at ?? 0) || null)}</div>
                      <div className="mt-1 text-xs text-slate-600">created_at: {_fmtTs(Number(approval.ts ?? 0) || null)}</div>
                    </div>
                  </div>

                  <div className="rounded border bg-white p-3">
                    <div className="text-xs text-slate-500">参数变更</div>
                    {configDiff.length ? (
                      <div className="mt-2 space-y-2">
                        {configDiff.slice(0, 60).map((c, idx) => {
                          const key = String(c.key ?? '').trim() || `#${idx + 1}`;
                          const fromV = c.from;
                          const toV = c.to;
                          const dir = String(c.direction ?? '').trim() || '-';
                          const dirBadge =
                            dir === 'tighten' ? (
                              <Badge className="bg-emerald-600 hover:bg-emerald-600">tighten</Badge>
                            ) : dir === 'loosen' ? (
                              <Badge className="bg-rose-600 hover:bg-rose-600">loosen</Badge>
                            ) : (
                              <Badge variant="outline">{dir}</Badge>
                            );
                          return (
                            <div key={`${key}-${idx}`} className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <div className="text-sm font-semibold truncate">{key}</div>
                                <div className="text-xs text-slate-600 break-all">
                                  {String(fromV)} → {String(toV)}
                                </div>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                {dirBadge}
                                <Badge variant="outline" className="max-w-[220px] truncate">{String(c.allowlist_ref ?? '')}</Badge>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="mt-2 text-sm text-slate-600">未发现 config_diff</div>
                    )}
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="rounded border bg-white p-3">
                      <div className="text-xs text-slate-500">影响（delta_metrics）</div>
                      {Object.keys(deltaMetrics).length ? (
                        <div className="mt-2 space-y-1">
                          {Object.entries(deltaMetrics).slice(0, 20).map(([k, vv]) => {
                            const d = _asRecord(vv);
                            const base = d.baseline;
                            const cand = d.candidate;
                            const delta = d.delta;
                            const color = typeof delta === 'number' ? (delta > 0 ? 'text-emerald-700' : delta < 0 ? 'text-rose-700' : 'text-slate-700') : 'text-slate-700';
                            return (
                              <div key={k} className="flex items-center justify-between gap-2 text-xs">
                                <span className="truncate">{k}</span>
                                <span className={`shrink-0 ${color}`}>{String(base)} → {String(cand)} ({String(delta)})</span>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="mt-2 text-sm text-slate-600">缺少 baseline 或未计算 delta</div>
                      )}
                    </div>
                    <div className="rounded border bg-white p-3">
                      <div className="text-xs text-slate-500">稳健性与门禁</div>
                      <div className="mt-2 space-y-1 text-xs text-slate-700">
                        <div className="flex items-center justify-between gap-2">
                          <span>gate_pass</span>
                          <span>{String((_asRecord(draft.gate_result).pass ?? _asRecord(draft.gate_result).decision) ?? '-')}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span>required_gates</span>
                          <span>{String(requiredGateItems.length)}</span>
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <span>risk_level</span>
                          <span>{requiredGateLevel}</span>
                        </div>
                      </div>
                      <div className="mt-2">
                        <Button variant="outline" size="sm" onClick={() => draftQuery.refetch()} disabled={!draftId || draftQuery.isFetching}>
                          刷新草案
                        </Button>
                      </div>
                    </div>
                  </div>

                  {behaviorSummary ? (
                    <div className="rounded border bg-white p-3">
                      <div className="text-xs text-slate-500">行为摘要（behavior_summary）</div>
                      <pre className="mt-2 text-xs whitespace-pre-wrap break-words text-slate-700">{JSON.stringify(behaviorSummary, null, 2)}</pre>
                    </div>
                  ) : null}

                  <div className="rounded border bg-white p-3">
                    <div className="text-xs text-slate-500">建议与理由</div>
                    <div className="mt-2 space-y-2">
                      {recommendation.blockers.length ? (
                        <div className="space-y-1">
                          {recommendation.blockers.map((b) => (
                            <div key={b} className="flex items-center gap-2 text-sm text-rose-700">
                              <XCircle className="h-4 w-4" />
                              <span>{b}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 text-sm text-slate-700">
                          <Circle className="h-4 w-4 text-slate-400" />
                          <span>硬门禁通过</span>
                        </div>
                      )}
                      {recommendation.reasons.length ? (
                        <div className="space-y-1">
                          {recommendation.reasons.map((r) => (
                            <div key={r} className="flex items-center gap-2 text-sm text-slate-700">
                              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                              <span>{r}</span>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="rounded border bg-white p-3 space-y-3">
                    <div className="text-xs text-slate-500">审批操作</div>
                    <Input value={reason} onChange={(e) => setReason(String(e.target.value ?? ''))} placeholder="审批原因（可选）" />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        className="gap-2"
                        onClick={() => doDecisionMutation.mutate({ id: approvalId, decision: 'approved', reason: reason.trim() || undefined })}
                        disabled={!operatorOk || doDecisionMutation.isPending}
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        同意
                      </Button>
                      <Button
                        variant="destructive"
                        className="gap-2"
                        onClick={() => doDecisionMutation.mutate({ id: approvalId, decision: 'reject', reason: reason.trim() || undefined })}
                        disabled={!operatorOk || doDecisionMutation.isPending}
                      >
                        <XCircle className="h-4 w-4" />
                        拒绝
                      </Button>
                      {!operatorOk ? <Badge className="bg-amber-600 hover:bg-amber-600">只读模式：需要配置 execute_token</Badge> : null}
                      {doDecisionMutation.isSuccess ? <Badge className="bg-emerald-600 hover:bg-emerald-600">已写入审批日志</Badge> : null}
                      {doDecisionMutation.isError ? <Badge className="bg-rose-600 hover:bg-rose-600">审批写入失败</Badge> : null}
                    </div>
                  </div>

                  <div className="rounded border bg-white p-3">
                    <div className="text-xs text-slate-500">附：变更级别信息</div>
                    <pre className="mt-2 text-xs whitespace-pre-wrap break-words text-slate-700">{JSON.stringify(levelInfo, null, 2)}</pre>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};
