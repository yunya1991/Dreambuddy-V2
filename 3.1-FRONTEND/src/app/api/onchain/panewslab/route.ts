import { NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);
// 统一接入 19-数据访问层（DAL），不再直连 18-数据获取中心的 data_center.db
const DB_PATH = path.join(process.cwd(), '..', '19-数据访问层', 'data', 'dreambuddy_core.db');

async function queryDb(sql: string): Promise<any[]> {
  const { stdout } = await execFileAsync('sqlite3', ['-json', DB_PATH, sql], { timeout: 10000 });
  return stdout.trim() ? JSON.parse(stdout) : [];
}

async function getLatestMetric(subCategory: string, metricName: string): Promise<{ value: number; ts: number } | null> {
  const rows = await queryDb(
    `SELECT metric_value, timestamp FROM mm_metrics WHERE sub_category='${subCategory}' AND metric_name='${metricName}' ORDER BY timestamp DESC LIMIT 1`
  );
  if (!rows[0]) return null;
  return { value: Number(rows[0].metric_value), ts: Number(rows[0].timestamp) };
}

export async function GET() {
  try {
    // cycle_signals（CryptoQuant 抄底信号）
    const [mvrv, puell, nupl, fg, reserveRisk, twoYearMa, hitCount, totalCount, hitRatio] = await Promise.all([
      getLatestMetric('cycle_signals', 'bottom_mvrv_value'),
      getLatestMetric('cycle_signals', 'bottom_puell-multiple_value'),
      getLatestMetric('cycle_signals', 'bottom_nupl_value'),
      getLatestMetric('cycle_signals', 'bottom_fear-greed_value'),
      getLatestMetric('cycle_signals', 'bottom_reserve-risk_value'),
      getLatestMetric('cycle_signals', 'bottom_two-year-ma_value'),
      getLatestMetric('cycle_signals', 'bottom_hit_count'),
      getLatestMetric('cycle_signals', 'bottom_total_count'),
      getLatestMetric('cycle_signals', 'bottom_hit_ratio_pct'),
    ]);

    // exchanges_whales（CryptoQuant 交易所+巨鲸数据）
    const [btcBal, btcBalChg30d, ethBal, whaleToEx, whaleFromEx, whaleNetflow] = await Promise.all([
      getLatestMetric('exchanges_whales', 'ex_bal_BTC_total'),
      getLatestMetric('exchanges_whales', 'ex_bal_BTC_chg30d_pct'),
      getLatestMetric('exchanges_whales', 'ex_bal_ETH_total'),
      getLatestMetric('exchanges_whales', 'whale_24h_to_ex_usd'),
      getLatestMetric('exchanges_whales', 'whale_24h_from_ex_usd'),
      getLatestMetric('exchanges_whales', 'whale_netflow_to_ex_usd'),
    ]);

    return NextResponse.json({
      ok: true,
      source: '19-DAL',
      cycle: {
        mvrv: mvrv?.value ?? null,
        puell_multiple: puell?.value ?? null,
        nupl: nupl?.value ?? null,
        fear_greed: fg?.value ?? null,
        reserve_risk: reserveRisk?.value ?? null,
        two_year_ma: twoYearMa?.value ?? null,
        bottom_hit_count: hitCount?.value ?? 0,
        bottom_total_count: totalCount?.value ?? 0,
        bottom_hit_ratio_pct: hitRatio?.value ?? 0,
      },
      exchange: {
        btc_balance: btcBal?.value ?? null,
        btc_balance_chg30d_pct: btcBalChg30d?.value ?? null,
        eth_balance: ethBal?.value ?? null,
        whale_24h_to_ex_usd: whaleToEx?.value ?? null,
        whale_24h_from_ex_usd: whaleFromEx?.value ?? null,
        whale_netflow_to_ex_usd: whaleNetflow?.value ?? null,
      },
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err instanceof Error ? err.message : 'dal_unavailable' },
      { status: 503 }
    );
  }
}
