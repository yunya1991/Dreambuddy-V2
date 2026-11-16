'use client';

// 数据研究看板（TASKS-20261116 T8-1 / T8-2 / T8-3 / T8-4 / T8-6）
// 组织轴 = 算法推荐：左列推荐项（D-K01 只读出口），右列该推荐的出口卡。
// 只展示结论与证据，不展示候选枚举 / 淘汰漏斗；不含任何买卖方向。
// 配置（tab / 卡）以服务端为唯一事实源（SPEC-54 R3b），localStorage 仅作离线缓存；
// 「－ / ×」二次确认 + 撤销，只删配置不删能力。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { V3Badge } from '@/components/V3Badge';
import { V3Empty } from '@/components/V3Empty';
import {
  fetchCardsConfig,
  runCapability,
  saveCardsConfig,
  type RunResponse,
} from '@/lib/visual/api';
import {
  CONFIG_VERSION,
  DEFAULT_ACTIVE_TAB,
  defaultTabs,
  loadConfig,
  mergeServerPanels,
  saveConfig,
  tabToServerRows,
} from '@/lib/visual/config';
import {
  MAX_PANELS_PER_TAB,
  MAX_TABS,
  addPanelToTab,
  addTab,
  buildPanelKey,
  removePanelFromTab,
  removeTab,
  type PanelSpec,
  type PanelTab,
} from '@/lib/visual/panelKey';
import { CapabilityCard } from './CapabilityCard';
import { CapabilityPicker } from './CapabilityPicker';

const BASES = ['BTC', 'ETH', 'SOL', 'NVDA', 'XAU'];

type PendingRemoval =
  | { kind: 'panel'; tabId: string; panelKey: string; label: string }
  | { kind: 'tab'; tabId: string; label: string };

interface UndoState {
  tabs: PanelTab[];
  activeId: string;
  label: string;
}

function pickField(row: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (value !== null && value !== undefined && value !== '') return String(value);
  }
  return '—';
}

function formatNumber(value: unknown, digits = 3): string {
  const num = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : '—';
}

export function DataResearchCardBoard() {
  const [tabs, setTabs] = useState<PanelTab[]>(defaultTabs);
  const [activeId, setActiveId] = useState(DEFAULT_ACTIVE_TAB);
  const [hydrated, setHydrated] = useState(false);
  const [base, setBase] = useState('BTC');
  const [rec, setRec] = useState<RunResponse | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [selected, setSelected] = useState(0);
  const [picker, setPicker] = useState<'tab' | 'card' | null>(null);
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState<PendingRemoval | null>(null);
  const [undo, setUndo] = useState<UndoState | null>(null);

  // tab_id → 上次已同步到服务端的行签名；相同则跳过重复 PUT
  const syncedRef = useRef<Map<string, string>>(new Map());

  const syncTab = useCallback((tab: PanelTab, deleted = false) => {
    const rows = tabToServerRows(tab, deleted);
    const signature = JSON.stringify(rows);
    if (!deleted && syncedRef.current.get(tab.id) === signature) return;
    if (deleted) syncedRef.current.delete(tab.id);
    else syncedRef.current.set(tab.id, signature);
    // FAIL-OPEN：网络/鉴权失败只影响跨设备一致性，不阻断看板操作
    saveCardsConfig(tab.id, rows).catch(() => undefined);
  }, []);

  // 首帧用默认配置（SSR / CSR 一致），挂载后再读 localStorage，避免水合不一致
  useEffect(() => {
    let alive = true;
    const config = loadConfig();
    setTabs(config.tabs);
    setActiveId(config.activeId);
    setHydrated(true);

    // SPEC-54 R3b：服务端为唯一事实源；拉取失败或未登录一律回落本地（FAIL-OPEN）
    fetchCardsConfig()
      .then((remote) => {
        if (!alive || !remote.ok || !remote.items?.length) return;
        const merged = mergeServerPanels(config, remote.items);
        setTabs(merged.tabs);
        setActiveId(merged.activeId);
        // 服务端已有记录：按合并结果刷新同步基线，避免挂载后再整页回写
        for (const tab of merged.tabs) {
          syncedRef.current.set(tab.id, JSON.stringify(tabToServerRows(tab)));
        }
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveConfig({ version: CONFIG_VERSION, tabs, activeId });
    for (const tab of tabs) syncTab(tab);
  }, [hydrated, tabs, activeId, syncTab]);

  useEffect(() => {
    let alive = true;
    setRecLoading(true);
    runCapability('D-K01', { target: base, top: 20 })
      .then((response) => {
        if (alive) setRec(response);
      })
      .catch((err: unknown) => {
        if (alive) setRec({ ok: false, reason: err instanceof Error ? err.message : 'fetch_failed' });
      })
      .finally(() => {
        if (alive) setRecLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [base]);

  const rows = useMemo<Record<string, unknown>[]>(() => {
    const data = (rec?.result?.data ?? {}) as Record<string, unknown>;
    // 能力信封把行数据放在 data.capabilities.<id> 下（顶层 rows/items 为兼容旧出口保留）
    const caps = (data.capabilities ?? {}) as Record<string, Record<string, unknown>>;
    const own = caps['D-K01'] ?? Object.values(caps)[0] ?? {};
    const raw =
      data.rows ??
      data.items ??
      data.recommendations ??
      own.rows ??
      own.items ??
      own.relations;
    return Array.isArray(raw) ? (raw as Record<string, unknown>[]) : [];
  }, [rec]);

  const activeTab = tabs.find((tab) => tab.id === activeId) ?? tabs[0];
  const mounted = activeTab.panels.map((panel) => panel.capability_id);
  const current = rows[selected] ?? rows[0];
  const emptyReason =
    rec?.result?.quality?.degraded_reason ||
    rec?.reason ||
    (rec && rec.ok === false ? '推荐出口不可用' : '');

  const atTabLimit = tabs.length >= MAX_TABS;
  const atPanelLimit = activeTab.panels.length >= MAX_PANELS_PER_TAB;

  function handlePick(panel: PanelSpec) {
    if (picker === 'tab') {
      const created = addTab(tabs, panel.title);
      if (!created.added || !created.tabId) {
        setNotice(`tab 已达上限 ${MAX_TABS}`);
        return;
      }
      const nextTabs = created.tabs.map((tab) =>
        tab.id === created.tabId ? addPanelToTab(tab, panel).tab : tab,
      );
      setTabs(nextTabs);
      setActiveId(created.tabId);
      setNotice('');
      setUndo(null);
      return;
    }
    // 推荐总览是 master-detail，卡一律落到「全部出口」，避免挂上却不可见
    const targetId = activeTab.id === 'rec' ? 'all' : activeTab.id;
    const targetTab = tabs.find((tab) => tab.id === targetId) ?? activeTab;
    const result = addPanelToTab(targetTab, panel);
    if (!result.added) {
      setNotice(
        result.reason === 'limit' ? `本 tab 卡片上限 ${MAX_PANELS_PER_TAB}` : '该能力已在本 tab',
      );
      return;
    }
    setTabs(tabs.map((tab) => (tab.id === targetTab.id ? result.tab : tab)));
    setActiveId(targetTab.id);
    setNotice('');
    setUndo(null);
  }

  function requestRemovePanel(panel: PanelSpec) {
    setNotice('');
    setPending({
      kind: 'panel',
      tabId: activeTab.id,
      panelKey: buildPanelKey(panel),
      label: panel.title,
    });
  }

  function requestRemoveTab(tab: PanelTab) {
    setNotice('');
    setPending({ kind: 'tab', tabId: tab.id, label: tab.title });
  }

  function confirmRemoval() {
    if (!pending) return;
    const snapshot: UndoState = {
      tabs,
      activeId,
      label: pending.kind === 'tab' ? `tab「${pending.label}」` : `卡片「${pending.label}」`,
    };
    if (pending.kind === 'tab') {
      const target = tabs.find((tab) => tab.id === pending.tabId);
      if (target) syncTab(target, true);
      const next = removeTab(tabs, pending.tabId);
      setTabs(next);
      if (activeId === pending.tabId) setActiveId(next[0]?.id ?? DEFAULT_ACTIVE_TAB);
    } else {
      setTabs(
        tabs.map((tab) =>
          tab.id === pending.tabId ? removePanelFromTab(tab, pending.panelKey) : tab,
        ),
      );
    }
    setPending(null);
    setUndo(snapshot);
  }

  function handlePanelArgsChange(panel: PanelSpec, args: Record<string, unknown>) {
    // 参数变了 panel_key 就变：视为同一张卡换参，位置不变，由看板统一同步服务端
    setTabs(
      tabs.map((tab) => ({
        ...tab,
        panels: tab.panels.map((item) => (item === panel ? { ...item, args } : item)),
      })),
    );
    setUndo(null);
  }

  function handleUndo() {
    if (!undo) return;
    setTabs(undo.tabs);
    setActiveId(undo.activeId);
    setUndo(null);
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">卡片模式</h1>
          <p className="mt-1 text-xs text-slate-500">
            可自定义 tab 与能力卡，配置随账号同步（本地仅缓存）；不含买卖方向与仓位
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] text-emerald-300">
            零 LLM
          </span>
          <span className="rounded-full border border-slate-800 bg-slate-900 px-2.5 py-0.5 text-[11px] text-slate-400">
            {rows.length} 条推荐
          </span>
          <select
            value={base}
            onChange={(event) => {
              setBase(event.target.value);
              setSelected(0);
            }}
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
          >
            {BASES.map((symbol) => (
              <option key={symbol} value={symbol}>
                {symbol}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setPicker('card')}
            disabled={atPanelLimit}
            title={atPanelLimit ? `本 tab 卡片上限 ${MAX_PANELS_PER_TAB}` : undefined}
            className="rounded-md border border-indigo-500/40 bg-indigo-500/15 px-2.5 py-1 text-xs text-indigo-200 hover:bg-indigo-500/25 disabled:cursor-not-allowed disabled:border-slate-800 disabled:bg-transparent disabled:text-slate-600"
          >
            ＋ 能力库
          </button>
        </div>
      </header>

      <nav className="flex items-center gap-1 overflow-x-auto border-b border-slate-800 pb-1">
        {tabs.map((tab) => (
          <span
            key={tab.id}
            className={`flex shrink-0 items-center rounded-t-md px-3 py-1.5 text-xs ${
              tab.id === activeId
                ? 'bg-indigo-500/10 text-indigo-200'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <button type="button" onClick={() => setActiveId(tab.id)}>
              {tab.title}
              {tab.panels.length > 0 && (
                <span className="ml-1 font-mono text-[10px] opacity-70">{tab.panels.length}</span>
              )}
            </button>
            {!tab.builtin && (
              <button
                type="button"
                title="删除此 tab（只删配置）"
                onClick={() => requestRemoveTab(tab)}
                className="ml-1.5 rounded px-1 text-[11px] text-slate-500 hover:bg-rose-500/10 hover:text-rose-400"
              >
                ×
              </button>
            )}
          </span>
        ))}
        <button
          type="button"
          onClick={() => setPicker('tab')}
          disabled={atTabLimit}
          title={atTabLimit ? `tab 已达上限 ${MAX_TABS}` : undefined}
          className="shrink-0 rounded px-2 py-1 font-mono text-[11px] text-indigo-300 hover:bg-indigo-500/10 disabled:cursor-not-allowed disabled:text-slate-600 disabled:hover:bg-transparent"
        >
          ＋ 新 tab
        </button>
        <span className="ml-auto shrink-0 px-1 font-mono text-[10px] text-slate-600">
          tab {tabs.length}/{MAX_TABS}
        </span>
      </nav>

      {notice && <p className="text-[11px] text-amber-400">{notice}</p>}

      {pending && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-[11px] text-rose-200">
          <span>确认移除{pending.kind === 'tab' ? ' tab ' : '卡片'}「{pending.label}」？只删看板配置，能力仍可从库取回。</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={confirmRemoval}
              className="rounded-md border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 text-rose-200 hover:bg-rose-500/25"
            >
              确认移除
            </button>
            <button
              type="button"
              onClick={() => setPending(null)}
              className="rounded-md border border-slate-700 px-2 py-0.5 text-slate-300 hover:border-slate-500"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {undo && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-[11px] text-slate-300">
          <span>已移除{undo.label}</span>
          <button
            type="button"
            onClick={handleUndo}
            className="rounded-md border border-indigo-500/40 bg-indigo-500/15 px-2 py-0.5 text-indigo-200 hover:bg-indigo-500/25"
          >
            撤销
          </button>
          <button
            type="button"
            onClick={() => setUndo(null)}
            className="rounded-md px-2 py-0.5 text-slate-500 hover:text-slate-300"
          >
            知道了
          </button>
        </div>
      )}

      {activeTab.id === 'rec' ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.6fr)]">
          <section className="rounded-xl border border-slate-800 bg-slate-900/40">
            <div className="flex items-center justify-between border-b border-slate-800/80 px-3.5 py-2.5">
              <div>
                <p className="text-[12.5px] font-medium text-slate-200">算法推荐</p>
                <p className="mt-0.5 text-[10px] text-slate-500">
                  {base} · D-K01 只读出口 · 按 |RankIC| 排序
                </p>
              </div>
              <V3Badge variant="default" label={`${rows.length} 条`} />
            </div>
            <div className="max-h-[560px] overflow-y-auto p-2">
              {recLoading && <div className="h-20 animate-pulse rounded-lg bg-slate-800/40" />}
              {!recLoading && rows.length === 0 && (
                <V3Empty
                  title="暂无通过门禁的推荐"
                  description={emptyReason || '关系评估注册表尚未生成；指标发布后此处自动出现'}
                />
              )}
              {!recLoading &&
                rows.map((row, index) => (
                  <button
                    key={`${pickField(row, ['relation_id', 'eval_id', 'target'])}-${index}`}
                    type="button"
                    onClick={() => setSelected(index)}
                    className={`mb-1 grid w-full grid-cols-[40px_1fr_auto] items-center gap-2 rounded-lg border px-2 py-1.5 text-left ${
                      index === selected
                        ? 'border-indigo-500/45 bg-indigo-500/10'
                        : 'border-transparent hover:border-slate-800 hover:bg-slate-800/30'
                    }`}
                  >
                    <span className="rounded bg-indigo-500/15 px-1 py-0.5 text-center font-mono text-[10px] text-indigo-300">
                      {pickField(row, ['relation_type', 'relation', 'type'])}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-xs text-slate-200">
                        {pickField(row, ['target', 'symbol'])} ·{' '}
                        {pickField(row, ['method', 'method_id', 'pattern'])}
                      </span>
                      <span className="mt-0.5 block truncate font-mono text-[9px] text-slate-500">
                        h{pickField(row, ['horizon', 'h'])} · n{pickField(row, ['sample_n', 'n'])} ·{' '}
                        {pickField(row, ['status'])}
                      </span>
                    </span>
                    <span className="text-right font-mono text-[11px] text-slate-300">
                      {formatNumber(row.rank_ic, 3)}
                      <span className="ml-1 text-[9px] text-slate-500">
                        hit {formatNumber(row.hit_rate, 2)}
                      </span>
                    </span>
                  </button>
                ))}
            </div>
          </section>

          <section className="space-y-3">
            {current ? (
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3.5 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[13px] font-medium text-slate-100">
                      {pickField(current, ['relation_id', 'eval_id'])} ·{' '}
                      {pickField(current, ['target', 'symbol'])}
                    </p>
                    <p className="mt-0.5 text-[10px] text-slate-500">
                      方法 {pickField(current, ['method', 'method_id'])} · h
                      {pickField(current, ['horizon', 'h'])} · n
                      {pickField(current, ['sample_n', 'n'])}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <V3Badge variant="default" label={pickField(current, ['status'])} />
                    <button
                      type="button"
                      onClick={() => setPicker('card')}
                      disabled={atPanelLimit}
                      className="rounded-md border border-indigo-500/40 bg-indigo-500/15 px-2 py-0.5 text-[10px] text-indigo-200 disabled:border-slate-800 disabled:bg-transparent disabled:text-slate-600"
                    >
                      ＋ 出口卡
                    </button>
                  </div>
                </div>
                <dl className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {[
                    ['RankIC', formatNumber(current.rank_ic, 3)],
                    ['hit', formatNumber(current.hit_rate, 2)],
                    ['Wilson 下界', formatNumber(current.hit_rate_lb, 3)],
                    ['holdout', formatNumber(current.holdout_hit_rate, 2)],
                    ['p_adj', formatNumber(current.p_adj, 4)],
                    ['连击', pickField(current, ['pass_streak'])],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="rounded-lg border border-slate-800/80 bg-slate-950/40 px-2 py-1.5"
                    >
                      <dd className="font-mono text-[13px] text-slate-100">{value}</dd>
                      <dt className="mt-0.5 text-[9px] text-slate-500">{label}</dt>
                    </div>
                  ))}
                </dl>
                <p className="mt-2 text-[10px] text-slate-500">
                  推荐只陈述关系与证据强度，不给方向、不给仓位；方向与执行在「技术图表」完成。
                </p>
              </div>
            ) : (
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3.5 py-3 text-[11px] text-slate-500">
                选中左侧一条推荐后，这里显示它的出口卡
              </div>
            )}

            <CapabilityCard
              panel={{ capability_id: 'D-K01', title: '关系推荐（只读出口）', args: { target: base } }}
              refreshKey={selected}
            />
            <button
              type="button"
              onClick={() => setPicker('card')}
              disabled={atPanelLimit}
              className="w-full rounded-xl border border-dashed border-slate-700 bg-indigo-500/[0.03] py-4 text-xs text-indigo-300 hover:border-indigo-500/60 disabled:cursor-not-allowed disabled:border-slate-800 disabled:text-slate-600"
            >
              ＋ 添加出口卡（从能力库按需取）
            </button>
          </section>
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {activeTab.panels.map((panel) => (
            <CapabilityCard
              key={buildPanelKey(panel)}
              panel={panel}
              onRemove={requestRemovePanel}
              onArgsChange={handlePanelArgsChange}
            />
          ))}
          <button
            type="button"
            onClick={() => setPicker('card')}
            disabled={atPanelLimit}
            className="min-h-[96px] rounded-xl border border-dashed border-slate-700 bg-indigo-500/[0.03] text-xs text-indigo-300 hover:border-indigo-500/60 disabled:cursor-not-allowed disabled:border-slate-800 disabled:text-slate-600"
          >
            {atPanelLimit ? `本 tab 已达上限 ${MAX_PANELS_PER_TAB}` : '＋ 添加能力卡片'}
          </button>
        </div>
      )}

      <CapabilityPicker
        open={picker !== null}
        mode={picker ?? 'card'}
        mounted={mounted}
        onClose={() => setPicker(null)}
        onPick={handlePick}
      />
    </div>
  );
}

export default DataResearchCardBoard;
