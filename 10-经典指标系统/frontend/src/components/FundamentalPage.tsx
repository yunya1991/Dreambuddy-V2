import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Outlet, useLocation } from 'react-router-dom';
import {
  fetchFundamentalNewsAnchorDeltaViewLatest,
  fetchFundamentalNewsAutomationState,
  fetchFundamentalNewsBriefLatest,
  fetchFundamentalNewsEvaluationHistory,
  fetchFundamentalNewsEventLedgerLatest,
  fetchFundamentalNewsRiskActionEventsLatest,
  runFundamentalNewsAutomationNow,
  setFundamentalNewsAutomationConfig,
  type FundamentalNewsAnchorDeltaViewResponse,
  type FundamentalNewsAutomationStateResponse,
  type FundamentalNewsBriefResponse,
  type FundamentalNewsEvaluationHistoryResponse,
  type FundamentalNewsEventLedgerItem,
  type FundamentalNewsRiskActionItem,
} from '../lib/api';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Tabs, TabsList, TabsTrigger } from './ui/tabs';

const FundamentalTabs: React.FC = () => {
  const loc = useLocation();
  const current = String(loc.pathname || '').trim();
  const isActive = (p: string) => current === p;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Link to="/fundamental/news">
        <Button variant={isActive('/fundamental/news') ? 'secondary' : 'ghost'}>新闻分析</Button>
      </Link>
    </div>
  );
};

export const FundamentalNewsPage: React.FC = () => {
  const qc = useQueryClient();
  const [periodHours, setPeriodHours] = useState<number>(4);
  const [periodDirty, setPeriodDirty] = useState<boolean>(false);
  const [newsView, setNewsView] = useState<'brief' | 'research'>('brief');
  const [briefExpanded, setBriefExpanded] = useState<boolean>(false);
  const [keyword, setKeyword] = useState<string>('');
  const [eventFilter, setEventFilter] = useState<string>('all');
  const [collapsedCards, setCollapsedCards] = useState<Record<string, boolean>>({});
  const isCollapsed = (id: string): boolean => Boolean(collapsedCards[id]);
  const toggleCollapsed = (id: string) => setCollapsedCards((s) => ({ ...s, [id]: !s[id] }));

  const automationQuery = useQuery({
    queryKey: ['fundamental', 'news', 'automation', 'state'],
    queryFn: () => fetchFundamentalNewsAutomationState(),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const latestNames = useMemo(() => {
    const latest = (automationQuery.data?.latest && typeof automationQuery.data.latest === 'object')
      ? (automationQuery.data.latest as Record<string, unknown>)
      : {};
    const _get = (k: string): string => {
      const node = latest[k];
      if (!node || typeof node !== 'object') return '';
      return String((node as Record<string, unknown>).name ?? '').trim();
    };
    return { brief: _get('brief'), eventLedger: _get('event_ledger'), riskEvents: _get('risk_action_events') };
  }, [automationQuery.data]);
  const briefQuery = useQuery({
    queryKey: ['fundamental', 'news', 'brief', latestNames.brief || ''],
    queryFn: () => fetchFundamentalNewsBriefLatest({ name: latestNames.brief || undefined, max_chars: 120000 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const ledgerQuery = useQuery({
    queryKey: ['fundamental', 'news', 'event_ledger', latestNames.eventLedger || ''],
    queryFn: () => fetchFundamentalNewsEventLedgerLatest({ name: latestNames.eventLedger || undefined, limit: 80 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const riskQuery = useQuery({
    queryKey: ['fundamental', 'news', 'risk_action', latestNames.riskEvents || ''],
    queryFn: () => fetchFundamentalNewsRiskActionEventsLatest({ name: latestNames.riskEvents || undefined, limit: 80 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const anchorDeltaQuery = useQuery({
    queryKey: ['fundamental', 'news', 'anchor_delta'],
    queryFn: () => fetchFundamentalNewsAnchorDeltaViewLatest(),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const evaluationQuery = useQuery({
    queryKey: ['fundamental', 'news', 'evaluation'],
    queryFn: () => fetchFundamentalNewsEvaluationHistory({ limit: 120, anchor_hour: 8 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const saveScheduleMut = useMutation({
    mutationFn: async (enabled: boolean) => setFundamentalNewsAutomationConfig({ enabled, period_hours: periodHours, window_hours: periodHours }),
    onSuccess: async (resp) => {
      const ph = Number(resp?.period_hours ?? NaN);
      if (Number.isFinite(ph) && ph > 0) setPeriodHours(ph);
      setPeriodDirty(false);
      await qc.invalidateQueries({ queryKey: ['fundamental', 'news'] });
    },
  });
  const runNowMut = useMutation({
    mutationFn: async () => runFundamentalNewsAutomationNow({ hours: periodHours, trigger_event: 'ui_manual' }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['fundamental', 'news'] });
    },
  });

  const payload = useMemo<FundamentalNewsBriefResponse | null>(() => (briefQuery.data && typeof briefQuery.data === 'object') ? (briefQuery.data as FundamentalNewsBriefResponse) : null, [briefQuery.data]);
  const autoPayload = useMemo<FundamentalNewsAutomationStateResponse | null>(() => (automationQuery.data && typeof automationQuery.data === 'object') ? (automationQuery.data as FundamentalNewsAutomationStateResponse) : null, [automationQuery.data]);
  const anchorPayload = useMemo<FundamentalNewsAnchorDeltaViewResponse | null>(() => (anchorDeltaQuery.data && typeof anchorDeltaQuery.data === 'object') ? (anchorDeltaQuery.data as FundamentalNewsAnchorDeltaViewResponse) : null, [anchorDeltaQuery.data]);
  const evaluationPayload = useMemo<FundamentalNewsEvaluationHistoryResponse | null>(() => (evaluationQuery.data && typeof evaluationQuery.data === 'object') ? (evaluationQuery.data as FundamentalNewsEvaluationHistoryResponse) : null, [evaluationQuery.data]);
  const ledgerRows = useMemo<FundamentalNewsEventLedgerItem[]>(() => {
    const rows = Array.isArray(ledgerQuery.data?.items) ? ledgerQuery.data.items : [];
    return rows.slice(0, 60);
  }, [ledgerQuery.data]);
  const riskRows = useMemo<FundamentalNewsRiskActionItem[]>(() => {
    const rows = Array.isArray(riskQuery.data?.items) ? riskQuery.data.items : [];
    return rows.slice(0, 60);
  }, [riskQuery.data]);
  const content = String(payload?.content ?? '').trim();
  const contentPreview = useMemo(() => content ? content.split('\n').slice(0, 38).join('\n') : '', [content]);
  const sectionBlocks = useMemo<Array<{ key: string; title: string; markdown: string }>>(() => {
    const names = ['链上数据', '大 V 观点', '项目动态', '宏观政策与市场', '跨市场联动'];
    return names.map((name) => {
      const idx = content.indexOf(name);
      if (idx < 0) return { key: name, title: name, markdown: '' };
      const next = names.map((n) => content.indexOf(n, idx + name.length)).filter((x) => x > idx);
      const end = next.length ? Math.min(...next) : content.length;
      return { key: name, title: name, markdown: content.slice(idx, end).trim() };
    }).filter((x) => Boolean(x.markdown));
  }, [content]);
  const signal = useMemo(() => {
    const line = content.split('\n').find((x) => x.includes('综合信号') || x.includes('Signal')) || '';
    return line || '-';
  }, [content]);
  const autoEnabled = Boolean(autoPayload?.enabled);
  const autoRunning = Boolean((autoPayload?.state as { running?: boolean } | undefined)?.running);
  const autoStateText = autoRunning ? 'running' : (autoEnabled ? 'enabled' : 'disabled');
  const latestBriefName = String((((autoPayload?.latest as Record<string, unknown> | undefined)?.brief as Record<string, unknown> | undefined)?.name ?? '')).trim();
  const latestLedgerName = String((((autoPayload?.latest as Record<string, unknown> | undefined)?.event_ledger as Record<string, unknown> | undefined)?.name ?? '')).trim();
  const latestRiskName = String((((autoPayload?.latest as Record<string, unknown> | undefined)?.risk_action_events as Record<string, unknown> | undefined)?.name ?? '')).trim();
  const latestViewName = String((((autoPayload?.latest as Record<string, unknown> | undefined)?.anchor_delta_view as Record<string, unknown> | undefined)?.name ?? '')).trim();
  const eventTypes = useMemo(() => {
    const s = new Set<string>();
    for (const r of ledgerRows) if (String(r.event_type || '').trim()) s.add(String(r.event_type));
    for (const r of riskRows) if (String(r.event_type || '').trim()) s.add(String(r.event_type));
    return ['all', ...Array.from(s)];
  }, [ledgerRows, riskRows]);
  const filteredLedger = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return ledgerRows.filter((r) => {
      const et = String(r.event_type ?? '').trim();
      const title = String(r.title ?? '').toLowerCase();
      if (eventFilter !== 'all' && et !== eventFilter) return false;
      if (kw && !title.includes(kw)) return false;
      return true;
    });
  }, [ledgerRows, eventFilter, keyword]);
  const filteredRisk = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return riskRows.filter((r) => {
      const et = String(r.event_type ?? '').trim();
      const title = String(r.title ?? '').toLowerCase();
      if (eventFilter !== 'all' && et !== eventFilter) return false;
      if (kw && !title.includes(kw)) return false;
      return true;
    });
  }, [riskRows, eventFilter, keyword]);
  const evaluationRows = useMemo(() => Array.isArray(evaluationPayload?.rows) ? evaluationPayload.rows : [], [evaluationPayload]);
  const panelCard = 'rounded-2xl border-slate-200/80 shadow-sm bg-white';
  const subCard = 'rounded-xl border-slate-200/80 bg-slate-50/40';
  const renderCollapseBtn = (id: string) => (
    <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => toggleCollapsed(id)}>
      {isCollapsed(id) ? '展开' : '折叠'}
    </Button>
  );

  return (
    <div className="space-y-5">
      <Tabs value={newsView} onValueChange={(v) => setNewsView(v === 'research' ? 'research' : 'brief')}>
        <TabsList className="rounded-xl border bg-slate-50 p-1">
          <TabsTrigger value="brief">简报视图</TabsTrigger>
          <TabsTrigger value="research">数据化研究</TabsTrigger>
        </TabsList>
      </Tabs>

      <div className={newsView === 'brief' ? 'space-y-4' : 'hidden'}>
        <Card className={panelCard}>
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2">
              <span className="text-[15px] font-semibold tracking-wide">新闻分析（SKILL 产物）</span>
              <div className="flex items-center gap-2 text-xs">
                <Badge variant={briefQuery.isFetching ? 'secondary' : 'outline'} className="rounded-full">{briefQuery.isFetching ? 'refreshing' : 'ready'}</Badge>
                <Button variant="outline" size="sm" onClick={() => { void briefQuery.refetch(); void ledgerQuery.refetch(); void riskQuery.refetch(); void anchorDeltaQuery.refetch(); void evaluationQuery.refetch(); }} disabled={briefQuery.isFetching}>刷新</Button>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(320px,1fr)]">
              <div className="space-y-4">
                <Card className={subCard}><CardHeader className="pb-2"><CardTitle className="flex items-center justify-between gap-2 text-sm"><span>头版摘要</span>{renderCollapseBtn('headline')}</CardTitle></CardHeader>{!isCollapsed('headline') ? <CardContent className="text-xs leading-6">{signal}</CardContent> : null}</Card>
                <Card className={subCard}>
                  <CardHeader className="pb-2"><CardTitle className="flex items-center justify-between gap-2 text-sm"><span>Gate 新闻速递（Gate News Briefing）</span>{renderCollapseBtn('gate_briefing')}</CardTitle></CardHeader>
                  {!isCollapsed('gate_briefing') ? <CardContent className="text-xs text-slate-500">当前环境未接入 gate briefing 接口，保留版位与字段结构。</CardContent> : null}
                </Card>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {sectionBlocks.map((sec) => (
                    <Card key={sec.key} className={subCard}><CardHeader className="pb-2"><CardTitle className="flex items-center justify-between gap-2 text-sm"><span>{sec.title}</span>{renderCollapseBtn(`sec_${sec.key}`)}</CardTitle></CardHeader>{!isCollapsed(`sec_${sec.key}`) ? <CardContent className="pt-0"><pre className="whitespace-pre-wrap text-xs leading-6">{sec.markdown}</pre></CardContent> : null}</Card>
                  ))}
                </div>
                <Card className={subCard}>
                  <CardHeader><CardTitle className="flex items-center justify-between gap-2"><span>全文简报（Markdown）</span><div className="flex items-center gap-2">{renderCollapseBtn('full_brief')}<Button type="button" variant="outline" size="sm" onClick={() => setBriefExpanded((v) => !v)}>{briefExpanded ? '折叠全文' : '展开全文'}</Button></div></CardTitle></CardHeader>
                  {!isCollapsed('full_brief') ? <CardContent><pre className="max-h-[520px] overflow-auto whitespace-pre-wrap text-xs leading-6">{briefExpanded ? content : contentPreview}</pre></CardContent> : null}
                </Card>
              </div>
              <div className="space-y-4 xl:sticky xl:top-4 xl:h-fit">
                <Card className={subCard}><CardHeader className="pb-2"><CardTitle className="flex items-center justify-between gap-2 text-sm"><span>信号温度计</span>{renderCollapseBtn('thermo')}</CardTitle></CardHeader>{!isCollapsed('thermo') ? <CardContent className="text-xs"><div className="font-semibold">{String(payload?.quality ?? '-')}</div><div className="mt-1 text-slate-500">{Number.isFinite(Number(payload?.coverage ?? NaN)) ? `${(Number(payload?.coverage) * 100).toFixed(1)}% coverage` : '-'}</div></CardContent> : null}</Card>
                <Card className={subCard}><CardHeader className="pb-2"><CardTitle className="flex items-center justify-between gap-2 text-sm"><span>动态仓位建议</span>{renderCollapseBtn('position_advice')}</CardTitle></CardHeader>{!isCollapsed('position_advice') ? <CardContent className="text-xs"><Badge variant="outline" className="rounded-full">{String(payload?.execution_gate ?? 'readonly_advisory')}</Badge></CardContent> : null}</Card>
                <Card className={subCard}><CardHeader className="pb-2"><CardTitle className="flex items-center justify-between gap-2 text-sm"><span>质量与回执</span>{renderCollapseBtn('receipt')}</CardTitle></CardHeader>{!isCollapsed('receipt') ? <CardContent className="text-xs">{`rows=${evaluationRows.length}`}</CardContent> : null}</Card>
                <Card className={subCard}><CardHeader className="pb-2"><CardTitle className="flex items-center justify-between gap-2 text-sm"><span>风险告警与冲突证据</span>{renderCollapseBtn('risk_evidence')}</CardTitle></CardHeader>{!isCollapsed('risk_evidence') ? <CardContent className="space-y-1 text-xs">{filteredRisk.slice(0, 8).map((r, i) => <div key={`risk_${i}`} className="rounded border border-slate-200 bg-white px-2 py-1">{String(r.title ?? '-')}</div>)}{!filteredRisk.length ? <div className="text-slate-500">暂无冲突证据</div> : null}</CardContent> : null}</Card>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className={panelCard}>
          <CardHeader><CardTitle className="flex items-center justify-between gap-2"><span>新闻产物触发</span><div className="flex items-center gap-2"><Badge variant={autoRunning ? 'secondary' : (autoEnabled ? 'outline' : 'destructive')}>{autoStateText}</Badge>{renderCollapseBtn('trigger_panel')}</div></CardTitle></CardHeader>
          {!isCollapsed('trigger_panel') ? <CardContent className="space-y-3 text-sm">
            <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2 text-xs"><div className="text-slate-500">latest brief</div><div className="mt-1 font-semibold">{latestBriefName || '-'}</div></div>
              <div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2 text-xs"><div className="text-slate-500">latest ledger</div><div className="mt-1 font-semibold">{latestLedgerName || '-'}</div></div>
              <div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2 text-xs"><div className="text-slate-500">latest risk events</div><div className="mt-1 font-semibold">{latestRiskName || '-'}</div></div>
              <div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2 text-xs"><div className="text-slate-500">latest anchor delta view</div><div className="mt-1 font-semibold">{latestViewName || '-'}</div></div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select className="h-9 rounded-lg border bg-white px-2" value={String(periodHours)} onChange={(e) => { setPeriodHours(Number(e.target.value || 4)); setPeriodDirty(true); }}>
                <option value="1">1h（快速增量层）</option><option value="4">4h</option><option value="8">8h</option><option value="12">12h</option><option value="24">24h</option>
              </select>
              <Button type="button" variant="outline" size="sm" disabled={saveScheduleMut.isPending} onClick={() => saveScheduleMut.mutate(true)}>保存定时触发</Button>
              <Button type="button" variant="outline" size="sm" disabled={saveScheduleMut.isPending} onClick={() => saveScheduleMut.mutate(false)}>暂停定时</Button>
              <Button type="button" size="sm" disabled={runNowMut.isPending || autoRunning} onClick={() => runNowMut.mutate()}>{runNowMut.isPending ? '触发中...' : '手动触发'}</Button>
              <Button type="button" variant="outline" size="sm" disabled={runNowMut.isPending || autoRunning} onClick={() => runFundamentalNewsAutomationNow({ hours: 1, trigger_event: 'ui_fast_delta_1h' }).then(() => { void briefQuery.refetch(); void anchorDeltaQuery.refetch(); void evaluationQuery.refetch(); })}>1h 快速更新</Button>
              {periodDirty ? <Badge variant="secondary">周期已修改，待保存</Badge> : null}
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2 text-xs">1h 快速触发评估：当前环境未提供 fast_trigger_eval 接口，保留版位。</div>
          </CardContent> : null}
        </Card>
      </div>

      <div className={newsView === 'research' ? 'space-y-4' : 'hidden'}>
        <Card className={panelCard}><CardHeader><CardTitle className="flex items-center justify-between gap-2"><span>08:00 Anchor + Latest Delta</span>{renderCollapseBtn('anchor_delta')}</CardTitle></CardHeader>{!isCollapsed('anchor_delta') ? <CardContent className="text-xs"><pre className="max-h-[280px] overflow-auto rounded-lg bg-slate-50/60 p-3">{JSON.stringify(anchorPayload?.record ?? {}, null, 2)}</pre></CardContent> : null}</Card>
        <Card className={panelCard}><CardHeader><CardTitle className="flex items-center justify-between gap-2"><span>持续观测（Monitoring）硬验收</span>{renderCollapseBtn('monitoring')}</CardTitle></CardHeader>{!isCollapsed('monitoring') ? <CardContent className="grid grid-cols-1 gap-3 text-xs md:grid-cols-4"><div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2">{`generated_at=${String(payload?.generated_at ?? '-')}`}</div><div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2">{`coverage=${String(payload?.coverage ?? '-')}`}</div><div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2">{`quality=${String(payload?.quality ?? '-')}`}</div><div className="rounded-xl border border-slate-200 bg-slate-50/40 px-3 py-2">{`rows=${evaluationRows.length}`}</div></CardContent> : null}</Card>
        <Card className={panelCard}><CardHeader><CardTitle className="flex items-center justify-between gap-2"><span>Run 级评估图表（Coverage / Quality / 动作时间线）</span>{renderCollapseBtn('run_chart')}</CardTitle></CardHeader>{!isCollapsed('run_chart') ? <CardContent className="space-y-2 text-xs">{evaluationRows.slice(-20).map((r, i) => <div key={`ev_${i}`} className="grid grid-cols-[160px_1fr_90px] items-center gap-2"><div className="text-slate-600">{String(r.generated_at || r.asof || '-')}</div><div className="h-2 rounded bg-slate-100"><div className={`${Number(r.coverage ?? 0) >= 0.5 ? 'bg-emerald-500' : 'bg-rose-500'} h-2 rounded`} style={{ width: `${Math.max(0, Math.min(100, Math.round(Number(r.coverage ?? 0) * 100)))}%` }} /></div><div>{String(r.quality ?? '-')}</div></div>)}</CardContent> : null}</Card>
        <Card className={panelCard}>
          <CardHeader><CardTitle className="flex items-center justify-between gap-2"><span>事件分类主视图</span>{renderCollapseBtn('event_table')}</CardTitle></CardHeader>
          {!isCollapsed('event_table') ? <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <select className="h-9 rounded-lg border bg-white px-2 text-sm" value={eventFilter} onChange={(e) => setEventFilter(String(e.target.value || 'all'))}>{eventTypes.map((x) => <option key={`evt_${x}`} value={x}>{x === 'all' ? '全部事件类型' : x}</option>)}</select>
              <input className="h-9 rounded-lg border px-2 text-sm" placeholder="关键词筛选标题" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
            </div>
            <div className="overflow-auto rounded-xl border border-slate-200">
              <table className="min-w-full text-xs">
                <thead><tr className="bg-slate-50 text-slate-600"><th className="px-2 py-2 text-left font-medium">来源</th><th className="px-2 py-2 text-left font-medium">事件类型</th><th className="px-2 py-2 text-left font-medium">标题</th><th className="px-2 py-2 text-left font-medium">动作</th></tr></thead>
                <tbody>
                  {filteredLedger.slice(0, 80).map((r, i) => <tr key={`l_${i}`} className="border-t"><td className="px-2 py-2">ledger</td><td className="px-2 py-2">{String(r.event_type ?? '-')}</td><td className="px-2 py-2">{String(r.title ?? '-')}</td><td className="px-2 py-2">{String(r.risk_action_proposal ?? '-')}</td></tr>)}
                  {filteredRisk.slice(0, 80).map((r, i) => <tr key={`r_${i}`} className="border-t"><td className="px-2 py-2">risk</td><td className="px-2 py-2">{String(r.event_type ?? '-')}</td><td className="px-2 py-2">{String(r.title ?? '-')}</td><td className="px-2 py-2">{String(r.risk_action_proposal ?? '-')}</td></tr>)}
                </tbody>
              </table>
            </div>
          </CardContent> : null}
        </Card>
        <Card className={panelCard}><CardHeader><CardTitle className="flex items-center justify-between gap-2"><span>相对早餐变化视图（三段式）</span>{renderCollapseBtn('breakfast_delta')}</CardTitle></CardHeader>{!isCollapsed('breakfast_delta') ? <CardContent className="text-xs"><pre className="max-h-[320px] overflow-auto rounded-lg bg-slate-50/60 p-3">{JSON.stringify(anchorPayload ?? {}, null, 2)}</pre></CardContent> : null}</Card>
      </div>
    </div>
  );
};

export const FundamentalPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-2xl font-bold">基本面分析</div>
          <div className="text-sm text-slate-600">先 SKILL 化能力，再按需集成到页面</div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">/fundamental</Badge>
          <Badge variant="secondary">readonly_advisory</Badge>
        </div>
      </div>
      <FundamentalTabs />
      <Outlet />
    </div>
  );
};
