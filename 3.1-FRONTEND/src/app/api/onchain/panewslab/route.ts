import { NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);
const DB_PATH = path.join(process.cwd(), '..', '18-数据获取中心', 'data_center.db');

async function queryDb(sql: string): Promise<any[]> {
  const { stdout } = await execFileAsync('sqlite3', ['-json', DB_PATH, sql], { timeout: 10000 });
  return stdout.trim() ? JSON.parse(stdout) : [];
}

export async function GET() {
  try {
    const cycleRows = await queryDb(
      "SELECT timestamp, metrics FROM records WHERE source='panewslab' AND sub_category='cycle_signals' ORDER BY rowid DESC LIMIT 1"
    );
    const exchangeRows = await queryDb(
      "SELECT timestamp, metrics FROM records WHERE source='panewslab' AND sub_category='exchanges_whales' ORDER BY rowid DESC LIMIT 1"
    );

    const cycle = cycleRows[0] ? JSON.parse(cycleRows[0].metrics) : null;
    const exchange = exchangeRows[0] ? JSON.parse(exchangeRows[0].metrics) : null;

    return NextResponse.json({
      ok: true,
      cycle: cycle
        ? {
            as_of: cycle.as_of,
            source: cycle.source,
            mvrv: cycle.bottom_mvrv_value,
            puell_multiple: cycle['bottom_puell-multiple_value'],
            nupl: cycle.bottom_nupl_value,
            fear_greed: cycle.bottom_fear_greed_value,
            reserve_risk: cycle.bottom_reserve_risk_value,
            two_year_ma: cycle.bottom_two_year_ma_value,
            bottom_hit_count: cycle.bottom_hit_count,
            bottom_total_count: cycle.bottom_total_count,
            bottom_hit_ratio_pct: cycle.bottom_hit_ratio_pct,
          }
        : null,
      exchange: exchange
        ? {
            as_of: exchange.exchanges_as_of,
            btc_balance: exchange.ex_bal_BTC_total,
            btc_balance_chg30d_pct: exchange.ex_bal_BTC_chg30d_pct,
            eth_balance: exchange.ex_bal_ETH_total,
            whale_24h_to_ex_usd: exchange.whale_24h_to_ex_usd,
            whale_24h_from_ex_usd: exchange.whale_24h_from_ex_usd,
            whale_netflow_to_ex_usd: exchange.whale_netflow_to_ex_usd,
          }
        : null,
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err instanceof Error ? err.message : 'db_unavailable' },
      { status: 503 }
    );
  }
}
