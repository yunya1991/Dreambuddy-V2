'use client';

import { useQuery } from '@tanstack/react-query';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';
import { queryKey, queryStaleTime } from '@/lib/query-keys';

/**
 * Web3 资金面板 — 币安 Web3 公开榜单（18 采集器 → records → 快照聚合）。
 *
 * 数据维度：
 *   - 聪明钱净流入榜（地址质量 + 资金流）
 *   - 社交热度榜（真实热度指数 + 情绪 + AI 摘要）
 *   - Alpha / 趋势榜的持仓结构（dev/sniper/insider/bundler/聪明钱/KOL）
 *   - memecoin 算法评分榜
 *   - 叙事热点（Topic Rush 净流入）
 *   - 单币画像 + 安全审计（税费/风险命中）
 */

interface Row {
  symbol?: string | null;
  [key: string]: unknown;
}

interface Web3Module {
  metrics?: {
    core?: Record<string, number | string | null>;
    breakdown?: {
      smart_money_inflow_top?: Row[];
      social_hype_top?: Row[];
      alpha_holding_top?: Row[];
      trending_volume_top?: Row[];
      meme_score_top?: Row[];
      narrative_top?: Row[];
      token_profile_top?: Row[];
      token_audit_top?: Row[];
      record_count?: number;
    };
  };
  meta?: { last_update?: string; source?: string[]; data_quality?: string };
}

interface SnapshotResponse {
  modules?: Record<string, Web3Module>;
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function fmtUsd(v: unknown): string {
  const n = num(v);
  if (n === null) return '--';
  const abs = Math.abs(n);
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function fmtNum(v: unknown, digits = 0): string {
  const n = num(v);
  if (n === null) return '--';
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function fmtPct(v: unknown, digits = 2): string {
  const n = num(v);
  if (n === null) return '--';
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

function riskBadge(level: unknown) {
  const n = num(level);
  if (n === null) return <V3Badge variant="default" label="--" />;
  if (n >= 4) return <V3Badge variant="danger" label={`高风险 ${n}`} />;
  if (n >= 2) return <V3Badge variant="warning" label={`中风险 ${n}`} />;
  return <V3Badge variant="success" label={`低风险 ${n}`} />;
}

function sentimentBadge(score: unknown, label?: unknown) {
  const n = num(score);
  const text = typeof label === 'string' && label ? label : n === null ? '--' : n > 0 ? 'Positive' : n < 0 ? 'Negative' : 'Neutral';
  if (n === null) return <V3Badge variant="default" label={text} />;
  if (n > 0) return <V3Badge variant="success" label={text} />;
  if (n < 0) return <V3Badge variant="danger" label={text} />;
  return <V3Badge variant="default" label={text} />;
}

function TableCard({
  title,
  hint,
  columns,
  rows,
  emptyText = '暂无数据',
}: {
  title: string;
  hint?: string;
  columns: { key: string; label: string; render?: (r: Row) => React.ReactNode }[];
  rows: Row[] | undefined;
  emptyText?: string;
}) {
  const data = rows ?? [];
  return (
    <V3Card padding="md">
      <div className="mb-2">
        <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
        {hint && <p className="text-[10px] text-slate-500 mt-0.5">{hint}</p>}
      </div>
      {data.length === 0 ? (
        <p className="text-xs text-slate-500 py-3">{emptyText}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                {columns.map(c => (
                  <th key={c.key} className="text-left font-normal py-1.5 pr-3 whitespace-nowrap">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((r, i) => (
                <tr key={`${r.symbol ?? r.topic ?? i}-${i}`} className="border-b border-slate-800/40 last:border-0">
                  {columns.map(c => (
                    <td key={c.key} className="py-1.5 pr-3 text-slate-300 whitespace-nowrap">
                      {c.render ? c.render(r) : String(r[c.key] ?? '--')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </V3Card>
  );
}

export function Web3Panel() {
  const snapshotQuery = useQuery({
    queryKey: queryKey('fundamental', 'snapshot'),
    queryFn: () => fundamentalApi.getSnapshot(),
    staleTime: queryStaleTime('fundamental'),
  });

  const mod = (snapshotQuery.data as SnapshotResponse | null)?.modules?.web3 ?? null;
  const loading = snapshotQuery.isLoading;
  const error = snapshotQuery.isError
    ? ((snapshotQuery.error as Error | null)?.message ?? '获取 Web3 数据失败')
    : null;

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-10 rounded-lg bg-slate-800/50 animate-pulse" />
        <div className="h-64 rounded-xl bg-slate-800/50 animate-pulse" />
        <div className="h-64 rounded-xl bg-slate-800/50 animate-pulse" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">
        Web3 资金数据加载失败：{error}
      </div>
    );
  }

  const core = mod?.metrics?.core ?? {};
  const bd = mod?.metrics?.breakdown ?? {};
  const recordCount = num(bd.record_count) ?? 0;

  const summaryItems = [
    { label: '聪明钱净流入合计', value: fmtUsd(core.smart_money_total_inflow_usd) },
    { label: '聪明钱地址数', value: fmtNum(core.smart_money_traders) },
    { label: '社交热度峰值', value: fmtNum(core.social_hype_top) },
    { label: '社交情绪均值', value: fmtNum(core.social_sentiment_avg, 2) },
    { label: 'Meme 最高评分', value: fmtNum(core.meme_top_score, 1) },
    { label: '叙事净流入合计', value: fmtUsd(core.narrative_total_inflow_usd) },
    { label: 'Alpha 标的数', value: fmtNum(core.alpha_count) },
    { label: '高风险代币数', value: fmtNum(core.high_risk_token_count) },
  ];

  return (
    <div className="space-y-4">
      <V3Card padding="md">
        <div className="mb-3">
          <h3 className="text-sm font-semibold text-slate-200">币安 Web3 资金与持仓结构</h3>
          <p className="text-[10px] text-slate-500 mt-0.5">
            数据源：币安 Web3 公开榜单（无需 Key） · 采集记录 {recordCount} 条
            {mod?.meta?.last_update && (
              <span className="ml-2">
                更新于 {mod.meta.last_update.slice(0, 16).replace('T', ' ')}
              </span>
            )}
            {mod?.meta?.data_quality === 'empty' && (
              <span className="ml-2 text-amber-400">（无采集数据，先跑 18 采集器）</span>
            )}
          </p>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {summaryItems.map(m => (
            <V3Card key={m.label} padding="sm" hover>
              <span className="text-[10px] text-slate-500">{m.label}</span>
              <p className="text-base font-semibold text-slate-200 mt-1">{m.value}</p>
            </V3Card>
          ))}
        </div>
      </V3Card>

      <TableCard
        title="聪明钱净流入榜（BSC · 24h）"
        hint="inflow=聪明钱净买入额 USD；traders=参与交易的聪明钱地址数"
        rows={bd.smart_money_inflow_top}
        columns={[
          { key: 'symbol', label: '代币' },
          { key: 'inflow_usd', label: '净流入', render: r => <span className={num(r.inflow_usd) !== null && (num(r.inflow_usd) as number) >= 0 ? 'text-emerald-400' : 'text-red-400'}>{fmtUsd(r.inflow_usd)}</span> },
          { key: 'traders', label: '地址数', render: r => fmtNum(r.traders) },
          { key: 'price_change_pct', label: '涨跌幅', render: r => fmtPct(r.price_change_pct) },
          { key: 'market_cap', label: '市值', render: r => fmtUsd(r.market_cap) },
          { key: 'holders', label: '持有人', render: r => fmtNum(r.holders) },
          { key: 'risk_level', label: '风险', render: r => riskBadge(r.risk_level) },
        ]}
      />

      <TableCard
        title="社交热度榜（BSC · 24h）"
        hint="真实社交热度指数 + 情绪判定 + AI 摘要（替代新闻条数代理）"
        rows={bd.social_hype_top}
        columns={[
          { key: 'symbol', label: '代币' },
          { key: 'hype', label: '热度', render: r => fmtNum(r.hype) },
          { key: 'sentiment_score', label: '情绪', render: r => sentimentBadge(r.sentiment_score, r.sentiment) },
          { key: 'market_cap', label: '市值', render: r => fmtUsd(r.market_cap) },
          { key: 'price_change_pct', label: '涨跌幅', render: r => fmtPct(r.price_change_pct) },
          { key: 'summary', label: 'AI 摘要', render: r => <span className="text-slate-400 max-w-[320px] inline-block truncate align-bottom">{String(r.summary ?? '--')}</span> },
        ]}
      />

      <TableCard
        title="Alpha 榜持仓结构"
        hint="dev/sniper/insider/bundler 占比是判断筹码质量的核心；top10 过高需警惕"
        rows={bd.alpha_holding_top}
        columns={[
          { key: 'symbol', label: '代币' },
          { key: 'holders', label: '持有人', render: r => fmtNum(r.holders) },
          { key: 'top10_pct', label: 'Top10%', render: r => fmtNum(r.top10_pct, 2) },
          { key: 'dev_pct', label: 'Dev%', render: r => fmtNum(r.dev_pct, 2) },
          { key: 'sniper_pct', label: 'Sniper%', render: r => fmtNum(r.sniper_pct, 2) },
          { key: 'insider_pct', label: 'Insider%', render: r => fmtNum(r.insider_pct, 2) },
          { key: 'bundler_pct', label: 'Bundler%', render: r => fmtNum(r.bundler_pct, 2) },
          { key: 'smart_money_pct', label: '聪明钱%', render: r => fmtNum(r.smart_money_pct, 2) },
          { key: 'kol_pct', label: 'KOL%', render: r => fmtNum(r.kol_pct, 2) },
          { key: 'kyc_holders', label: 'KYC 持有人', render: r => fmtNum(r.kyc_holders) },
          { key: 'risk_level', label: '风险', render: r => riskBadge(r.risk_level) },
        ]}
      />

      <TableCard
        title="Meme 算法评分榜（Pulse）"
        hint="score 越高越可能突破；volume_bn_7d 为币安用户 7 日成交量"
        rows={bd.meme_score_top}
        columns={[
          { key: 'symbol', label: '代币' },
          { key: 'score', label: '评分', render: r => fmtNum(r.score, 1) },
          { key: 'rank', label: '排名', render: r => fmtNum(r.rank) },
          { key: 'market_cap', label: '市值', render: r => fmtUsd(r.market_cap) },
          { key: 'liquidity', label: '流动性', render: r => fmtUsd(r.liquidity) },
          { key: 'holders', label: '持有人', render: r => fmtNum(r.holders) },
          { key: 'top10_pct', label: 'Top10%', render: r => fmtNum(r.top10_pct, 2) },
          { key: 'volume_bn_7d', label: '币安7日量', render: r => fmtUsd(r.volume_bn_7d) },
        ]}
      />

      <TableCard
        title="叙事热点（Topic Rush · Solana）"
        hint="按主题净流入排序，关联代币为资金主要流入标的"
        rows={bd.narrative_top}
        columns={[
          { key: 'topic', label: '主题' },
          { key: 'net_inflow_usd', label: '净流入', render: r => fmtUsd(r.net_inflow_usd) },
          { key: 'net_inflow_1h_usd', label: '1h 净流入', render: r => fmtUsd(r.net_inflow_1h_usd) },
          { key: 'token_size', label: '关联币数', render: r => fmtNum(r.token_size) },
          {
            key: 'top_tokens',
            label: '主要标的',
            render: r => {
              const toks = (r.top_tokens as Array<{ symbol?: string }> | undefined) ?? [];
              return <span className="text-slate-400">{toks.map(t => t.symbol).filter(Boolean).join(' / ') || '--'}</span>;
            },
          },
        ]}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <TableCard
          title="单币画像（跟随趋势榜 Top10）"
          hint="真实持有人总量 / FDV / KOL 与专业投资者持仓数"
          rows={bd.token_profile_top}
          columns={[
            { key: 'symbol', label: '代币' },
            { key: 'holders', label: '持有人', render: r => fmtNum(r.holders) },
            { key: 'top10_pct', label: 'Top10%', render: r => fmtNum(r.top10_pct, 2) },
            { key: 'fdv', label: 'FDV', render: r => fmtUsd(r.fdv) },
            { key: 'kol_holders', label: 'KOL', render: r => fmtNum(r.kol_holders) },
            { key: 'pro_holders', label: 'Pro', render: r => fmtNum(r.pro_holders) },
            { key: 'smart_money_holders', label: '聪明钱', render: r => fmtNum(r.smart_money_holders) },
          ]}
        />
        <TableCard
          title="代币安全审计"
          hint="riskLevel≥4 应直接拦截；买卖税 >10% 视为重大风险"
          rows={bd.token_audit_top}
          columns={[
            { key: 'symbol', label: '代币' },
            { key: 'risk_level', label: '风险', render: r => riskBadge(r.risk_level) },
            { key: 'buy_tax', label: '买税%', render: r => fmtNum(r.buy_tax, 2) },
            { key: 'sell_tax', label: '卖税%', render: r => fmtNum(r.sell_tax, 2) },
            { key: 'risk_hits', label: '风险命中', render: r => fmtNum(r.risk_hits) },
            { key: 'caution_hits', label: '警告命中', render: r => fmtNum(r.caution_hits) },
          ]}
        />
      </div>
    </div>
  );
}

export default Web3Panel;
