import React, { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { applyGovernanceChangeset, authMe, executeAgentSkills, fetchAgentChangesetDraftGet, fetchAgentOutboxRead, fetchAgentPipelineArtifacts, fetchApprovalGet, fetchApprovalsSummary, fetchAutomationCardsState, fetchConfig, getUiEnv, hasOperatorToken, logApprovalDecision, runAutomationParamoptScenariosEnsure, runAutomationParamoptSmokeApply, runAutomationSupplyChain, runAutomationWeb3MarketDigest, setAutomationConfig, triggerAutomationParamoptExplore, updateConfig } from '../lib/api';
import type { AgentPipelineArtifactsResponse, AutomationCardStateV1, AutomationCardsStateResponse } from '../lib/api';

const _nowMs = () => Date.now();

const EXPLORE_WIDE_PRESET: Record<string, unknown> = {
  trade_whitelist_auto_enabled: true,
  trade_whitelist_auto_source: 'universe_scored_top',
  trade_whitelist_auto_max: 80,
  trade_whitelist_auto_require_alpha_pass: false,
  trade_whitelist_enabled: true,
  trade_whitelist_enforcement: 'hard',
  threshold_trend: 0.55,
  threshold_chop: 0.60,
  signals_dedup_ttl_sec: 900,
  signals_dedup_bucket_sec: 30,
  signals_pair_side_cooldown_sec: 60,
  signals_coin_side_cooldown_sec: 60,
  entry_inflight_cooldown_sec: 30,
  pc_hysteresis_delta: 0.005,
  max_open_trades: 10,
  max_orders_per_minute: 24,
  order_rate_window_sec: 30,
};

function _secToHuman(sec: number): string {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  if (s <= 0) return '-';
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d${h % 24}h`;
  if (h > 0) return `${h}h${m % 60}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function _msToAgo(ms: number): string {
  const x = Math.max(0, Math.floor(ms));
  const sec = Math.floor(x / 1000);
  const m = Math.floor(sec / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d${h % 24}h ago`;
  if (h > 0) return `${h}h${m % 60}m ago`;
  if (m > 0) return `${m}m ago`;
  return `${sec}s ago`;
}

function _msAgo(nowMs: number, v?: number | null): string {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n) || n <= 0) return '-';
  const ms = n < 1e11 ? n * 1000 : n;
  return _msToAgo(Math.max(0, nowMs - ms));
}

function _ttlText(ms?: number | null): string {
  const n = Number(ms ?? NaN);
  if (!Number.isFinite(n)) return '-';
  if (n <= 0) return '已过期';
  return _secToHuman(Math.floor(n / 1000));
}

function _statusBadgeVariant(st: string): 'secondary' | 'outline' | 'destructive' {
  if (st === 'ON' || st === 'RUNNING') return 'secondary';
  if (st === 'ERROR') return 'destructive';
  return 'outline';
}

function _stepBadgeVariant(st: string): 'secondary' | 'outline' | 'destructive' {
  if (st === 'DONE') return 'secondary';
  if (st === 'FAIL') return 'destructive';
  return 'outline';
}

type SystemMonitorReport = {
  ok?: boolean;
  ts?: number;
  trace_id?: string;
  pair?: string;
  strategy?: string;
  timerange?: string;
  summary?: {
    faq_hits?: string[];
    link_check_ok?: boolean | null;
    backtest_ok?: boolean | null;
    preauthorized_allowed?: boolean;
    changeset_draft_id?: string | null;
    approval_id?: string | null;
  };
  triage?: {
    faq_hits?: string[];
    preauthorized?: { allowed?: boolean } | null;
    proposed_config_patch?: Record<string, unknown> | null;
  } | null;
  backtest?: {
    ok?: boolean;
    result?: { ok?: boolean; metrics_summary?: Record<string, unknown> } | null;
  } | null;
  link_check?: { ok?: boolean } | null;
  changeset_draft?: { ok?: boolean } | null;
  auto_exec?: { ok?: boolean; apply?: Record<string, unknown> | null; error?: string } | null;
};

type RcaOutboxItem = {
  id?: string;
  trace_id?: string;
  ts?: number;
  event_type?: string;
  type?: string;
  severity?: string;
  result?: SystemMonitorReport;
};

const _CARD_META: Record<string, { title: string; desc: string }> = {
  gtw_global_workflow: { title: '全局交易工作流（GTW）', desc: '全局编排总开关：交易数据分析 + 宏观趋势分析 + 三路径编排（轮询/事件）' },
  shadow_switch: { title: '策略影子自动化许可开关', desc: '允许策略影子自动化运行 + 自动启动' },
  strategy_supply_chain: { title: '策略供应链', desc: '拉取→入库→沙箱评估→分档→审批' },
  strategy_shadow_loop: { title: '策略自动影子闭环', desc: '触发→候选→门禁→审批→执行/回滚' },
  paramopt_automation: { title: '贝叶斯参数优化自动化', desc: '亏损触发→寻优→验证→审批→应用/回滚' },
  twitter_delivery: { title: '推特自动发推状态', desc: '推送开关、队列与最近投递结果' },
  web3_market_digest: { title: 'Web3 行情汇总（Thread Digest）', desc: '定时轮询 Binance Web3 → 聚合 → LLM 生成线程 → outbox 入队' },
  other: { title: '系统监控与Bug修复', desc: '异常→RCA→沙箱验证→审批→受控修复/回滚' },
};

export const AutomationManagementPanel: React.FC = () => {
  const { module } = useParams();
  const nowMs = _nowMs();
  const [gtwShowRaw, setGtwShowRaw] = useState<boolean>(false);
  const [paramoptShowRaw, setParamoptShowRaw] = useState<boolean>(false);
  const [paramoptShowAllStages, setParamoptShowAllStages] = useState<boolean>(false);
  const [paramoptShowAllOps, setParamoptShowAllOps] = useState<boolean>(false);
  const [exploreApplyResult, setExploreApplyResult] = useState<string>('');
  const [paramoptScenarioEnsureShowRaw, setParamoptScenarioEnsureShowRaw] = useState<boolean>(false);
  const [paramoptSmokeApplyShowRaw, setParamoptSmokeApplyShowRaw] = useState<boolean>(false);
  const [pendingApprovalSelectedId, setPendingApprovalSelectedId] = useState<string>('');
  const [pendingApprovalActionResult, setPendingApprovalActionResult] = useState<string>('');

  const includeDetails = String(module || '').trim() === 'paramopt_automation';

  const cardsQuery = useQuery({
    queryKey: ['automation', 'cards', 'state', { details: includeDetails }],
    queryFn: async () => await fetchAutomationCardsState({ details: includeDetails }),
    refetchInterval: 8000,
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 4,
    retryDelay: (attemptIndex) => Math.min(15000, 800 * 2 ** attemptIndex),
  });

  const cardsResp = cardsQuery.data as AutomationCardsStateResponse | undefined;
  const cards = useMemo(() => (Array.isArray(cardsResp?.cards) ? cardsResp!.cards : []), [cardsResp]);

  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const authMeQuery = useQuery({
    queryKey: ['authMe'],
    queryFn: authMe,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const orderedCards: AutomationCardStateV1[] = useMemo(() => {
    const order = ['gtw_global_workflow', 'shadow_switch', 'strategy_supply_chain', 'strategy_shadow_loop', 'paramopt_automation', 'twitter_delivery', 'web3_market_digest', 'other'];
    const by = new Map(cards.map((c) => [String(c.card_id), c]));
    return order.map((k) => by.get(k)).filter((x): x is AutomationCardStateV1 => Boolean(x));
  }, [cards]);

  const selectedCard: AutomationCardStateV1 | null = useMemo(() => {
    const m = String(module || '').trim();
    if (!m) return null;
    return orderedCards.find((c) => String(c.card_id) === m) || null;
  }, [module, orderedCards]);

  const paramoptLatest = useMemo(() => {
    if (!selectedCard || String(selectedCard.card_id) !== 'paramopt_automation') return null;
    const details = (selectedCard.details && typeof selectedCard.details === 'object') ? (selectedCard.details as Record<string, unknown>) : {};
    const lastWrap = (details.last && typeof details.last === 'object') ? (details.last as Record<string, unknown>) : {};
    const lastOut = (lastWrap.out && typeof lastWrap.out === 'object') ? (lastWrap.out as Record<string, unknown>) : {};
    const stages = Array.isArray(lastOut.stages) ? (lastOut.stages as Array<Record<string, unknown>>) : [];
    const pickStageIdx = (() => {
      if (!stages.length) return -1;
      const score = (st: Record<string, unknown>) => {
        const r = (st.result && typeof st.result === 'object') ? (st.result as Record<string, unknown>) : {};
        const sel = (r.selected && typeof r.selected === 'object') ? (r.selected as Record<string, unknown>) : {};
        const patch = (sel.config_patch && typeof sel.config_patch === 'object') ? (sel.config_patch as Record<string, unknown>) : {};
        const sug = (sel.config_suggest && typeof sel.config_suggest === 'object') ? (sel.config_suggest as Record<string, unknown>) : {};
        const patchN = Object.keys(patch).length;
        const sugN = Object.keys(sug).length;
        const approvalId = String(r.approval_id ?? '').trim();
        const draftId = String(r.draft_id ?? '').trim();
        const hasIds = Number(Boolean(approvalId)) + Number(Boolean(draftId));
        const best = (r.best && typeof r.best === 'object') ? (r.best as Record<string, unknown>) : {};
        const bestMax = Number(best.max ?? NaN);
        const bestScore = Number.isFinite(bestMax) ? bestMax : -1e18;
        return patchN * 1000000 + sugN * 10000 + hasIds * 100 + bestScore;
      };
      let bestIdx = 0;
      let bestScore = score(stages[0]!);
      for (let i = 1; i < stages.length; i++) {
        const s = score(stages[i]!);
        if (s > bestScore) {
          bestScore = s;
          bestIdx = i;
        }
      }
      return bestIdx;
    })();
    const bestStage = (pickStageIdx >= 0 && pickStageIdx < stages.length) ? stages[pickStageIdx] : null;
    const firstStage = bestStage;
    const firstResult = (bestStage && typeof bestStage.result === 'object' && bestStage.result) ? (bestStage.result as Record<string, unknown>) : {};
    const selected = (firstResult.selected && typeof firstResult.selected === 'object') ? (firstResult.selected as Record<string, unknown>) : {};
    const configPatch = (selected.config_patch && typeof selected.config_patch === 'object') ? (selected.config_patch as Record<string, unknown>) : {};
    const configSuggest = (selected.config_suggest && typeof selected.config_suggest === 'object') ? (selected.config_suggest as Record<string, unknown>) : {};
    const approvalId = String(firstResult.approval_id ?? '').trim();
    const draftId = String(firstResult.draft_id ?? '').trim();
    const applyObj = (firstResult.apply && typeof firstResult.apply === 'object') ? (firstResult.apply as Record<string, unknown>) : {};
    const applyMode = String(applyObj.mode ?? '').trim();
    const autoApply = (firstResult.auto_apply && typeof firstResult.auto_apply === 'object') ? (firstResult.auto_apply as Record<string, unknown>) : {};
    return { details, lastWrap, lastOut, stages, firstStage, firstResult, firstStageIdx: pickStageIdx, configPatch, configSuggest, approvalId, draftId, applyMode, autoApply };
  }, [selectedCard]);

  const approvalDetailQuery = useQuery({
    queryKey: ['approvals', 'get', paramoptLatest?.approvalId],
    queryFn: async () => {
      const id = String(paramoptLatest?.approvalId || '').trim();
      if (!id) return { ok: false, error: 'missing_id' };
      return await fetchApprovalGet({ id });
    },
    enabled: Boolean(paramoptLatest?.approvalId),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const draftDetailQuery = useQuery({
    queryKey: ['agent', 'changeset_draft', 'get', paramoptLatest?.draftId],
    queryFn: async () => {
      const id = String(paramoptLatest?.draftId || '').trim();
      if (!id) return { ok: false, error: 'missing_id' };
      return await fetchAgentChangesetDraftGet({ id });
    },
    enabled: Boolean(paramoptLatest?.draftId),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  type ParamoptScenarioEnsurePayload = Parameters<typeof runAutomationParamoptScenariosEnsure>[0];
  const paramoptScenarioEnsureMutation = useMutation({
    mutationFn: async (payload: ParamoptScenarioEnsurePayload) => await runAutomationParamoptScenariosEnsure(payload),
  });

  const paramoptSmokeApplyMutation = useMutation({
    mutationFn: async () => await runAutomationParamoptSmokeApply({
      rollback_after: true,
      scenario: 'E',
      preset: 'o6',
      n_init: 2,
      n_iter: 4,
      folds: 3,
      eval_mode: 'rolling',
    }),
  });

  const gtwTraceId = String(selectedCard?.trace_id ?? '').trim();
  const gtwEnabled = Boolean(selectedCard && String(selectedCard.card_id) === 'gtw_global_workflow' && gtwTraceId);
  const otherEnabled = Boolean(selectedCard && String(selectedCard.card_id) === 'other');

  const gtwDecisionPkgQuery = useQuery({
    queryKey: ['gtw', 'decision_package', gtwTraceId],
    queryFn: async () => await fetchAgentPipelineArtifacts({ trace_id: gtwTraceId, kind: 'gtw.decision_package', limit: 200 }),
    enabled: gtwEnabled,
    refetchInterval: 8000,
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 4,
    retryDelay: (attemptIndex) => Math.min(15000, 800 * 2 ** attemptIndex),
  });

  const gtwTriggeredQuery = useQuery({
    queryKey: ['gtw', 'triggered', gtwTraceId],
    queryFn: async () => await fetchAgentPipelineArtifacts({ trace_id: gtwTraceId, kind: 'gtw.triggered', limit: 50 }),
    enabled: gtwEnabled,
    refetchInterval: 8000,
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 4,
    retryDelay: (attemptIndex) => Math.min(15000, 800 * 2 ** attemptIndex),
  });

  const rcaTailQuery = useQuery({
    queryKey: ['agent', 'outbox', 'rca', 'tail'],
    queryFn: async () => {
      try {
        return await fetchAgentOutboxRead({ name: 'rca.jsonl', tail: true, limit: 200, compact: false });
      } catch (e) {
        const st = (e as { response?: { status?: number } } | null | undefined)?.response?.status;
        if (st === 404) {
          return { ok: true, name: 'rca.jsonl', offset: 0, next_offset: 0, items: [], count: 0, reset: false, ts: Date.now() };
        }
        throw e;
      }
    },
    enabled: otherEnabled,
    refetchInterval: 10000,
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 2,
    retryDelay: (attemptIndex) => Math.min(10000, 800 * 2 ** attemptIndex),
  });

  const sysMonReports = useMemo(() => {
    const resp = rcaTailQuery.data as { items?: { item: unknown }[] } | undefined;
    const items = Array.isArray(resp?.items) ? resp!.items : [];
    const out: Array<{ id: string; trace_id: string; ts_ms: number; severity: string; report: SystemMonitorReport }> = [];

    for (const it of items) {
      const raw = (it && typeof it.item === 'object' && it.item) ? (it.item as RcaOutboxItem) : null;
      if (!raw) continue;
      const tp = String(raw.event_type ?? raw.type ?? '').trim();
      if (tp !== 'system.monitor.report') continue;
      const rep = (raw.result && typeof raw.result === 'object') ? raw.result : null;
      if (!rep) continue;
      const tid = String(raw.trace_id ?? rep.trace_id ?? '').trim();
      const id = String(raw.id ?? '').trim() || tid;
      if (!tid) continue;
      const ts = Number(raw.ts ?? rep.ts ?? 0);
      const ts_ms = ts > 1e11 ? ts : ts * 1000;
      const sev = String(raw.severity ?? '').trim().toUpperCase() || 'P3';
      out.push({ id, trace_id: tid, ts_ms, severity: sev, report: rep });
    }

    out.sort((a, b) => b.ts_ms - a.ts_ms);
    return out;
  }, [rcaTailQuery.data]);

  const sysMonCardsView = useMemo(() => {
    const now = nowMs;
    const win24h = sysMonReports.filter((x) => (x.ts_ms > 0) && (now - x.ts_ms <= 24 * 3600 * 1000));
    const fixed = win24h.filter((x) => x.report.auto_exec?.ok === true);
    const needAppr = win24h.filter((x) => String(x.report.summary?.approval_id ?? '').trim().length > 0 && x.report.auto_exec?.ok !== true);
    const draft = win24h.filter((x) => String(x.report.summary?.changeset_draft_id ?? '').trim().length > 0 && String(x.report.summary?.approval_id ?? '').trim().length <= 0 && x.report.auto_exec?.ok !== true);
    const p1 = win24h.filter((x) => x.severity === 'P1');
    const p2 = win24h.filter((x) => x.severity === 'P2');
    const p3 = win24h.filter((x) => x.severity === 'P3');
    const successRate = win24h.length ? fixed.length / win24h.length : NaN;
    const last = sysMonReports.length ? sysMonReports[0] : null;
    const lastAge = last ? _msAgo(now, last.ts_ms) : '-';
    return {
      win24h,
      fixed,
      needAppr,
      draft,
      p1,
      p2,
      p3,
      successRate,
      lastAge,
    };
  }, [nowMs, sysMonReports]);

  const [sysMonOpen, setSysMonOpen] = useState<Record<string, boolean>>({});

  const gtwLatestDecisionPkgItem = useMemo(() => {
    const resp = gtwDecisionPkgQuery.data as AgentPipelineArtifactsResponse | undefined;
    const items = Array.isArray(resp?.items) ? resp!.items : [];
    if (items.length <= 0) return null;
    return items[items.length - 1]?.item ?? null;
  }, [gtwDecisionPkgQuery.data]);

  const gtwLatestTriggeredItem = useMemo(() => {
    const resp = gtwTriggeredQuery.data as AgentPipelineArtifactsResponse | undefined;
    const items = Array.isArray(resp?.items) ? resp!.items : [];
    if (items.length <= 0) return null;
    return items[items.length - 1]?.item ?? null;
  }, [gtwTriggeredQuery.data]);

  const actionMutation = useMutation({
    mutationFn: async (req: Record<string, unknown>) => {
      const tp = String(req?.type ?? '').trim();
      const _viaQwenControl = async (tool: string, payload: Record<string, unknown>) => {
        const traceId = `${_nowMs()}_${Math.random().toString(16).slice(2)}`;
        const out = await executeAgentSkills({
          trace_id: traceId,
          async: false,
          tool_plan: [{ tool, input: { ...payload, trace_id: traceId } }],
        });
        const results = Array.isArray(out?.results) ? out.results : [];
        const r0 = (results.length > 0 && typeof results[0] === 'object' && results[0]) ? (results[0] as Record<string, unknown>) : {};
        const skillOut = (r0.result && typeof r0.result === 'object') ? (r0.result as Record<string, unknown>) : {};
        const inner = (skillOut.result && typeof skillOut.result === 'object') ? (skillOut.result as Record<string, unknown>) : null;
        return inner || skillOut || out;
      };
      if (tp === 'automation.config') {
        const payload = (req?.payload && typeof req.payload === 'object') ? (req.payload as Record<string, unknown>) : {};
        return await setAutomationConfig({ ...payload, confirm_live: true, trace_id: `${_nowMs()}_${Math.random().toString(16).slice(2)}` });
      }
      if (tp === 'automation.shadow_loop.run') {
        const payload = (req?.payload && typeof req.payload === 'object') ? (req.payload as Record<string, unknown>) : {};
        return await _viaQwenControl('qwen.control.shadow_loop_run', { ...payload });
      }
      if (tp === 'automation.supply_chain.run') {
        const payload = (req?.payload && typeof req.payload === 'object') ? (req.payload as Record<string, unknown>) : {};
        return await runAutomationSupplyChain({ ...payload });
      }
      if (tp === 'automation.paramopt.trigger') {
        const payload = (req?.payload && typeof req.payload === 'object') ? (req.payload as Record<string, unknown>) : {};
        return await _viaQwenControl('qwen.control.paramopt_trigger', { ...payload, confirm_live: true });
      }
      if (tp === 'automation.paramopt.explore.trigger') {
        const payload = (req?.payload && typeof req.payload === 'object') ? (req.payload as Record<string, unknown>) : {};
        return await triggerAutomationParamoptExplore({ ...payload, confirm_live: true, trace_id: `${_nowMs()}_${Math.random().toString(16).slice(2)}` });
      }
      if (tp === 'automation.system_monitor.run') {
        const payload = (req?.payload && typeof req.payload === 'object') ? (req.payload as Record<string, unknown>) : {};
        return await _viaQwenControl('qwen.control.system_monitor_run', { ...payload });
      }
      if (tp === 'automation.gtw.run') {
        const payload = (req?.payload && typeof req.payload === 'object') ? (req.payload as Record<string, unknown>) : {};
        return await _viaQwenControl('qwen.control.gtw_run', {
          force: Boolean(payload.force),
          trigger_event: (payload.trigger_event == null ? null : String(payload.trigger_event)),
        });
      }
      if (tp === 'automation.web3.market_digest.run') {
        const payload = (req?.payload && typeof req.payload === 'object') ? (req.payload as Record<string, unknown>) : {};
        return await runAutomationWeb3MarketDigest({ force: Boolean(payload.force), trigger_event: (payload.trigger_event == null ? null : String(payload.trigger_event)) });
      }
      return { ok: false, error: 'unknown_action' } as { ok: boolean; error?: string };
    },
    onSuccess: () => {
      cardsQuery.refetch();
    },
  });

  const canOperate = hasOperatorToken();
  const canWriteConfig = canOperate || Boolean(authMeQuery.data?.ok);

  const uiEnv = getUiEnv();
  const backendEnvRaw = String(
    (configQuery.data as unknown as { governance_env?: unknown; _governance_env?: unknown } | undefined)?.governance_env
      ?? (configQuery.data as unknown as { governance_env?: unknown; _governance_env?: unknown } | undefined)?._governance_env
      ?? ''
  ).trim().toLowerCase();
  const backendEnvNorm = (backendEnvRaw === 'prod' || backendEnvRaw === 'explore' || backendEnvRaw === 'pilot') ? backendEnvRaw : '';
  const isExplore = uiEnv === 'explore' || backendEnvNorm === 'explore';
  const envMismatch = backendEnvNorm && backendEnvNorm !== uiEnv;

  const approvalsSummaryQuery = useQuery({
    queryKey: ['approvals', 'summary'],
    queryFn: async () => await fetchApprovalsSummary({ max_lines: 4000, max_bytes: 4_000_000 }),
    enabled: String(selectedCard?.card_id || '') === 'paramopt_automation',
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const pendingApprovals = useMemo(() => {
    const resp = approvalsSummaryQuery.data as unknown as { pending?: unknown } | undefined;
    const items = Array.isArray(resp?.pending) ? (resp!.pending as Array<Record<string, unknown>>) : [];
    const out = items
      .map((x) => ({
        id: String(x?.id ?? '').trim(),
        trace_id: String(x?.trace_id ?? '').trim(),
        action: String(x?.action ?? '').trim(),
        reason: String(x?.reason ?? '').trim(),
        approver: String(x?.approver ?? '').trim(),
        decision: String(x?.decision ?? '').trim(),
        ts: Number(x?.ts ?? 0),
        expires_at: Number(x?.expires_at ?? 0),
        ttl_ms: Number(x?.ttl_ms ?? NaN),
        is_explore: Boolean(x?.is_explore),
        auto_reject_policy: String(x?.auto_reject_policy ?? '').trim(),
      }))
      .filter((x) => Boolean(x.id));
    return out;
  }, [approvalsSummaryQuery.data]);

  const recentAutoRejectedApprovals = useMemo(() => {
    const resp = approvalsSummaryQuery.data as unknown as { recent_auto_rejected?: unknown } | undefined;
    const items = Array.isArray(resp?.recent_auto_rejected) ? (resp!.recent_auto_rejected as Array<Record<string, unknown>>) : [];
    return items
      .map((x) => ({
        id: String(x?.id ?? '').trim(),
        trace_id: String(x?.trace_id ?? '').trim(),
        action: String(x?.action ?? '').trim(),
        reason: String(x?.reason ?? '').trim(),
        decision: String(x?.decision ?? '').trim(),
        ts: Number(x?.ts ?? 0),
      }))
      .filter((x) => Boolean(x.id));
  }, [approvalsSummaryQuery.data]);

  const pendingApprovalDetailQuery = useQuery({
    queryKey: ['approvals', 'get', pendingApprovalSelectedId],
    queryFn: async () => await fetchApprovalGet({ id: String(pendingApprovalSelectedId || '') }),
    enabled: Boolean(pendingApprovalSelectedId),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const pendingApprovalRejectMutation = useMutation({
    mutationFn: async (id: string) => {
      const approvalResp = await fetchApprovalGet({ id: String(id) });
      if (!approvalResp?.ok) return approvalResp;
      const approval = (approvalResp.approval && typeof approvalResp.approval === 'object') ? (approvalResp.approval as Record<string, unknown>) : {};
      const traceId = String(approval.trace_id ?? approvalResp.id ?? id).trim();
      const action = String(approval.action ?? 'config.apply').trim() || 'config.apply';
      return await logApprovalDecision({ id: String(id), decision: 'reject', approver: 'ui', action, trace_id: traceId, reason: 'ui_quick_reject' });
    },
    onSuccess: async (res) => {
      setPendingApprovalActionResult(JSON.stringify(res ?? { ok: true }, null, 2));
      await approvalsSummaryQuery.refetch();
      await cardsQuery.refetch();
      await pendingApprovalDetailQuery.refetch();
    },
    onError: (err) => {
      const msg = String((err as { message?: unknown } | null | undefined)?.message ?? err);
      setPendingApprovalActionResult(JSON.stringify({ ok: false, error: msg }, null, 2));
    },
  });

  const pendingApprovalApproveApplyMutation = useMutation({
    mutationFn: async (id: string) => {
      const approvalResp = await fetchApprovalGet({ id: String(id) });
      if (!approvalResp?.ok) return approvalResp as unknown;
      const approval = (approvalResp.approval && typeof approvalResp.approval === 'object') ? (approvalResp.approval as Record<string, unknown>) : {};
      const traceId = String(approval.trace_id ?? approvalResp.id ?? id).trim();
      const action = String(approval.action ?? 'config.apply').trim() || 'config.apply';
      const changeset = (approval.changeset && typeof approval.changeset === 'object') ? (approval.changeset as Record<string, unknown>) : {};
      const policyRef = String((changeset as { policy_ref?: unknown } | undefined)?.policy_ref ?? 'gov_default').trim() || 'gov_default';
      const logRes = await logApprovalDecision({ id: String(id), decision: 'approved', approver: 'ui', action, trace_id: traceId, reason: 'ui_quick_approve' });
      const applyRes = await applyGovernanceChangeset({ trace_id: `${_nowMs()}_${id}`, confirm_live: true, policy_ref: policyRef, approval_id: String(id), changeset });
      return { ok: Boolean((logRes as { ok?: unknown } | undefined)?.ok) && Boolean((applyRes as { ok?: unknown } | undefined)?.ok), log: logRes, apply: applyRes };
    },
    onSuccess: async (res) => {
      setPendingApprovalActionResult(JSON.stringify(res ?? { ok: true }, null, 2));
      await approvalsSummaryQuery.refetch();
      await cardsQuery.refetch();
      await pendingApprovalDetailQuery.refetch();
    },
    onError: (err) => {
      const msg = String((err as { message?: unknown } | null | undefined)?.message ?? err);
      setPendingApprovalActionResult(JSON.stringify({ ok: false, error: msg }, null, 2));
    },
  });

  const exploreMutation = useMutation({
    mutationFn: async () => await updateConfig({ ...EXPLORE_WIDE_PRESET }),
    onSuccess: async (res) => {
      setExploreApplyResult(JSON.stringify(res ?? { ok: true }, null, 2));
      await configQuery.refetch();
      await cardsQuery.refetch();
    },
    onError: (err) => {
      const msg = String((err as { message?: unknown } | null | undefined)?.message ?? err);
      setExploreApplyResult(JSON.stringify({ ok: false, error: msg }, null, 2));
    },
  });

  const renderCard = (c: AutomationCardStateV1) => {
    const meta = _CARD_META[String(c.card_id)] ?? { title: String(c.card_id), desc: '' };
    const isWeb3LightCard = String(c.card_id) === 'web3_market_digest';
    const updatedAgo = _msAgo(nowMs, c.updated_at_ms);
    const pct = Math.max(0, Math.min(100, Number(c.progress?.pct ?? 0)));
    const traceId = String(c.trace_id ?? '').trim();
    const stuckFor = c.stuck?.stuck_since_ms ? _msToAgo(Math.max(0, nowMs - Number(c.stuck.stuck_since_ms))) : '-';
    const shadowDisabled = String(c.status) === 'BLOCKED' && String(c.stuck?.reason_code || '') === 'shadow_disabled';

    const controlledActions = Array.isArray(c.actions) ? c.actions.filter((a) => String(a.kind) === 'controlled') : [];
    const navActions = Array.isArray(c.actions) ? c.actions.filter((a) => String(a.kind) === 'navigate') : [];

    const doControlled = async (a: { id: string; label?: string; request?: Record<string, unknown> }) => {
      if (!canWriteConfig) return;
      if (!window.confirm(`确认执行：${String(a.label || a.id)}？`)) return;
      const req = (a.request && typeof a.request === 'object') ? (a.request as Record<string, unknown>) : {};
      await actionMutation.mutateAsync(req);
    };

    return (
      <Card key={String(c.card_id)}>
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-2">
            <span className="truncate">{meta.title}</span>
            <Badge variant={_statusBadgeVariant(String(c.status))}>{String(c.status || '').trim() || '-'}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="text-sm text-slate-600">
            {isWeb3LightCard ? '该卡片仅保留迁移提示与入口导航，主入口已迁移到基本面模块。' : meta.desc}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs text-slate-600 truncate">updated {updatedAgo}</div>
            {traceId ? <div className="text-xs text-slate-600 truncate">trace: {traceId}</div> : <div className="text-xs text-slate-400">trace: -</div>}
          </div>

          {isWeb3LightCard ? (
            <div className="rounded border bg-blue-50 px-2 py-2 text-xs text-blue-800">
              主入口：新闻分析请进入 /fundamental/news。
            </div>
          ) : null}

          <div className="h-2 rounded bg-slate-200 overflow-hidden">
            <div className="h-2 bg-emerald-500" style={{ width: `${pct}%` }} />
          </div>

          {(!isWeb3LightCard && c.stuck) ? (
            <div className="rounded border bg-white px-2 py-2 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-slate-700 truncate">stuck_at: {String(c.stuck.stuck_at || '-')}</div>
                <Badge variant="outline">stuck_for {stuckFor}</Badge>
              </div>
              <div className="mt-1 text-slate-600 truncate">
                {String(c.stuck.reason_code || '').trim() ? `reason_code: ${String(c.stuck.reason_code)}` : 'reason_code: -'}
              </div>
              <div className="mt-1 text-slate-600 truncate">{String(c.stuck.reason || '').trim() ? `reason: ${String(c.stuck.reason)}` : 'reason: -'}</div>
            </div>
          ) : null}
          {String(c.card_id) === 'paramopt_automation' && shadowDisabled ? (
            <div className="rounded border bg-amber-50 px-2 py-2 text-xs text-amber-800">
              disabled reason：需要先开启“策略自动影子闭环（enable_shadow_automation_loop）”
            </div>
          ) : null}

          {!isWeb3LightCard && Array.isArray(c.progress?.steps) ? (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
              {c.progress!.steps.map((s) => (
                <div key={String(s.key)} className="flex items-center justify-between rounded border bg-white px-2 py-1">
                  <span className="truncate">{String(s.label || s.key)}</span>
                  <span className="flex items-center gap-2">
                    {s.ts_ms ? <Badge variant="outline">{_msAgo(nowMs, Number(s.ts_ms))}</Badge> : null}
                    <Badge variant={_stepBadgeVariant(String(s.status))}>{String(s.status || '').trim() || '-'}</Badge>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-slate-400">-</div>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            {isWeb3LightCard ? (
              <>
                <Link to="/fundamental/news">
                  <Button size="sm" variant="outline">前往 /fundamental/news</Button>
                </Link>
              </>
            ) : (
              <Link to={`/agent/automation/${encodeURIComponent(String(c.card_id))}`}>
                <Button size="sm" variant="outline">进入</Button>
              </Link>
            )}
            {controlledActions.map((a) => (
              <Button
                key={String(a.id)}
                size="sm"
                variant="outline"
                disabled={
                  isWeb3LightCard ||
                  actionMutation.isPending ||
                  !canWriteConfig ||
                  (String(c.status) === 'BLOCKED' && String(c.stuck?.reason_code || '') === 'shadow_disabled' && String(a.id).includes('paramopt'))
                }
                title={
                  !canWriteConfig
                    ? '需要 Admin 登录或填入 Operator Token'
                    : (String(c.card_id) === 'paramopt_automation' && shadowDisabled && String(a.id).includes('paramopt'))
                      ? '需要先开启：策略自动影子闭环（enable_shadow_automation_loop）'
                      : undefined
                }
                onClick={() => void doControlled({ id: String(a.id), label: String(a.label || a.id), request: (a.request as Record<string, unknown> | undefined) })}
              >
                {String(a.label || a.id)}
              </Button>
            ))}
            {(isWeb3LightCard ? [] : navActions).map((a) => (
              <Link key={String(a.id)} to={isWeb3LightCard ? '/fundamental/news' : String(a.href || '#')}>
                <Button size="sm" variant="outline" disabled={!String(a.href || '').trim()}>
                  {String(a.label || a.id)}
                </Button>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  };

  const pageTitle = selectedCard ? (_CARD_META[String(selectedCard.card_id)]?.title ?? String(selectedCard.card_id)) : '自动化管理';
  const pageDesc = selectedCard ? (_CARD_META[String(selectedCard.card_id)]?.desc ?? '') : '运营视角：状态、进度、卡点与审批跳转';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-lg font-semibold">{pageTitle}</div>
          <div className="text-sm text-slate-600">{pageDesc}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <Badge variant="outline">ui_env {uiEnv}</Badge>
            <Badge variant="outline">backend_env {backendEnvNorm || '-'}</Badge>
            {!envMismatch ? null : <Badge variant="destructive">env_mismatch</Badge>}
            <Badge variant="outline">explore_wide_preset_card</Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {selectedCard ? (
            <Link to="/agent/automation">
              <Button variant="outline">返回</Button>
            </Link>
          ) : null}
          <Button variant="outline" onClick={() => { cardsQuery.refetch(); }}>刷新</Button>
        </div>
      </div>

      {cardsQuery.isLoading ? (
        <div className="rounded border bg-white px-4 py-6 text-sm text-slate-600">
          正在加载…
        </div>
      ) : cardsQuery.error ? (
        <div className="rounded border bg-white px-4 py-6 text-sm text-red-700">
          加载失败：{String((cardsQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}
        </div>
      ) : (!selectedCard && orderedCards.length <= 0) ? (
        <div className="rounded border bg-white px-4 py-6 text-sm text-slate-600">
          暂无可展示的自动化卡片（后端未返回 cards 或接口不可用）。
        </div>
      ) : null}

      {selectedCard ? (
        <div className="grid grid-cols-1 gap-6">
          {renderCard(selectedCard)}
          {String(selectedCard.card_id) === 'web3_market_digest' ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span>入口迁移提示</span>
                  <Badge variant="outline">web3_market_digest</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="rounded border bg-blue-50 px-3 py-2 text-blue-800">
                  为避免重复入口，本页面仅保留轻量跳转。新闻分析请走 /fundamental/news。
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Link to="/fundamental/news">
                    <Button variant="outline">前往 /fundamental/news</Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          ) : null}
          {String(selectedCard.card_id) === 'paramopt_automation' ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="truncate">贝叶斯参数优化详情（最新）</span>
                  <Badge variant="outline">paramopt</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {(() => {
                  const details = (selectedCard.details && typeof selectedCard.details === 'object') ? (selectedCard.details as Record<string, unknown>) : {};
                  const autoCfg = (details.automation && typeof details.automation === 'object') ? (details.automation as Record<string, unknown>) : {};
                  const lastWrap = (details.last && typeof details.last === 'object') ? (details.last as Record<string, unknown>) : {};
                  const exploreLast = (details.last_explore && typeof details.last_explore === 'object') ? (details.last_explore as Record<string, unknown>) : {};
                  const opsViewPassive = (details.ops_view_passive && typeof details.ops_view_passive === 'object')
                    ? (details.ops_view_passive as Record<string, unknown>)
                    : ((details.ops_view && typeof details.ops_view === 'object') ? (details.ops_view as Record<string, unknown>) : {});
                  const opsViewExplore = (details.ops_view_explore && typeof details.ops_view_explore === 'object') ? (details.ops_view_explore as Record<string, unknown>) : {};
                  const opsView = opsViewPassive;
                  const lastOut = (lastWrap.out && typeof lastWrap.out === 'object') ? (lastWrap.out as Record<string, unknown>) : {};
                  const summary = (lastOut.summary && typeof lastOut.summary === 'object') ? (lastOut.summary as Record<string, unknown>) : {};
                  const stageSummaries = Array.isArray(summary.stage_summaries) ? (summary.stage_summaries as Array<Record<string, unknown>>) : [];
                  const stages = Array.isArray(lastOut.stages) ? (lastOut.stages as Array<Record<string, unknown>>) : [];
                  const firstStage = stages.length ? stages[0] : null;
                  const firstResult = (firstStage && typeof firstStage.result === 'object' && firstStage.result) ? (firstStage.result as Record<string, unknown>) : {};
                  const firstBaseline = (firstResult.baseline && typeof firstResult.baseline === 'object') ? (firstResult.baseline as Record<string, unknown>) : {};
                  const firstBest = (firstResult.best && typeof firstResult.best === 'object') ? (firstResult.best as Record<string, unknown>) : {};
                  const firstBestMetrics = (firstBest.metrics && typeof firstBest.metrics === 'object') ? (firstBest.metrics as Record<string, unknown>) : {};
                  const firstApply = (firstResult.apply && typeof firstResult.apply === 'object') ? (firstResult.apply as Record<string, unknown>) : {};
                  const firstAutoApply = (firstResult.auto_apply && typeof firstResult.auto_apply === 'object') ? (firstResult.auto_apply as Record<string, unknown>) : {};
                  const metrics = [
                    { key: 'sortino', label: 'Sortino' },
                    { key: 'calmar', label: 'Calmar' },
                    { key: 'profit_factor', label: 'PF' },
                    { key: 'max_drawdown', label: 'MaxDD' },
                    { key: 'trades', label: 'Trades' },
                    { key: 'coverage_days', label: 'CoverageDays' },
                  ];
                  const pickedStageSummaries = paramoptShowAllStages ? stageSummaries : stageSummaries.slice(0, 4);
                  const freqSec = Number(autoCfg.trade_cycle_period_sec ?? NaN);
                  const triggerK = Number(autoCfg.loss_trigger_streak_k ?? NaN);
                  const exploreFreqSec = Number(autoCfg.explore_cycle_period_sec ?? NaN);
                  const exploreTtlH = Number(autoCfg.explore_approval_ttl_hours ?? NaN);
                  const triggerKText = Number.isFinite(triggerK) ? String(Math.floor(triggerK)) : '-';
                  const freqText = Number.isFinite(freqSec) && freqSec > 0 ? _secToHuman(freqSec) : '-';
                  const exploreFreqText = Number.isFinite(exploreFreqSec) && exploreFreqSec > 0 ? _secToHuman(exploreFreqSec) : '-';
                  const trend = Array.isArray(opsView.trend) ? (opsView.trend as Array<Record<string, unknown>>) : [];
                  const trendShow = paramoptShowAllOps ? trend : trend.slice(Math.max(0, trend.length - 8));
                  const scenarioShare = Array.isArray(opsView.scenario_share) ? (opsView.scenario_share as Array<Record<string, unknown>>) : [];
                  const scenarioShareShow = paramoptShowAllOps ? scenarioShare : scenarioShare.slice(0, 8);
                  const optimizationShare = Array.isArray(opsView.optimization_share)
                    ? (opsView.optimization_share as Array<Record<string, unknown>>)
                    : (Array.isArray(opsView.module_share) ? (opsView.module_share as Array<Record<string, unknown>>) : []);
                  const moduleShare = optimizationShare;
                  const moduleShareShow = paramoptShowAllOps ? moduleShare : moduleShare.slice(0, 6);
                  const rejectTopn = Array.isArray(opsView.reject_topn) ? (opsView.reject_topn as Array<Record<string, unknown>>) : [];
                  const rejectTopnShow = paramoptShowAllOps ? rejectTopn : rejectTopn.slice(0, 6);
                  const opsSuccessRate = Number(opsView.success_rate ?? NaN);
                  const opsSuccessRate7 = Number(opsView.success_rate_7 ?? NaN);
                  const opsSuccessRate14 = Number(opsView.success_rate_14 ?? NaN);
                  const opsRunsN = Number(opsView.runs_n ?? NaN);
                  const opsAvgInt = Number(opsView.avg_interval_sec ?? NaN);
                  const opsStance = String(opsView.market_stance ?? '').trim() || '-';
                  const passiveRuns = Number(opsViewPassive.runs_n ?? NaN);
                  const passiveSuccess = Number(opsViewPassive.success_rate ?? NaN);
                  const exploreRuns = Number(opsViewExplore.runs_n ?? NaN);
                  const exploreSuccess = Number(opsViewExplore.success_rate ?? NaN);

                  return (
                    <div className="space-y-3">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                        <div className="rounded border bg-white px-3 py-2">
                          <div className="text-slate-600 mb-1">被动优化（监控/亏损触发）</div>
                          <div className="grid grid-cols-2 gap-2">
                            <div>连亏阈值: {triggerKText}</div>
                            <div>周期频率: {freqText}</div>
                            <div>近N次: {Number.isFinite(passiveRuns) ? String(Math.floor(passiveRuns)) : '-'}</div>
                            <div>成功率: {Number.isFinite(passiveSuccess) ? `${(passiveSuccess * 100).toFixed(1)}%` : '-'}</div>
                          </div>
                        </div>
                        <div className="rounded border bg-white px-3 py-2">
                          <div className="text-slate-600 mb-1">探索优化（策略库资产）</div>
                          <div className="grid grid-cols-2 gap-2">
                            <div>轮询频率: {exploreFreqText}</div>
                            <div>审批TTL: {Number.isFinite(exploreTtlH) ? `${Math.floor(exploreTtlH)}h` : '-'}</div>
                            <div>近N次: {Number.isFinite(exploreRuns) ? String(Math.floor(exploreRuns)) : '-'}</div>
                            <div>成功率: {Number.isFinite(exploreSuccess) ? `${(exploreSuccess * 100).toFixed(1)}%` : '-'}</div>
                          </div>
                          <div className="mt-1 text-slate-600">最近探索: {_msAgo(nowMs, Number(exploreLast.ts ?? 0))}</div>
                        </div>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2 text-xs">
                        <div className="rounded border bg-white px-2 py-2">
                          <div className="text-slate-600">触发阈值（连亏）</div>
                          <div>{triggerKText}</div>
                        </div>
                        <div className="rounded border bg-white px-2 py-2">
                          <div className="text-slate-600">周期寻参频率</div>
                          <div>{freqText}</div>
                        </div>
                        <div className="rounded border bg-white px-2 py-2">
                          <div className="text-slate-600">自动审批直发</div>
                          <div>{autoCfg.loss_auto_no_manual_approval ? 'ON' : 'OFF'}</div>
                        </div>
                        <div className="rounded border bg-white px-2 py-2">
                          <div className="text-slate-600">最近触发</div>
                          <div>{_msAgo(nowMs, Number(lastWrap.ts ?? 0))}</div>
                        </div>
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="text-xs text-slate-600 mb-2">优化状态与频率</div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                          <div>total: {String(summary.total ?? '-')}</div>
                          <div>ok: {String(summary.ok ?? '-')}</div>
                          <div>failed: {String(summary.failed ?? '-')}</div>
                          <div>trigger: {String(lastOut.trigger_event ?? '-')}</div>
                        </div>
                        <div className="mt-2 text-xs text-slate-600 break-all">
                          modules: {Array.isArray(lastOut.presets) ? (lastOut.presets as unknown[]).map((x) => String(x)).join(', ') : '-'}
                        </div>
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-xs text-slate-600">运营视角 1：最近 N 次优化成功率趋势</div>
                          <Button size="sm" variant="outline" onClick={() => setParamoptShowAllOps((v) => !v)}>
                            {paramoptShowAllOps ? '收起' : '展开更多'}
                          </Button>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 text-xs mt-2">
                          <div>runs_n: {Number.isFinite(opsRunsN) ? String(Math.floor(opsRunsN)) : '-'}</div>
                          <div>success_rate: {Number.isFinite(opsSuccessRate) ? `${(opsSuccessRate * 100).toFixed(1)}%` : '-'}</div>
                          <div>rolling7: {Number.isFinite(opsSuccessRate7) ? `${(opsSuccessRate7 * 100).toFixed(1)}%` : '-'}</div>
                          <div>rolling14: {Number.isFinite(opsSuccessRate14) ? `${(opsSuccessRate14 * 100).toFixed(1)}%` : '-'}</div>
                          <div>avg_interval: {Number.isFinite(opsAvgInt) ? _secToHuman(opsAvgInt) : '-'}</div>
                          <div>market_stance: {opsStance}</div>
                        </div>
                        <div className="mt-2 space-y-1 text-xs">
                          {trendShow.length ? trendShow.map((t, i) => {
                            const ok = Boolean(t.ok);
                            const ts = Number(t.ts ?? 0);
                            const sr = Number(t.success_rate ?? NaN);
                            const sr7 = Number(t.rolling_success_rate_7 ?? NaN);
                            const sr14 = Number(t.rolling_success_rate_14 ?? NaN);
                            const sc = String(t.scenario ?? '').trim();
                            const scTitle = String(t.scenario_title ?? '').trim();
                            const scRule = String(t.scenario_rule_id ?? '').trim();
                            const scWhy = String(t.scenario_why ?? '').trim();
                            const scEvidence = (t.scenario_evidence && typeof t.scenario_evidence === 'object') ? (t.scenario_evidence as Record<string, unknown>) : {};
                            const matchedRules = Array.isArray(scEvidence.matched_rules) ? (scEvidence.matched_rules as Array<Record<string, unknown>>) : [];
                            const primaryRuleId = scRule || (matchedRules.map((x) => String(x.rule_id ?? '').trim()).find((x) => x) ?? '');
                            const secondaryRuleIds = matchedRules
                              .map((x) => String(x.rule_id ?? '').trim())
                              .filter((x) => x && x !== primaryRuleId)
                              .slice(0, 4);
                            const hardFails = Array.isArray(scEvidence.hard_fails) ? (scEvidence.hard_fails as unknown[]).map((x) => String(x)).filter((x) => x.trim()) : [];
                            const causeCodes = Array.isArray(scEvidence.cause_codes) ? (scEvidence.cause_codes as unknown[]).map((x) => String(x)).filter((x) => x.trim()) : [];
                            const mods = Array.isArray(t.presets) ? (t.presets as unknown[]).map((x) => String(x)).join(', ') : '-';
                            return (
                              <div key={`${String(t.idx ?? i)}_${ts}`} className="rounded border bg-slate-50 px-2 py-2 space-y-1">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span>{_msAgo(nowMs, ts)}</span>
                                  <span className="flex items-center gap-2">
                                    {sc ? <Badge variant="outline">{sc}{scTitle ? ` ${scTitle}` : ''}</Badge> : null}
                                    {primaryRuleId ? <Badge variant="secondary">主判定 {primaryRuleId}</Badge> : null}
                                    {secondaryRuleIds.length ? <Badge variant="outline">次判定 {secondaryRuleIds.length}</Badge> : null}
                                  </span>
                                </div>
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span className="flex items-center gap-2">
                                  <Badge variant={ok ? 'secondary' : 'destructive'}>{ok ? 'ok' : 'fail'}</Badge>
                                  <Badge variant="outline">{Number.isFinite(sr) ? `${(sr * 100).toFixed(1)}%` : '-'}</Badge>
                                  <Badge variant="outline">7:{Number.isFinite(sr7) ? `${(sr7 * 100).toFixed(0)}%` : '-'}</Badge>
                                  <Badge variant="outline">14:{Number.isFinite(sr14) ? `${(sr14 * 100).toFixed(0)}%` : '-'}</Badge>
                                  </span>
                                  <span className="text-slate-600 truncate">{mods || '-'}</span>
                                </div>
                                <div className="text-slate-600 truncate">
                                  证据: 主={primaryRuleId || '-'} | 次={secondaryRuleIds.length ? secondaryRuleIds.join(', ') : '-'}{scWhy ? ` | ${scWhy}` : ''}
                                </div>
                                <details className="rounded border bg-white px-2 py-1">
                                  <summary className="cursor-pointer select-none text-slate-700">展开证据明细（rules + signals）</summary>
                                  <div className="mt-2 space-y-2">
                                    {matchedRules.length ? matchedRules.map((mr, j) => {
                                      const rid = String(mr.rule_id ?? '').trim() || '-';
                                      const msc = String(mr.scenario ?? '').trim() || '-';
                                      const mwhy = String(mr.why ?? '').trim() || '-';
                                      const sig = (mr.signals && typeof mr.signals === 'object') ? (mr.signals as Record<string, unknown>) : {};
                                      const isPrimary = Boolean(primaryRuleId) && rid === primaryRuleId;
                                      return (
                                        <div key={`${rid}_${j}`} className="rounded border bg-slate-50 px-2 py-2">
                                          <div className="flex flex-wrap items-center gap-2">
                                            <Badge variant={isPrimary ? 'secondary' : 'outline'}>{rid}</Badge>
                                            <Badge variant={isPrimary ? 'secondary' : 'outline'}>{isPrimary ? '主判定规则' : '次判定规则'}</Badge>
                                            <Badge variant="outline">{msc}</Badge>
                                            <span className="text-slate-600">{mwhy}</span>
                                          </div>
                                          <pre className="mt-1 text-[11px] overflow-auto max-h-[180px] whitespace-pre-wrap">{JSON.stringify(sig, null, 2)}</pre>
                                        </div>
                                      );
                                    }) : <div className="text-slate-400">无命中规则</div>}
                                    <div className="text-[11px] text-slate-600 break-all">
                                      hard_fails: {hardFails.length ? hardFails.join(', ') : '-'}
                                    </div>
                                    <div className="text-[11px] text-slate-600 break-all">
                                      cause_codes: {causeCodes.length ? causeCodes.join(', ') : '-'}
                                    </div>
                                  </div>
                                </details>
                              </div>
                            );
                          }) : <div className="text-slate-400">-</div>}
                        </div>
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="text-xs text-slate-600">运营视角 2：文档场景占比 + 优化占比 + 拒绝原因 TopN</div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mt-2">
                          <div className="rounded border bg-slate-50 px-2 py-2">
                            <div className="text-xs text-slate-600 mb-1">文档场景占比（A-G）</div>
                            <div className="space-y-1 text-xs">
                              {scenarioShareShow.length ? scenarioShareShow.map((s, i) => {
                                const cnt = Number(s.count ?? NaN);
                                const sh = Number(s.share ?? NaN);
                                const sc = String(s.scenario ?? i);
                                const title = String(s.title ?? '').trim();
                                return <div key={`${sc}_${i}`} className="flex items-center justify-between gap-2"><span className="truncate">{title ? `${sc} ${title}` : sc}</span><span>{Number.isFinite(cnt) ? String(Math.floor(cnt)) : '-'} / {Number.isFinite(sh) ? `${(sh * 100).toFixed(1)}%` : '-'}</span></div>;
                              }) : <div className="text-slate-400">-</div>}
                            </div>
                          </div>
                          <div className="rounded border bg-slate-50 px-2 py-2">
                            <div className="text-xs text-slate-600 mb-1">优化占比（O模块）</div>
                            <div className="space-y-1 text-xs">
                              {moduleShareShow.length ? moduleShareShow.map((m, i) => {
                                const cnt = Number(m.count ?? NaN);
                                const sh = Number(m.share ?? NaN);
                                return <div key={`${String(m.module ?? i)}`} className="flex items-center justify-between gap-2"><span>{String(m.module ?? '-')}</span><span>{Number.isFinite(cnt) ? String(Math.floor(cnt)) : '-'} / {Number.isFinite(sh) ? `${(sh * 100).toFixed(1)}%` : '-'}</span></div>;
                              }) : <div className="text-slate-400">-</div>}
                            </div>
                          </div>
                          <div className="rounded border bg-slate-50 px-2 py-2">
                            <div className="text-xs text-slate-600 mb-1">拒绝原因 TopN</div>
                            <div className="space-y-1 text-xs">
                              {rejectTopnShow.length ? rejectTopnShow.map((r, i) => {
                                const cnt = Number(r.count ?? NaN);
                                return <div key={`${String(r.reason ?? i)}`} className="flex items-center justify-between gap-2"><span className="truncate">{String(r.reason ?? '-')}</span><span>{Number.isFinite(cnt) ? String(Math.floor(cnt)) : '-'}</span></div>;
                              }) : <div className="text-slate-400">-</div>}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="text-xs text-slate-600 mb-2">最新一次优化前后对比</div>
                        {!firstStage ? (
                          <div className="text-xs text-slate-400">-</div>
                        ) : (
                          <div className="space-y-2">
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
                              <div className="rounded border bg-slate-50 px-2 py-2">preset: {String(firstStage.preset ?? '-')}</div>
                              <div className="rounded border bg-slate-50 px-2 py-2">route: {String((stageSummaries[(paramoptLatest?.firstStageIdx ?? 0)]?.route ?? '-'))}</div>
                              <div className="rounded border bg-slate-50 px-2 py-2">apply_mode: {String(firstApply.mode ?? '-')}</div>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                              {metrics.map((m) => {
                                const b = Number(firstBaseline[m.key] ?? NaN);
                                const a = Number(firstBestMetrics[m.key] ?? NaN);
                                const has = Number.isFinite(b) || Number.isFinite(a);
                                return (
                                  <div key={m.key} className="rounded border bg-slate-50 px-2 py-2 flex items-center justify-between gap-2">
                                    <span>{m.label}</span>
                                    {!has ? (
                                      <span className="text-slate-400">-</span>
                                    ) : (
                                      <span className="truncate">
                                        {Number.isFinite(b) ? b.toFixed(4) : '-'} → {Number.isFinite(a) ? a.toFixed(4) : '-'}
                                      </span>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                              <div className="rounded border bg-white px-2 py-2">
                                <div className="text-slate-600">优化结果</div>
                                <div className="mt-1 break-all">{firstResult.ok ? 'ok' : 'fail'} / {String(firstResult.error ?? '-')}</div>
                              </div>
                              <div className="rounded border bg-white px-2 py-2">
                                <div className="text-slate-600">自动应用</div>
                                <div className="mt-1 break-all">{firstAutoApply && Object.keys(firstAutoApply).length ? JSON.stringify(firstAutoApply) : '-'}</div>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="text-xs text-slate-600 mb-2">参数变化（selected.config_patch / config_suggest）</div>
                        {(() => {
                          const patch = (paramoptLatest && paramoptLatest.configPatch && Object.keys(paramoptLatest.configPatch).length) ? paramoptLatest.configPatch : {};
                          const suggest = (paramoptLatest && paramoptLatest.configSuggest && Object.keys(paramoptLatest.configSuggest).length) ? paramoptLatest.configSuggest : {};
                          const cfg = (configQuery.data as unknown as Record<string, unknown> | undefined) || {};
                          const patchKeys = Object.keys(patch);
                          const suggestKeys = Object.keys(suggest);
                          const fmt = (v: unknown) => {
                            if (v === null) return 'null';
                            if (v === undefined) return 'undefined';
                            if (typeof v === 'string') return v;
                            if (typeof v === 'number' || typeof v === 'boolean') return String(v);
                            try { return JSON.stringify(v); } catch { return String(v); }
                          };
                          return (
                            <div className="space-y-2">
                              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                                <div>patch_keys: {patchKeys.length}</div>
                                <div>suggest_keys: {suggestKeys.length}</div>
                                <div>draft_id: {paramoptLatest?.draftId || '-'}</div>
                                <div>approval_id: {paramoptLatest?.approvalId || '-'}</div>
                              </div>
                              {!patchKeys.length && !suggestKeys.length ? (
                                <div className="text-xs text-slate-400">-</div>
                              ) : (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                                  {patchKeys.slice(0, 60).map((k) => (
                                    <div key={k} className="rounded border bg-slate-50 px-2 py-2">
                                      <div className="text-slate-600">{k}</div>
                                      <div className="mt-1 break-all">{fmt(cfg[k])} → {fmt(patch[k])}</div>
                                    </div>
                                  ))}
                                  {!suggestKeys.length ? null : (
                                    <div className="rounded border bg-white px-2 py-2">
                                      <div className="text-slate-600">config_suggest（raw）</div>
                                      <pre className="mt-1 text-[11px] overflow-auto max-h-[220px] whitespace-pre-wrap">{JSON.stringify(suggest, null, 2)}</pre>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })()}
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-xs text-slate-600">审批流水线（draft → approval → apply）</div>
                          <div className="flex items-center gap-2">
                            <Button size="sm" variant="outline" onClick={() => { void approvalDetailQuery.refetch(); void draftDetailQuery.refetch(); }}>
                              刷新
                            </Button>
                          </div>
                        </div>
                        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                          <div className="rounded border bg-slate-50 px-2 py-2">
                            <div className="text-slate-600">apply_mode</div>
                            <div className="mt-1 break-all">{paramoptLatest?.applyMode || '-'}</div>
                          </div>
                          <div className="rounded border bg-slate-50 px-2 py-2">
                            <div className="text-slate-600">auto_apply</div>
                            <div className="mt-1 break-all">{paramoptLatest?.autoApply && Object.keys(paramoptLatest.autoApply).length ? JSON.stringify(paramoptLatest.autoApply) : '-'}</div>
                          </div>
                          <div className="rounded border bg-white px-2 py-2">
                            <div className="text-slate-600">approval.get</div>
                            {approvalDetailQuery.isLoading ? (
                              <div className="mt-1 text-slate-400">loading…</div>
                            ) : approvalDetailQuery.error ? (
                              <div className="mt-1 text-red-700">error: {String((approvalDetailQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}</div>
                            ) : (
                              <pre className="mt-1 text-[11px] overflow-auto max-h-[220px] whitespace-pre-wrap">{JSON.stringify((approvalDetailQuery.data as unknown as Record<string, unknown> | undefined) ?? null, null, 2)}</pre>
                            )}
                          </div>
                          <div className="rounded border bg-white px-2 py-2">
                            <div className="text-slate-600">changeset_draft.get</div>
                            {draftDetailQuery.isLoading ? (
                              <div className="mt-1 text-slate-400">loading…</div>
                            ) : draftDetailQuery.error ? (
                              <div className="mt-1 text-red-700">error: {String((draftDetailQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}</div>
                            ) : (
                              <pre className="mt-1 text-[11px] overflow-auto max-h-[220px] whitespace-pre-wrap">{JSON.stringify((draftDetailQuery.data as unknown as Record<string, unknown> | undefined) ?? null, null, 2)}</pre>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-xs text-slate-600">待审批（Approvals · pending）</div>
                          <div className="flex items-center gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => { void approvalsSummaryQuery.refetch(); if (pendingApprovalSelectedId) void pendingApprovalDetailQuery.refetch(); }}
                            >
                              刷新
                            </Button>
                          </div>
                        </div>
                        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                          <div className="rounded border bg-slate-50 px-2 py-2">
                            <div className="text-slate-600">pending 列表（最多 20）</div>
                            {approvalsSummaryQuery.isLoading ? (
                              <div className="mt-1 text-slate-400">loading…</div>
                            ) : approvalsSummaryQuery.error ? (
                              <div className="mt-1 text-red-700">error: {String((approvalsSummaryQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}</div>
                            ) : pendingApprovals.length ? (
                              <div className="mt-2 space-y-2">
                                {pendingApprovals.map((it) => (
                                  <div key={it.id} className={`rounded border px-2 py-2 ${pendingApprovalSelectedId === it.id ? 'bg-white' : 'bg-slate-100'}`}>
                                    <div className="flex flex-wrap items-center justify-between gap-2">
                                      <div className="font-mono break-all">{it.id}</div>
                                      <div className="flex flex-wrap items-center gap-2 text-slate-500">
                                        {it.is_explore ? <Badge variant="outline">探索审批</Badge> : <Badge variant="outline">常规审批</Badge>}
                                        {it.is_explore && it.auto_reject_policy ? <Badge variant="destructive">自动驳回策略</Badge> : null}
                                        <span>{_msAgo(nowMs, it.ts)}</span>
                                      </div>
                                    </div>
                                    <div className="mt-1 text-slate-600 break-all">{it.action || '-'}</div>
                                    <div className="mt-1 break-all">{it.reason || '-'}</div>
                                    <div className="mt-1 flex flex-wrap items-center gap-2 text-slate-600">
                                      <span>TTL: {_ttlText(it.ttl_ms)}</span>
                                      {Number.isFinite(it.expires_at) && it.expires_at > 0 ? <span>截止: {_msAgo(nowMs, it.expires_at)}</span> : null}
                                      {it.decision ? <Badge variant="outline">{it.decision}</Badge> : null}
                                    </div>
                                    <div className="mt-2 flex flex-wrap gap-2">
                                      <Button size="sm" variant="outline" onClick={() => { setPendingApprovalSelectedId(it.id); }}>
                                        查看
                                      </Button>
                                      {it.trace_id ? (
                                        <Link to={`/agent/ops?trace_id=${encodeURIComponent(String(it.trace_id))}#approvals`}>
                                          <Button size="sm" variant="outline">一键查看审批材料</Button>
                                        </Link>
                                      ) : null}
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={!canWriteConfig || pendingApprovalApproveApplyMutation.isPending}
                                        onClick={() => { pendingApprovalApproveApplyMutation.mutate(it.id); }}
                                      >
                                        {pendingApprovalApproveApplyMutation.isPending ? '执行中…' : '批准并应用'}
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={!canWriteConfig || pendingApprovalRejectMutation.isPending}
                                        onClick={() => { pendingApprovalRejectMutation.mutate(it.id); }}
                                      >
                                        {pendingApprovalRejectMutation.isPending ? '执行中…' : '驳回'}
                                      </Button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="mt-1 text-slate-400">暂无 pending</div>
                            )}
                            <div className="mt-3 rounded border bg-white px-2 py-2">
                              <div className="text-slate-600">自动驳回（最近，expired_24h_auto_reject）</div>
                              {recentAutoRejectedApprovals.length ? (
                                <div className="mt-2 space-y-2">
                                  {recentAutoRejectedApprovals.map((it) => (
                                    <div key={`auto_rej_${it.id}_${it.ts}`} className="rounded border bg-slate-50 px-2 py-2">
                                      <div className="flex flex-wrap items-center justify-between gap-2">
                                        <div className="font-mono break-all">{it.id}</div>
                                        <div className="flex items-center gap-2 text-slate-500">
                                          <Badge variant="destructive">AUTO_REJECTED</Badge>
                                          <span>{_msAgo(nowMs, it.ts)}</span>
                                        </div>
                                      </div>
                                      <div className="mt-1 text-slate-600 break-all">{it.action || '-'}</div>
                                      <div className="mt-1 break-all">{it.reason || '-'}</div>
                                      <div className="mt-2 flex flex-wrap gap-2">
                                        <Button size="sm" variant="outline" onClick={() => { setPendingApprovalSelectedId(it.id); }}>
                                          查看记录
                                        </Button>
                                        {it.trace_id ? (
                                          <Link to={`/agent/ops?trace_id=${encodeURIComponent(String(it.trace_id))}#approvals`}>
                                            <Button size="sm" variant="outline">一键查看审批材料</Button>
                                          </Link>
                                        ) : null}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <div className="mt-1 text-slate-400">暂无自动驳回记录</div>
                              )}
                            </div>
                          </div>

                          <div className="rounded border bg-white px-2 py-2">
                            <div className="text-slate-600">approval.get（selected）</div>
                            {!pendingApprovalSelectedId ? (
                              <div className="mt-1 text-slate-400">未选择</div>
                            ) : pendingApprovalDetailQuery.isLoading ? (
                              <div className="mt-1 text-slate-400">loading…</div>
                            ) : pendingApprovalDetailQuery.error ? (
                              <div className="mt-1 text-red-700">error: {String((pendingApprovalDetailQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}</div>
                            ) : (
                              <pre className="mt-1 text-[11px] overflow-auto max-h-[260px] whitespace-pre-wrap">{JSON.stringify((pendingApprovalDetailQuery.data as unknown as Record<string, unknown> | undefined) ?? null, null, 2)}</pre>
                            )}
                            {pendingApprovalActionResult ? (
                              <pre className="mt-2 text-[11px] overflow-auto max-h-[180px] whitespace-pre-wrap">{pendingApprovalActionResult}</pre>
                            ) : null}
                          </div>
                        </div>
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="text-xs text-slate-600 mb-2">自动化操作（覆盖场景 / 实盘链路自检）</div>
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!canWriteConfig || paramoptScenarioEnsureMutation.isPending}
                            onClick={() => {
                              paramoptScenarioEnsureMutation.mutate({
                                ensure_missing_only: true,
                                max_batches: 3,
                                source: 'ui',
                                budget: { n_init: 3, n_iter: 10, skip_robustness: true, auto_draft: true, no_manual_approval: false },
                              });
                            }}
                          >
                            {paramoptScenarioEnsureMutation.isPending ? '补齐中…' : '补齐场景覆盖（A-G）'}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!canWriteConfig || paramoptScenarioEnsureMutation.isPending}
                            onClick={() => {
                              paramoptScenarioEnsureMutation.mutate({
                                ensure_missing_only: true,
                                max_batches: 3,
                                source: 'ui',
                                apply_live: true,
                                confirm_live: true,
                                rollback_after_apply: true,
                                policy_ref: 'gov_default',
                                budget: { n_init: 3, n_iter: 10, skip_robustness: true, auto_draft: true, no_manual_approval: false },
                              });
                            }}
                          >
                            {paramoptScenarioEnsureMutation.isPending ? '执行中…' : '补齐并尝试应用（自动审批，自动回滚）'}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!canWriteConfig || paramoptSmokeApplyMutation.isPending}
                            onClick={() => { paramoptSmokeApplyMutation.mutate(); }}
                          >
                            {paramoptSmokeApplyMutation.isPending ? '执行中…' : '实盘链路自检（自动回滚）'}
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => setParamoptScenarioEnsureShowRaw((v) => !v)}>
                            {paramoptScenarioEnsureShowRaw ? '隐藏补齐结果' : '显示补齐结果'}
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => setParamoptSmokeApplyShowRaw((v) => !v)}>
                            {paramoptSmokeApplyShowRaw ? '隐藏自检结果' : '显示自检结果'}
                          </Button>
                        </div>
                        {!paramoptScenarioEnsureShowRaw ? null : (
                          <div className="mt-2 rounded border bg-white px-2 py-2">
                            <pre className="text-xs overflow-auto max-h-[300px] whitespace-pre-wrap">{JSON.stringify(paramoptScenarioEnsureMutation.data ?? null, null, 2)}</pre>
                          </div>
                        )}
                        {!paramoptSmokeApplyShowRaw ? null : (
                          <div className="mt-2 rounded border bg-white px-2 py-2">
                            <pre className="text-xs overflow-auto max-h-[300px] whitespace-pre-wrap">{JSON.stringify(paramoptSmokeApplyMutation.data ?? null, null, 2)}</pre>
                          </div>
                        )}
                      </div>

                      <div className="rounded border bg-white px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-xs text-slate-600">阶段结果（可折叠）</div>
                          <Button size="sm" variant="outline" onClick={() => setParamoptShowAllStages((v) => !v)}>
                            {paramoptShowAllStages ? '收起' : '展开更多'}
                          </Button>
                        </div>
                        <div className="mt-2 space-y-2 text-xs">
                          {pickedStageSummaries.length ? pickedStageSummaries.map((s, i) => (
                            <div key={`${String(s.trace_id ?? i)}`} className="rounded border bg-slate-50 px-2 py-2">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="truncate">{String(s.preset ?? '-')}</div>
                                <span className="flex items-center gap-2">
                                  <Badge variant={String(s.route) === 'auto_rejected' ? 'destructive' : 'outline'}>{String(s.route ?? '-')}</Badge>
                                  <Badge variant={s.ok ? 'secondary' : 'destructive'}>{s.ok ? 'ok' : 'fail'}</Badge>
                                </span>
                              </div>
                              <div className="mt-1 text-slate-600 break-all">
                                policy={String(s.policy_decision ?? '-')} / gate_pass={String(s.gate_pass ?? '-')} / approval={String(s.approval_id ?? '-')} / apply_mode={String(s.apply_mode ?? '-')} / auto_apply_ok={String(s.auto_apply_ok ?? '-')}
                              </div>
                              <div className="mt-1 text-slate-600 break-all">
                                best_max={String(s.best_max ?? '-')} / patch_keys={String(s.patch_keys_n ?? '-')} / suggest_keys={String(s.suggest_keys_n ?? '-')}
                              </div>
                            </div>
                          )) : <div className="text-slate-400">-</div>}
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <Button size="sm" variant="outline" onClick={() => setParamoptShowRaw((v) => !v)}>
                          {paramoptShowRaw ? '隐藏原始 JSON' : '显示原始 JSON'}
                        </Button>
                      </div>
                      {paramoptShowRaw ? (
                        <div className="rounded border bg-white px-2 py-2">
                          <pre className="text-xs overflow-auto max-h-[420px] whitespace-pre-wrap">{JSON.stringify(details, null, 2)}</pre>
                        </div>
                      ) : null}
                    </div>
                  );
                })()}
              </CardContent>
            </Card>
          ) : null}
          {String(selectedCard.card_id) === 'other' ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="truncate">最新修复 Bug（按 FAQ 命中归因）</span>
                  <span className="flex items-center gap-2">
                    <Badge variant="outline">rca.jsonl</Badge>
                    <Button size="sm" variant="outline" onClick={() => { void rcaTailQuery.refetch(); }}>
                      刷新
                    </Button>
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {rcaTailQuery.isLoading ? (
                  <div className="text-slate-600">正在加载…</div>
                ) : rcaTailQuery.error ? (
                  <div className="text-red-700">加载失败：{String((rcaTailQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}</div>
                ) : null}

                {!rcaTailQuery.isLoading && !rcaTailQuery.error && sysMonReports.length <= 0 ? (
                  <div className="rounded border bg-white px-3 py-2 text-xs text-slate-600">
                    rca.jsonl 暂无记录（后端返回 404 会被视为“空”）。可点击卡片里的“运行检查（沙箱）”生成 system.monitor.report。
                  </div>
                ) : null}

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2 text-xs">
                  <div className="rounded border bg-white px-2 py-2">
                    <div className="text-slate-600">24h 事件</div>
                    <div>{sysMonCardsView.win24h.length}</div>
                  </div>
                  <div className="rounded border bg-white px-2 py-2">
                    <div className="text-slate-600">24h 自动修复</div>
                    <div>{sysMonCardsView.fixed.length}{Number.isFinite(sysMonCardsView.successRate) ? ` / ${(sysMonCardsView.successRate * 100).toFixed(1)}%` : ''}</div>
                  </div>
                  <div className="rounded border bg-white px-2 py-2">
                    <div className="text-slate-600">24h 待审批 / 草案</div>
                    <div>{sysMonCardsView.needAppr.length} / {sysMonCardsView.draft.length}</div>
                  </div>
                  <div className="rounded border bg-white px-2 py-2">
                    <div className="text-slate-600">24h 严重度</div>
                    <div>P1 {sysMonCardsView.p1.length} / P2 {sysMonCardsView.p2.length} / P3 {sysMonCardsView.p3.length}</div>
                  </div>
                </div>

                <div className="rounded border bg-white px-3 py-2 text-xs text-slate-600">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>最近一次：{sysMonCardsView.lastAge}</div>
                    <div className="text-slate-500">仅展示最近 200 条 outbox tail 中的 system.monitor.report</div>
                  </div>
                </div>

                {!sysMonReports.length && !rcaTailQuery.isLoading ? (
                  <div className="text-slate-600">暂无 system.monitor.report 记录。</div>
                ) : (
                  <div className="space-y-2">
                    {sysMonReports.slice(0, 30).map((x) => {
                      const rep = x.report;
                      const hits = Array.isArray(rep.summary?.faq_hits) ? rep.summary!.faq_hits!.map((h) => String(h)).filter((h) => h.trim()) : [];
                      const hits2 = Array.isArray(rep.triage?.faq_hits) ? rep.triage!.faq_hits!.map((h) => String(h)).filter((h) => h.trim()) : [];
                      const faq = hits.length ? hits : hits2;
                      const fixed = rep.auto_exec?.ok === true;
                      const approvalId = String(rep.summary?.approval_id ?? '').trim();
                      const draftId = String(rep.summary?.changeset_draft_id ?? '').trim();
                      const statusLabel = fixed ? 'AUTO_FIXED' : (approvalId ? 'PENDING_APPROVAL' : (draftId ? 'DRAFT_READY' : 'TRIAGED'));
                      const open = sysMonOpen[x.id] ?? false;
                      const pair = String(rep.pair ?? '-');
                      const strategy = String(rep.strategy ?? '-');
                      const linkOk = rep.summary?.link_check_ok;
                      const btOk = rep.summary?.backtest_ok;
                      const preauth = rep.summary?.preauthorized_allowed;

                      return (
                        <div key={x.id} className="rounded border bg-slate-50 px-2 py-2">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => setSysMonOpen((m) => ({ ...m, [x.id]: !m[x.id] }))}
                              >
                                {open ? '收起' : '展开'}
                              </Button>
                              <Badge variant={x.severity === 'P1' ? 'destructive' : (x.severity === 'P2' ? 'secondary' : 'outline')}>{x.severity}</Badge>
                              <Badge variant={fixed ? 'secondary' : 'outline'}>{statusLabel}</Badge>
                              <Badge variant="outline">{_msAgo(nowMs, x.ts_ms)}</Badge>
                              <span className="text-slate-700">{pair}</span>
                              <span className="text-slate-500 truncate">{strategy}</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                              <Link to={`/agent/ops?trace_id=${encodeURIComponent(String(x.trace_id))}#pipeline`}>
                                <Button size="sm" variant="outline">流水线</Button>
                              </Link>
                              <Link to={`/agent/ops?trace_id=${encodeURIComponent(String(x.trace_id))}#trace_replay`}>
                                <Button size="sm" variant="outline">回放</Button>
                              </Link>
                            </div>
                          </div>

                          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                            <span className="text-slate-600">FAQ 命中：</span>
                            {faq.length ? faq.slice(0, 8).map((h) => (
                              <Badge key={`${x.id}_${h}`} variant="outline">{h}</Badge>
                            )) : <span className="text-slate-400">未命中</span>}
                          </div>

                          {!open ? null : (
                            <div className="mt-2 grid grid-cols-1 lg:grid-cols-2 gap-2 text-xs">
                              <div className="rounded border bg-white px-2 py-2">
                                <div className="text-slate-600 mb-1">状态摘要</div>
                                <div className="space-y-1">
                                  <div>trace_id: <span className="text-slate-700">{String(x.trace_id)}</span></div>
                                  <div>link_check_ok: <span className="text-slate-700">{linkOk == null ? '-' : (linkOk ? 'true' : 'false')}</span></div>
                                  <div>backtest_ok: <span className="text-slate-700">{btOk == null ? '-' : (btOk ? 'true' : 'false')}</span></div>
                                  <div>preauthorized_allowed: <span className="text-slate-700">{preauth == null ? '-' : (preauth ? 'true' : 'false')}</span></div>
                                  <div>draft_id: <span className="text-slate-700">{draftId || '-'}</span></div>
                                  <div>approval_id: <span className="text-slate-700">{approvalId || '-'}</span></div>
                                </div>
                              </div>
                              <div className="rounded border bg-white px-2 py-2">
                                <div className="text-slate-600 mb-1">拟变更（stopgap）</div>
                                <pre className="text-xs overflow-auto max-h-[260px] whitespace-pre-wrap">
                                  {rep.triage?.proposed_config_patch && Object.keys(rep.triage.proposed_config_patch).length
                                    ? JSON.stringify(rep.triage.proposed_config_patch, null, 2)
                                    : '-'}
                                </pre>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          ) : null}
          {String(selectedCard.card_id) === 'gtw_global_workflow' && gtwTraceId ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="truncate">GTW 决策包与回执</span>
                  <Badge variant="outline">trace {gtwTraceId.slice(0, 10)}…</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => setGtwShowRaw((v) => !v)}>
                    {gtwShowRaw ? '隐藏原始 JSON' : '显示原始 JSON'}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => { void gtwDecisionPkgQuery.refetch(); void gtwTriggeredQuery.refetch(); }}>
                    刷新决策包
                  </Button>
                </div>

                {gtwDecisionPkgQuery.isLoading ? (
                  <div className="text-slate-600">正在加载决策包…</div>
                ) : gtwDecisionPkgQuery.error ? (
                  <div className="text-red-700">决策包加载失败：{String((gtwDecisionPkgQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}</div>
                ) : !gtwLatestDecisionPkgItem ? (
                  <div className="text-slate-600">暂无 gtw.decision_package 产物。</div>
                ) : (
                  (() => {
                    const item = gtwLatestDecisionPkgItem as Record<string, unknown>;
                    const pkg = (item.artifact && typeof item.artifact === 'object') ? (item.artifact as Record<string, unknown>) : null;
                    const analysis = (pkg && typeof pkg.analysis === 'object' && pkg.analysis) ? (pkg.analysis as Record<string, unknown>) : null;
                    const macro = (analysis && typeof analysis.macro === 'object' && analysis.macro) ? (analysis.macro as Record<string, unknown>) : null;
                    const pathSel = (pkg && typeof pkg.path_selection === 'object' && pkg.path_selection) ? (pkg.path_selection as Record<string, unknown>) : null;
                    const scores = (pathSel && Array.isArray(pathSel.scores)) ? (pathSel.scores as Array<Record<string, unknown>>) : [];
                    const chosen = (pathSel && Array.isArray(pathSel.chosen_path_ids)) ? (pathSel.chosen_path_ids as unknown[]).map((x) => String(x)).filter((x) => x.trim()) : [];
                    const pathPlans = (pkg && Array.isArray(pkg.path_plans)) ? (pkg.path_plans as Array<Record<string, unknown>>) : [];
                    const createdAt = Number(pkg?.created_at_ms ?? 0);
                    const decisionId = String(pkg?.decision_id ?? '').trim();

                    const macroRegime = String(macro?.regime ?? '').trim() || '-';
                    const macroConf = Number(macro?.confidence ?? NaN);
                    const macroPersistence = Number(macro?.regime_persistence ?? NaN);
                    const macroSwitchScore = Number(macro?.regime_switch_score ?? NaN);
                    const macroDwell = Number(macro?.transition_min_dwell_cycles ?? NaN);

                    const topScores = scores
                      .map((s) => ({
                        path_id: String(s?.path_id ?? '').trim(),
                        score: Number(s?.score ?? NaN),
                        top_rules: Array.isArray(s?.top_rules) ? (s.top_rules as unknown[]).map((x) => String(x)).filter((x) => x.trim()).slice(0, 6) : [],
                      }))
                      .filter((x) => x.path_id)
                      .sort((a, b) => (Number.isFinite(b.score) ? b.score : -1e9) - (Number.isFinite(a.score) ? a.score : -1e9))
                      .slice(0, 5);

                    const chosenPlans = chosen.length
                      ? pathPlans.filter((p) => chosen.includes(String(p?.path_id ?? '').trim()))
                      : pathPlans;

                    return (
                      <div className="space-y-3">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                          <div className="rounded border bg-white px-2 py-2">
                            <div className="text-slate-600">decision_id</div>
                            <div className="truncate">{decisionId || '-'}</div>
                          </div>
                          <div className="rounded border bg-white px-2 py-2">
                            <div className="text-slate-600">created_at</div>
                            <div className="truncate">{createdAt > 0 ? _msAgo(nowMs, createdAt) : '-'}</div>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                          <div className="rounded border bg-white px-3 py-2">
                            <div className="text-xs text-slate-600 mb-2">macro</div>
                            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                              <div className="text-slate-600">regime</div><div className="truncate">{macroRegime}</div>
                              <div className="text-slate-600">confidence</div><div className="truncate">{Number.isFinite(macroConf) ? macroConf.toFixed(3) : '-'}</div>
                              <div className="text-slate-600">persistence</div><div className="truncate">{Number.isFinite(macroPersistence) ? String(Math.floor(macroPersistence)) : '-'}</div>
                              <div className="text-slate-600">switch_score</div><div className="truncate">{Number.isFinite(macroSwitchScore) ? macroSwitchScore.toFixed(3) : '-'}</div>
                              <div className="text-slate-600">transition_dwell</div><div className="truncate">{Number.isFinite(macroDwell) ? String(Math.floor(macroDwell)) : '-'}</div>
                            </div>
                          </div>

                          <div className="rounded border bg-white px-3 py-2">
                            <div className="text-xs text-slate-600 mb-2">path_selection</div>
                            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                              <div className="text-slate-600">method</div><div className="truncate">{String(pathSel?.method ?? '-')}</div>
                              <div className="text-slate-600">chosen</div><div className="truncate">{chosen.length ? chosen.join(', ') : '-'}</div>
                            </div>
                            <div className="mt-2 space-y-1 text-xs">
                              {topScores.length ? topScores.map((x) => (
                                <div key={x.path_id} className="flex items-center justify-between gap-2">
                                  <span className="truncate">{x.path_id}</span>
                                  <span className="text-slate-600 truncate">{Number.isFinite(x.score) ? x.score.toFixed(3) : '-'}</span>
                                  <span className="text-slate-500 truncate">{x.top_rules.length ? x.top_rules.join(', ') : '-'}</span>
                                </div>
                              )) : <div className="text-slate-400">-</div>}
                            </div>
                          </div>
                        </div>

                        <div className="rounded border bg-white px-3 py-2">
                          <div className="text-xs text-slate-600 mb-2">observe / rollback</div>
                          <div className="space-y-2">
                            {chosenPlans.length ? chosenPlans.map((p) => {
                              const pid = String(p?.path_id ?? '').trim() || '-';
                              const enabled = Boolean(p?.enabled);
                              const dis = String(p?.disabled_reason ?? '').trim() || null;
                              const plan = (p.plan && typeof p.plan === 'object') ? (p.plan as Record<string, unknown>) : null;
                              const observe = (plan && plan.observe_criteria && typeof plan.observe_criteria === 'object') ? (plan.observe_criteria as Record<string, unknown>) : null;
                              const rollback = (plan && plan.rollback && typeof plan.rollback === 'object') ? (plan.rollback as Record<string, unknown>) : null;
                              const rbCond = (rollback && rollback.conditions && typeof rollback.conditions === 'object') ? (rollback.conditions as Record<string, unknown>) : null;
                              const appr = (plan && plan.approval && typeof plan.approval === 'object') ? (plan.approval as Record<string, unknown>) : null;
                              const apprReq = Boolean(appr?.required);
                              const minTrades = Number(observe?.min_trades ?? NaN);
                              const minDur = Number(observe?.min_duration_sec ?? NaN);
                              return (
                                <div key={pid} className="rounded border bg-slate-50 px-2 py-2 text-xs">
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="truncate">{pid}</div>
                                    <span className="flex items-center gap-2">
                                      <Badge variant={enabled ? 'secondary' : 'outline'}>{enabled ? 'enabled' : 'disabled'}</Badge>
                                      <Badge variant="outline">{apprReq ? 'approval' : 'no_approval'}</Badge>
                                    </span>
                                  </div>
                                  {dis ? <div className="text-slate-600 mt-1 truncate">disabled_reason: {dis}</div> : null}
                                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
                                    <div className="rounded border bg-white px-2 py-2">
                                      <div className="text-slate-600">observe</div>
                                      <div className="mt-1 text-slate-700">
                                        min_trades {Number.isFinite(minTrades) ? String(Math.floor(minTrades)) : '-'} / min_duration {_secToHuman(minDur)}
                                      </div>
                                      {observe?.targets ? <div className="mt-1 text-slate-600 truncate">targets: {JSON.stringify(observe.targets)}</div> : null}
                                    </div>
                                    <div className="rounded border bg-white px-2 py-2">
                                      <div className="text-slate-600">rollback</div>
                                      <div className="mt-1 text-slate-700 truncate">
                                        {rbCond ? JSON.stringify(rbCond) : '-'}
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              );
                            }) : <div className="text-xs text-slate-400">-</div>}
                          </div>
                        </div>

                        {gtwShowRaw ? (
                          <div className="rounded border bg-white px-2 py-2">
                            <div className="text-slate-600 text-xs mb-1">gtw.decision_package (raw)</div>
                            <pre className="text-xs overflow-auto max-h-[420px] whitespace-pre-wrap">{JSON.stringify(pkg, null, 2)}</pre>
                          </div>
                        ) : null}
                      </div>
                    );
                  })()
                )}

                {gtwTriggeredQuery.isLoading ? (
                  <div className="text-slate-600">正在加载触发回执…</div>
                ) : gtwTriggeredQuery.error ? (
                  <div className="text-red-700">触发回执加载失败：{String((gtwTriggeredQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}</div>
                ) : !gtwLatestTriggeredItem ? (
                  <div className="text-slate-600">暂无 gtw.triggered 产物。</div>
                ) : (
                  (() => {
                    const item = gtwLatestTriggeredItem as Record<string, unknown>;
                    const art = (item.artifact && typeof item.artifact === 'object') ? (item.artifact as Record<string, unknown>) : null;
                    const triggered = (art && Array.isArray(art.triggered)) ? (art.triggered as Array<Record<string, unknown>>) : [];
                    return (
                      <div className="rounded border bg-white px-3 py-2">
                        <div className="text-xs text-slate-600 mb-2">triggered</div>
                        {triggered.length ? (
                          <div className="space-y-1 text-xs">
                            {triggered.map((t, i) => {
                              const pid = String(t?.path_id ?? '-');
                              const st = String(t?.status ?? (t?.ok ? 'DONE' : 'FAIL'));
                              const http = Number(t?.http ?? NaN);
                              const tr = String(t?.trace_id ?? '').trim();
                              const sum = String(t?.summary ?? '').trim();
                              return (
                                <div key={`${pid}_${i}`} className="flex flex-wrap items-center justify-between gap-2 rounded border bg-slate-50 px-2 py-2">
                                  <div className="truncate">{pid}</div>
                                  <span className="flex items-center gap-2">
                                    <Badge variant={String(st).toUpperCase() === 'FAIL' ? 'destructive' : 'secondary'}>{st}</Badge>
                                    <Badge variant="outline">{Number.isFinite(http) ? `http ${http}` : 'http -'}</Badge>
                                  </span>
                                  {tr ? <div className="text-slate-600 truncate">trace {tr.slice(0, 10)}…</div> : <div className="text-slate-400 truncate">trace -</div>}
                                  {sum ? <div className="text-slate-600 truncate">{sum}</div> : <div className="text-slate-400 truncate">-</div>}
                                </div>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="text-xs text-slate-400">-</div>
                        )}
                        {gtwShowRaw ? (
                          <div className="rounded border bg-white px-2 py-2 mt-2">
                            <div className="text-slate-600 text-xs mb-1">gtw.triggered (raw)</div>
                            <pre className="text-xs overflow-auto max-h-[260px] whitespace-pre-wrap">{JSON.stringify(art, null, 2)}</pre>
                          </div>
                        ) : null}
                      </div>
                    );
                  })()
                )}
              </CardContent>
            </Card>
          ) : null}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {!isExplore ? null : (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="truncate">Explore：一键松绑（宽泛探索）</span>
                  <Badge variant="outline">dry_run</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="text-sm text-slate-600">
                  一键放宽交易对范围、去重/冷却、阈值、并发与限速（Explore 强制 dry_run，不触达实盘）。
                </div>
                {!envMismatch ? null : (
                  <div className="text-xs text-amber-700 break-words">
                    环境不一致：ui_env={uiEnv}，backend_env={backendEnvNorm || '-'}。这通常意味着前端代理指向了非 Explore 后端端口。
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    disabled={!canWriteConfig || exploreMutation.isPending}
                    onClick={async () => {
                      if (!canWriteConfig) return;
                      setExploreApplyResult('');
                      await exploreMutation.mutateAsync();
                    }}
                  >
                    立即应用
                  </Button>
                </div>
                {!canWriteConfig ? (
                  <div className="text-xs text-amber-700 break-words">
                    未检测到可写权限：请先 Admin 登录或填入 Operator Token（CONFIG_TOKEN / MAINTENANCE_TOKEN）。
                  </div>
                ) : null}
                {!exploreApplyResult ? null : (
                  <div className="text-xs font-mono text-slate-600 break-all">{exploreApplyResult}</div>
                )}
              </CardContent>
            </Card>
          )}
          {orderedCards.map((c) => renderCard(c))}
        </div>
      )}
    </div>
  );
};
