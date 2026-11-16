'use client';

// 数据研究（设计稿 v3 · 五子页严格对齐）
// 顺序：1 目标与覆盖 → 2 算法分类 → 3 现象归纳 → 4 假设验证 → 5 数据卡片。
// 数据全部来自 /api/visual/research 的只读投影（注册表 / 预注册空间 / 算法注册表），
// 前端零统计重算；产物缺失一律显式空态 + 原因，不补造。

import { useEffect, useMemo, useState } from 'react';
import { V3Badge } from '@/components/V3Badge';
import { V3Empty } from '@/components/V3Empty';
import type { PanelSpec } from '@/lib/visual/panelKey';
import {
  fetchResearch,
  type CoverageCell,
  type GateRow,
  type PatternRow,
  type RecommendationRow,
  type RelationClass,
  type ResearchPayload,
} from '@/lib/visual/research';
import { CapabilityCard } from './CapabilityCard';
import { CapabilityPicker } from './CapabilityPicker';

const TABS: { id: string; idx: number; label: string; sub: string }[] = [
  { id: 'coverage', idx: 1, label: '目标与覆盖', sub: '目标 × 数据域' },
  { id: 'classes', idx: 2, label: '算法分类', sub: 'R1–R6 与算法包' },
  { id: 'patterns', idx: 3, label: '现象归纳', sub: '同向率与明细' },
  { id: 'validation', idx: 4, label: '假设验证', sub: '门禁与漏斗' },
  { id: 'cards', idx: 5, label: '数据卡片', sub: '只读出口与证据' },
];

const CELL_TONE: Record<string, string> = {
  ok: 'bg-emerald-500/15 text-emerald-300',
  partial: 'bg-amber-500/12 text-amber-300',
  missing: 'bg-rose-500/10 text-rose-300',
  unknown: 'bg-slate-800/60 text-slate-500',
};

const STATE_TONE: Record<string, string> = {
  stable: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
  candidate: 'border-amber-500/25 bg-amber-500/10 text-amber-300',
  decayed: 'border-rose-500/25 bg-rose-500/10 text-rose-300',
  strong: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300',
  weak: 'border-amber-500/25 bg-amber-500/10 text-amber-300',
  opposed: 'border-rose-500/25 bg-rose-500/10 text-rose-300',
};

function fmtNum(value: number | null | undefined, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function Cell({ state }: { state: CoverageCell['state'] }) {
  const mark = state === 'ok' ? '✓' : state === 'partial' ? '◐' : state === 'missing' ? '—' : '?';
  return (
    <div
      className={`flex h-6 items-center justify-center rounded text-[10px] ${CELL_TONE[state] ?? CELL_TONE.unknown}`}
    >
      {mark}
    </div>
  );
}

function Pill({ tone = 'default', children }: { tone?: string; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] ${
        STATE_TONE[tone] ?? 'border-slate-700 bg-slate-900 text-slate-400'
      }`}
    >
      {children}
    </span>
  );
}

function Card({
  title,
  sub,
  right,
  children,
  note,
  className = '',
}: {
  title: string;
  sub?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  note?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 rounded-xl border border-slate-800 bg-slate-900/40 p-3.5 ${className}`}>
      <header className="mb-2.5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[12.5px] font-medium text-slate-200">{title}</h2>
          {sub && <p className="mt-0.5 text-[10px] text-slate-500">{sub}</p>}
        </div>
        {right && <div className="flex shrink-0 items-center gap-1.5">{right}</div>}
      </header>
      {children}
      {note && <p className="mt-2 text-[10px] leading-relaxed text-slate-500">{note}</p>}
    </section>
  );
}

function RelationCard({ item }: { item: RelationClass }) {
  const enabled = item.enabled;
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] text-indigo-300">{item.id}</span>
        <Pill tone={item.packages > 0 ? (item.gate_pass > 0 ? 'stable' : 'candidate') : 'default'}>
          {item.packages > 0 ? `算法包 ${item.packages}` : enabled ? '待接入' : '未启用'}
        </Pill>
      </div>
      <p className="mt-1.5 text-xs font-medium text-slate-200">{item.name}</p>
      <p className="mt-1 min-h-[32px] text-[10.5px] leading-relaxed text-slate-500">
        {item.question || item.hypothesis || '—'}
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        {(item.judge.slice(0, 4) || item.members.slice(0, 4)).map((tag) => (
          <span
            key={tag}
            className="rounded border border-slate-800 bg-slate-900 px-1 py-0.5 font-mono text-[9px] text-slate-400"
          >
            {tag}
          </span>
        ))}
        {item.members.length > 0 && (
          <span className="rounded border border-slate-800 bg-slate-900 px-1 py-0.5 font-mono text-[9px] text-slate-500">
            方法 {item.members.length}
          </span>
        )}
      </div>
      <div className="mt-2 flex gap-3 font-mono text-[9px] text-slate-500">
        <span>
          过门 <b className="text-slate-200">{item.gate_pass}</b>
        </span>
        <span>
          |RankIC| <b className="text-slate-200">{fmtNum(item.mean_abs_rank_ic, 3)}</b>
        </span>
        <span>
          hit <b className="text-slate-200">{fmtNum(item.mean_hit, 2)}</b>
        </span>
      </div>
      {!enabled && item.blocked_by && (
        <p className="mt-1.5 text-[9px] text-slate-600">阻塞：{item.blocked_by}</p>
      )}
    </div>
  );
}

function GateItem({ item }: { item: GateRow }) {
  const ratio = item.pass !== null && item.total > 0 ? item.pass / item.total : 0;
  return (
    <div className="flex items-start gap-2.5 border-b border-slate-800/60 py-2 last:border-0">
      <span className="mt-0.5 rounded bg-indigo-500/15 px-1.5 py-0.5 font-mono text-[10px] text-indigo-300">
        {item.id}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[11.5px] text-slate-200">{item.name}</p>
        <p className="mt-0.5 font-mono text-[9.5px] text-slate-500">{item.rule}</p>
        <div className="mt-1 flex items-center gap-2">
          <span className="h-1 flex-1 overflow-hidden rounded-full bg-slate-800">
            <span
              className="block h-full rounded-full bg-indigo-500/70"
              style={{ width: `${Math.max(2, Math.round(ratio * 100))}%` }}
            />
          </span>
          <span className="font-mono text-[9px] text-slate-500">
            {item.pass === null ? '该期未记录' : `${item.pass}/${item.total}`}
          </span>
        </div>
      </div>
      <Pill tone={item.pass === null ? 'default' : 'stable'}>{item.status}</Pill>
    </div>
  );
}

export function DataResearchBoard() {
  const [active, setActive] = useState('coverage');
  const [payload, setPayload] = useState<ResearchPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [horizon, setHorizon] = useState<number | null>(null);
  const [extras, setExtras] = useState<PanelSpec[]>([]);
  const [picker, setPicker] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchResearch(12)
      .then((data) => {
        if (!alive) return;
        if (data.ok === false) {
          setError(data.reason || '研究出口降级');
          return;
        }
        setPayload(data);
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'fetch_failed');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const rows = useMemo(
    () => (payload?.recommendations.length ? payload.recommendations : payload?.candidates ?? []),
    [payload],
  );
  const usingCandidates = (payload?.recommendations.length ?? 0) === 0 && rows.length > 0;
  const horizons = useMemo(
    () => Array.from(new Set(rows.map((row) => row.horizon))).sort((a, b) => a - b),
    [rows],
  );
  const currentHorizon = horizon ?? horizons[0] ?? null;
  const filtered = useMemo(
    () => rows.filter((row) => (currentHorizon === null ? true : row.horizon === currentHorizon)),
    [rows, currentHorizon],
  );

  const patternMatrix = useMemo(() => {
    const items = payload?.patterns.rows ?? [];
    const hs = Array.from(new Set(items.map((row) => row.horizon ?? 0))).sort((a, b) => a - b);
    const relations = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6'];
    const cells: Record<string, Record<number, PatternRow>> = {};
    for (const row of items) {
      const h = row.horizon ?? 0;
      cells[row.relation] = cells[row.relation] ?? {};
      cells[row.relation][h] = row;
    }
    return { horizons: hs, relations, cells };
  }, [payload]);

  const distribution = payload?.distribution ?? { relations: [], horizons: [], values: [] };
  const space = payload?.space;
  const latest = payload?.latest;

  function addPanel(panel: PanelSpec) {
    if (extras.some((item) => item.capability_id === panel.capability_id)) {
      setPicker(false);
      return;
    }
    setExtras((prev) => [...prev, panel]);
    setPicker(false);
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">数据研究</h1>
          <p className="mt-1 text-xs text-slate-500">
            目标 → 分类 → 归纳 → 验证（≥60%）→ 数据卡片；同一闭环，全部只读历史统计
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <V3Badge variant="success" label="零 LLM · 全统计" />
          {payload?.as_of && <V3Badge variant="info" label={`评估 ${payload.as_of}`} />}
          {payload?.source?.registry_rows != null && (
            <V3Badge variant="default" label={`注册表 ${payload.source.registry_rows} 行`} />
          )}
          {payload?.degraded && <V3Badge variant="warning" label="部分降级" />}
        </div>
      </header>

      <nav className="flex items-center gap-1 overflow-x-auto border-b border-slate-800 pb-1">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActive(tab.id)}
            className={`shrink-0 rounded-t-md px-3 py-1.5 text-xs ${
              tab.id === active
                ? 'bg-indigo-500/10 text-indigo-200'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <span className="mr-1 font-mono text-[10px] opacity-70">{tab.idx}</span>
            {tab.label}
            <span className="ml-1.5 hidden text-[9px] text-slate-600 sm:inline">{tab.sub}</span>
          </button>
        ))}
      </nav>

      {error && <V3Empty title="研究数据暂不可用" description={`${error}；可稍后刷新重试`} />}
      {loading && !payload && <div className="h-24 animate-pulse rounded-xl bg-slate-800/40" />}

      {!loading && payload && payload.ok === false && (
        <V3Empty
          title="研究出口降级"
          description={payload.reason || '注册表或配置未就绪；不补造数据'}
        />
      )}

      {/* 1 目标与覆盖 */}
      {payload && active === 'coverage' && (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.85fr)]">
          <Card
            title="目标 × 数据域 覆盖矩阵"
            sub="目标恒为「价格前瞻收益」，不预测绝对价格"
            right={<Pill tone="default">h ∈ {space?.horizons.join(' / ') || '—'}</Pill>}
            note={
              <>
                {(payload.coverage.notes ?? []).map((item) => (
                  <span key={item} className="block">
                    {item}
                  </span>
                ))}
                灰格能力在「数据口径」子页给出未达门原因（n / gate / not_collected）。
              </>
            }
          >
            {payload.coverage.available ? (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full border-separate border-spacing-[2px]">
                    <thead>
                      <tr>
                        <th className="w-[74px] px-1 text-left font-mono text-[9px] font-normal text-slate-400">
                          目标资产
                        </th>
                        {payload.coverage.domains.map((domain) => (
                          <th key={domain.key} className="px-1 text-center text-[9px] font-normal text-slate-500">
                            {domain.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {payload.coverage.rows.map((row) => (
                        <tr key={row.target}>
                          <td className="px-1 font-mono text-[10px] text-slate-300">
                            {row.label}
                            <span className="ml-1 text-[8px] text-slate-600">n{row.n}</span>
                          </td>
                          {payload.coverage.domains.map((domain) => (
                            <td key={domain.key} className="p-0">
                              <Cell state={row.domains[domain.key]?.state ?? 'unknown'} />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-slate-500">
                  <span>✓ 已入池且达 min_n</span>
                  <span>◐ 覆盖不足 / 降级</span>
                  <span>— 未采集</span>
                </div>
              </>
            ) : (
              <V3Empty
                title="暂无覆盖矩阵"
                description={payload.reason || '注册表与数据域均未就绪'}
              />
            )}
          </Card>

          <div className="space-y-3">
            <Card
              title="本期预注册空间"
              sub={
                space?.available
                  ? `discovery_space v${space.version} · seed ${space.seed ?? '—'} · 冻结`
                  : '配置未读取'
              }
              right={<Pill tone="candidate">运行期禁扩张</Pill>}
            >
              {space?.available ? (
                <>
                  <div className="grid grid-cols-4 gap-2">
                    {[
                      ['序列池', String(space.series_count), `资产 + 宏观`],
                      ['变换', String(space.transform_count), space.transforms.join('/')],
                      ['关系型方法', String(space.method_count), '预注册子集'],
                      ['单元预算', String(space.max_units), `≤${space.max_minutes} min`],
                    ].map(([label, value, detail]) => (
                      <div key={label} className="rounded-lg border border-slate-800/80 bg-slate-950/40 px-2 py-1.5">
                        <p className="font-mono text-[15px] text-slate-100">{value}</p>
                        <p className="mt-0.5 text-[9px] text-slate-500">{label}</p>
                        <p className="truncate font-mono text-[8px] text-slate-600">{detail}</p>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {[
                      `pair ≤ ${space.max_pairs}`,
                      `FDR α=${space.alpha ?? '—'}`,
                      `去重 |corr|>${space.corr_threshold ?? '—'}`,
                      `分段 ${(space.screen_ratio ?? 0) * 100}/${(space.holdout_ratio ?? 0) * 100}`,
                      `发现上限 ${space.max_findings}`,
                    ].map((chip) => (
                      <span
                        key={chip}
                        className="rounded border border-slate-800 bg-slate-900 px-1.5 py-0.5 font-mono text-[9px] text-slate-400"
                      >
                        {chip}
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <p className="text-[11px] text-slate-500">未找到 discovery_space.yaml</p>
              )}
              <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
                任何维度改动 = 新一期预注册（version+1 并重跑基线）；不支持在同一 version 内追加序列或方法。
              </p>
            </Card>

            <Card
              title="最近一期产出"
              sub={latest?.eval_at ? `评估于 ${latest.eval_at.slice(0, 19)}` : '注册表未写入'}
              right={<Pill tone={latest?.available ? 'stable' : 'default'}>{latest?.available ? '已完成' : '空'}</Pill>}
              note="运行期只写 reports/ 与注册表；前端只做投影，落库由 MERS 复核后执行。"
            >
              {latest?.available ? (
                <table className="w-full">
                  <tbody>
                    {[
                      ['枚举单元', space?.max_units ?? 0, latest.report ? '报告 manifest' : '预注册预算'],
                      ['可评估（n ≥ 250）', latest.evaluable ?? 0, `${payload.source.registry_rows ?? 0} 行中`],
                      ['显著（p_adj < 0.05）', latest.significant ?? 0, 'BH-FDR'],
                      ['样本外同号', latest.holdout_recorded === false ? '未记录' : (latest.holdout_agree ?? 0), 'holdout 30%'],
                      ['过四门禁', latest.gate_pass ?? 0, 'candidate'],
                      ['升 stable', latest.stable ?? 0, '连击 ≥ 3'],
                    ].map(([label, value, ref]) => (
                      <tr key={String(label)} className="border-b border-slate-800/50 last:border-0">
                        <td className="py-1.5 text-[11px] text-slate-400">{label}</td>
                        <td className="py-1.5 text-right font-mono text-[12px] text-slate-100">
                          {typeof value === 'number' ? value.toLocaleString() : value}
                        </td>
                        <td className="py-1.5 pl-2 text-right font-mono text-[9px] text-slate-600">{ref}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-[11px] text-slate-500">{latest?.reason || '注册表尚未生成'}</p>
              )}
            </Card>
          </div>
        </div>
      )}

      {/* 2 算法分类 */}
      {payload && active === 'classes' && (
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {payload.classes.length > 0 ? (
              payload.classes.map((item) => <RelationCard key={item.id} item={item} />)
            ) : (
              <V3Empty title="暂无关系分类" description="algorithm_registry.yaml 未读取或为空" />
            )}
          </div>

          <Card
            title="算法包统计（algorithm_registry 视图）"
            sub="按关系类聚合；算法包 = 变换 × 方法 × 目标 × 冻结参数"
            right={
              <>
                <Pill tone="default">
                  {payload.classes.reduce((sum, item) => sum + item.packages, 0)} 个算法包
                </Pill>
                <Pill tone="default">{payload.source.data_version || '—'}</Pill>
              </>
            }
            note="分类不是人工贴标签：relation_type 由算法包声明，验证阶段用绑定能力复核判据；对不上则算法包作废。多角色方法会在多个关系类重复出现。"
          >
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-800">
                    {['关系类', '算法包', '覆盖方法', '过门禁', '平均 |RankIC|', '平均 hit', '状态分布', '备注'].map(
                      (head) => (
                        <th
                          key={head}
                          className="whitespace-nowrap px-2 py-1.5 text-left text-[9px] font-normal uppercase tracking-wide text-slate-500"
                        >
                          {head}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {payload.classes.map((item) => (
                    <tr key={item.id} className="border-b border-slate-800/50 last:border-0 hover:bg-slate-800/20">
                      <td className="whitespace-nowrap px-2 py-1.5 text-[11px] text-slate-200">
                        {item.id} {item.name}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-[11px] text-slate-200">{item.packages}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-[11px] text-slate-300">
                        {item.members.length}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-[11px] text-slate-300">{item.gate_pass}</td>
                      <td className="px-2 py-1.5 text-right font-mono text-[11px] text-slate-300">
                        {fmtNum(item.mean_abs_rank_ic, 3)}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-[11px] text-slate-300">
                        {fmtNum(item.mean_hit, 2)}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1.5">
                        {item.states.stable > 0 && <Pill tone="stable">stable {item.states.stable}</Pill>}{' '}
                        {item.states.candidate > 0 && (
                          <Pill tone="candidate">cand {item.states.candidate}</Pill>
                        )}{' '}
                        {item.states.decayed > 0 && <Pill tone="decayed">decayed {item.states.decayed}</Pill>}{' '}
                        {item.packages === 0 && <Pill tone="default">{item.enabled ? '未接入' : '未启用'}</Pill>}
                      </td>
                      <td className="px-2 py-1.5 text-[10px] text-slate-500">
                        {item.top_horizon ? `h=${item.top_horizon} 最多` : item.blocked_by || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {/* 3 现象归纳 */}
      {payload && active === 'patterns' && (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <Card
            title="同类现象归纳矩阵"
            sub="值 = 同向率 sign_agreement（support / (support + oppose)）"
            right={<Pill tone="default">{payload.patterns.source === 'report' ? 'patterns.json' : '注册表投影'}</Pill>}
            note="0.50 = 抛硬币。矩阵只报同向率与 p_adj，不写因果句；缺失期限留空，不补造。"
          >
            {payload.patterns.available ? (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full border-separate border-spacing-[2px]">
                    <thead>
                      <tr>
                        <th className="w-[60px] px-1 text-left font-mono text-[9px] font-normal text-slate-400">
                          关系类
                        </th>
                        {patternMatrix.horizons.map((h) => (
                          <th key={h} className="px-1 text-center text-[9px] font-normal text-slate-500">
                            h={h}
                          </th>
                        ))}
                        <th className="px-1 text-center text-[9px] font-normal text-slate-500">跨期限一致</th>
                      </tr>
                    </thead>
                    <tbody>
                      {patternMatrix.relations.map((relation) => {
                        const cells = patternMatrix.cells[relation] ?? {};
                        const values = Object.values(cells)
                          .map((item) => item.agreement)
                          .filter((value): value is number => typeof value === 'number');
                        const consistent =
                          values.length === 0
                            ? '—'
                            : values.every((value) => value >= 0.5)
                              ? '是'
                              : values.some((value) => value >= 0.5)
                                ? '部分'
                                : '否';
                        return (
                          <tr key={relation}>
                            <td className="px-1 font-mono text-[10px] text-slate-300">{relation}</td>
                            {patternMatrix.horizons.map((h) => {
                              const cell = cells[h];
                              const agreement = cell?.agreement ?? null;
                              const tone =
                                agreement === null
                                  ? 'bg-slate-800/60 text-slate-500'
                                  : agreement >= 0.8
                                    ? 'bg-indigo-500/45 text-indigo-100'
                                    : agreement >= 0.7
                                      ? 'bg-indigo-500/30 text-indigo-200'
                                      : agreement >= 0.6
                                        ? 'bg-indigo-500/18 text-indigo-200'
                                        : 'bg-indigo-500/10 text-indigo-300';
                              return (
                                <td key={h} className="p-0">
                                  <div className={`flex h-6 items-center justify-center rounded text-[9px] ${tone}`}>
                                    {agreement === null ? '—' : agreement.toFixed(2)}
                                  </div>
                                </td>
                              );
                            })}
                            <td className="p-0">
                              <div
                                className={`flex h-6 items-center justify-center rounded text-[9px] ${
                                  consistent === '是'
                                    ? 'bg-emerald-500/15 text-emerald-300'
                                    : consistent === '部分'
                                      ? 'bg-amber-500/10 text-amber-300'
                                      : consistent === '否'
                                        ? 'bg-rose-500/10 text-rose-300'
                                        : 'bg-slate-800/60 text-slate-500'
                                }`}
                              >
                                {consistent}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-[9px] text-slate-600">
                  口径：{payload.patterns.source === 'derived' ? '注册表 RankIC 符号计数（support=正号，oppose=负号）；' : '报告 patterns.json；'}
                  反对数 &gt; 支持数标 opposed，不隐藏。
                </p>
              </>
            ) : (
              <V3Empty title="暂无可归纳现象" description="报告与注册表均无同组符号样本" />
            )}
          </Card>

          <Card
            title="pattern 明细"
            sub="可回溯到 findings.jsonl 成员"
            right={<Pill tone="default">{payload.patterns.rows.length} 条</Pill>}
            note="归纳规则：按 relation_type × horizon 分组 → 符号一致计数 → 二项检验 + BH；|corr|>0.95 去重。"
          >
            {payload.patterns.rows.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-800">
                      {['pattern', '支持/反对', '同向率', 'p_adj', '状态'].map((head) => (
                        <th
                          key={head}
                          className="whitespace-nowrap px-2 py-1.5 text-left text-[9px] font-normal uppercase tracking-wide text-slate-500"
                        >
                          {head}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {payload.patterns.rows.map((row) => (
                      <tr key={row.id} className="border-b border-slate-800/50 last:border-0">
                        <td className="whitespace-nowrap px-2 py-1.5 font-mono text-[10px] text-slate-400">{row.id}</td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10px] text-slate-300">
                          {row.support} / {row.oppose}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10px] text-slate-200">
                          {fmtNum(row.agreement, 2)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10px] text-slate-300">
                          {fmtNum(row.p_adj, 3)}
                        </td>
                        <td className="px-2 py-1.5">
                          <Pill tone={row.status}>{row.status}</Pill>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <V3Empty title="暂无 pattern" description="同一关系类 × 期限没有可计数样本" />
            )}
          </Card>
        </div>
      )}

      {/* 4 假设验证 */}
      {payload && active === 'validation' && (
        <div className="grid gap-3 xl:grid-cols-[minmax(280px,0.85fr)_minmax(0,1.55fr)]">
          <Card
            title="四门禁"
            sub="全过才 gate_pass=1"
            right={<Pill tone="candidate">按可评估样本统计</Pill>}
            note={
              <>
                为什么不是只看 60%：n=250、hit=0.60 → Wilson 下界 ≈ 0.537（过）；n=30、hit=0.67 →
                下界 ≈ 0.49（不过）。只卡点估计会让小样本抢占推荐 Top3。
              </>
            }
          >
            {payload.gates.length > 0 ? (
              payload.gates.map((item) => <GateItem key={item.id} item={item} />)
            ) : (
              <p className="text-[11px] text-slate-500">注册表为空，门禁计数不可用</p>
            )}
          </Card>

          <div className="space-y-3">
            <Card
              title="验证漏斗"
              sub={`${payload.as_of ?? '—'} 期 · ${payload.source.registry_rows ?? 0} → ${latest?.gate_pass ?? 0}`}
              right={
                <Pill tone="stable">
                  通过率{' '}
                  {payload.source.registry_rows
                    ? `${(((latest?.gate_pass ?? 0) / payload.source.registry_rows) * 100).toFixed(2)}%`
                    : '—'}
                </Pill>
              }
              note="漏斗每层都可下钻到 eval_id；任何一层为 0 不隐藏，标 blocked 并给原因。"
            >
              {payload.funnel.length > 0 ? (
                <div className="space-y-2">
                  {payload.funnel.map((step, index) => (
                    <div key={step.step} className="grid grid-cols-[110px_1fr_64px] items-center gap-2">
                      <span className="truncate text-[10.5px] text-slate-400">{step.step}</span>
                      <span className="h-3 overflow-hidden rounded bg-slate-900">
                        <span
                          className={`block h-full rounded ${
                            index === payload.funnel.length - 1 ? 'bg-emerald-500/60' : 'bg-indigo-500/50'
                          }`}
                          style={{ width: `${Math.max(step.count > 0 ? 1.5 : 0, (step.ratio ?? 0) * 100)}%` }}
                        />
                      </span>
                      <span className="text-right font-mono text-[10px] text-slate-300">
                        {step.count.toLocaleString()}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <V3Empty title="漏斗不可用" description="注册表为空" />
              )}
            </Card>

            <Card
              title="样本外命中率（滚动季度）"
              sub="holdout only · 基线 50%"
              right={<Pill tone="default">h=5 / h=20</Pill>}
              note="仅当连续 2 个季度 < 0.55 才触发降级复核；本页不重算命中率。"
            >
              {payload.holdout.available ? (
                <div className="flex h-[150px] items-end gap-1">
                  {payload.holdout.points.map((point) => (
                    <div key={point.period} className="flex flex-1 flex-col items-center gap-1">
                      <span className="font-mono text-[9px] text-slate-400">{point.value.toFixed(2)}</span>
                      <span
                        className="w-full rounded-t bg-indigo-500/50"
                        style={{ height: `${Math.max(2, point.value * 120)}px` }}
                      />
                      <span className="font-mono text-[8px] text-slate-600">{point.period}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <V3Empty title="暂无季度序列" description={payload.holdout.reason || '未归档历史期'} />
              )}
            </Card>
          </div>
        </div>
      )}

      {/* 5 数据卡片 */}
      {payload && active === 'cards' && (
        <div className="space-y-3">
          <Card
            title="关系卡片（只读出口）"
            sub="status ∈ {stable, candidate} 且 gate_pass=1；按 |RankIC| 降序"
            right={
              <div className="flex overflow-hidden rounded-md border border-slate-700">
                {(horizons.length > 0 ? horizons : [0]).map((h) => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setHorizon(h)}
                    className={`px-2 py-0.5 text-[10px] ${
                      currentHorizon === h ? 'bg-indigo-500/20 text-indigo-200' : 'text-slate-400'
                    }`}
                  >
                    h={h}
                  </button>
                ))}
              </div>
            }
            note="卡片字段全部来自 relationship_eval（不重算）；「加入技术图表」只写前端配置，不改注册表。"
          >
            {usingCandidates && (
              <p className="mb-2 rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1 text-[10px] text-amber-300">
                当期尚无 gate_pass=1 的关系，下表为候选（gate_pass=0，仅历史统计，不进入推荐）。
              </p>
            )}
            {filtered.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-800">
                      {['relation', '类型', '方法 × 变换', 'RankIC', 'hit', 'Wilson', 'holdout', 'n', 'p_adj', '状态', '证据标的'].map(
                        (head) => (
                          <th
                            key={head}
                            className="whitespace-nowrap px-2 py-1.5 text-left text-[9px] font-normal uppercase tracking-wide text-slate-500"
                          >
                            {head}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((row: RecommendationRow) => (
                      <tr key={row.eval_id} className="border-b border-slate-800/50 last:border-0 hover:bg-slate-800/20">
                        <td className="whitespace-nowrap px-2 py-1.5 font-mono text-[9.5px] text-slate-500">
                          {String(row.eval_id).slice(0, 8)}
                        </td>
                        <td className="whitespace-nowrap px-2 py-1.5 text-[10.5px] text-slate-200">{row.relation}</td>
                        <td className="whitespace-nowrap px-2 py-1.5 font-mono text-[9.5px] text-slate-400">
                          {row.method} × {row.transform}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10.5px] text-slate-100">
                          {fmtNum(Math.abs(row.rank_ic ?? 0), 3)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10.5px] text-slate-300">
                          {fmtNum(row.hit_rate, 2)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10.5px] text-slate-300">
                          {fmtNum(row.hit_rate_lb, 2)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10.5px] text-slate-300">
                          {fmtNum(row.holdout_hit_rate, 2)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10.5px] text-slate-300">{row.n}</td>
                        <td className="px-2 py-1.5 text-right font-mono text-[10.5px] text-slate-300">
                          {fmtNum(row.p_adj, 3)}
                        </td>
                        <td className="px-2 py-1.5">
                          <Pill tone={row.status}>{row.gate_pass === 1 ? row.status : 'candidate'}</Pill>
                        </td>
                        <td className="whitespace-nowrap px-2 py-1.5 font-mono text-[9.5px] text-slate-500">
                          {row.target} · h{row.horizon}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <V3Empty
                title="暂无关系卡片"
                description={payload.reason || '该期限无通过或候选关系；注册表写入后自动出现'}
              />
            )}
          </Card>

          <div className="grid gap-3 md:grid-cols-3">
            <Card
              title="关系强度演化"
              sub={payload.evidence.headline ? `${String(payload.evidence.headline).slice(0, 8)} · 每期 RankIC` : '每期 RankIC'}
              right={<Pill tone="default">series</Pill>}
              note="连续 3 期同向且显著 → pass_streak 累积。"
            >
              <p className="py-6 text-center text-[10px] text-slate-600">
                注册表按当期覆盖写入，无逐期序列；等 MERS 归档历史期后自动出现
              </p>
            </Card>

            <Card title="证据链" sub="transform → method → target" right={<Pill tone="default">graph</Pill>} note="边权 = |RankIC|；不画方向箭头，避免被读成因果。">
              {payload.evidence.available ? (
                <div className="space-y-1.5">
                  {payload.evidence.nodes.map((node, index) => (
                    <div key={node.id} className="flex items-center gap-2">
                      <span className="rounded border border-slate-800 bg-slate-950/60 px-1.5 py-0.5 font-mono text-[9.5px] text-slate-300">
                        {node.label}
                      </span>
                      <span className="text-[9px] text-slate-600">{node.group}</span>
                      {index < payload.evidence.nodes.length - 1 && (
                        <span className="ml-auto text-[9px] text-indigo-400">→</span>
                      )}
                    </div>
                  ))}
                  <p className="pt-1 text-[9px] text-slate-600">
                    边权 {fmtNum(payload.evidence.edges[0]?.weight ?? null, 3)}
                  </p>
                </div>
              ) : (
                <p className="py-6 text-center text-[10px] text-slate-600">暂无可用证据链</p>
              )}
            </Card>

            <Card title="推荐分布" sub="按类型 × 期限" right={<Pill tone="default">matrix</Pill>} note="空白类型不补造：未启用的关系类整行留空。">
              {distribution.horizons.length > 0 ? (
                <table className="w-full border-separate border-spacing-[2px]">
                  <thead>
                    <tr>
                      <th className="w-[44px] px-1 text-left font-mono text-[9px] font-normal text-slate-500">
                        类型
                      </th>
                      {distribution.horizons.map((h) => (
                        <th key={h} className="px-1 text-center text-[9px] font-normal text-slate-500">
                          h{h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {distribution.relations.map((relation, rowIndex) => (
                      <tr key={relation}>
                        <td className="px-1 font-mono text-[10px] text-slate-400">{relation}</td>
                        {distribution.horizons.map((_, colIndex) => {
                          const value = distribution.values[rowIndex]?.[colIndex] ?? 0;
                          return (
                            <td key={`${relation}-${colIndex}`} className="p-0">
                              <div
                                className={`flex h-6 items-center justify-center rounded text-[9px] ${
                                  value > 0
                                    ? 'bg-indigo-500/20 text-indigo-200'
                                    : 'bg-slate-800/50 text-slate-600'
                                }`}
                              >
                                {value > 0 ? value : ''}
                              </div>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="py-6 text-center text-[10px] text-slate-600">暂无分布</p>
              )}
            </Card>
          </div>

          <details className="rounded-xl border border-slate-800 bg-slate-900/30 p-3">
            <summary className="cursor-pointer text-[11px] text-slate-400">
              能力出口卡（按需取，不参与上方结论）
            </summary>
            <div className="mt-2 space-y-2">
              <button
                type="button"
                onClick={() => setPicker(true)}
                className="w-full rounded-lg border border-dashed border-slate-700 bg-indigo-500/[0.03] py-2 text-[11px] text-indigo-300 hover:border-indigo-500/60"
              >
                ＋ 能力库
              </button>
              {extras.map((panel) => (
                <CapabilityCard
                  key={panel.capability_id}
                  panel={panel}
                  onRemove={() => setExtras((prev) => prev.filter((item) => item.capability_id !== panel.capability_id))}
                />
              ))}
            </div>
          </details>
        </div>
      )}

      <CapabilityPicker
        open={picker}
        mode="card"
        mounted={extras.map((panel) => panel.capability_id)}
        onClose={() => setPicker(false)}
        onPick={addPanel}
      />

      <p className="text-[10px] text-slate-600">
        设计稿 v3 · 数据研究五子页；数值全部来自关系评估注册表与预注册空间，不重算、不补造。
      </p>
    </div>
  );
}

export default DataResearchBoard;
