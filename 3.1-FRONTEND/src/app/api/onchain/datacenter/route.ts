import { NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);
const DB_PATH = path.join(process.cwd(), '..', '18-数据获取中心', 'data_center.db');

async function queryDb(sql: string): Promise<any[]> {
  try {
    const { stdout } = await execFileAsync('sqlite3', ['-json', DB_PATH, sql], { timeout: 8000 });
    return stdout.trim() ? JSON.parse(stdout) : [];
  } catch {
    return [];
  }
}

async function getLatest(source: string, subCategory: string): Promise<any> {
  const rows = await queryDb(
    `SELECT timestamp, metrics FROM records WHERE source='${source}' AND sub_category='${subCategory}' ORDER BY rowid DESC LIMIT 1`
  );
  if (!rows[0]) return null;
  try {
    const m = JSON.parse(rows[0].metrics);
    return { as_of: rows[0].timestamp, ...m };
  } catch {
    return null;
  }
}

export async function GET() {
  const [funding, longShort, liquidations, etfFlow, tether, usdc, fearGreed] = await Promise.all([
    getLatest('coinglass', 'funding_rate'),
    getLatest('coinglass', 'long_short_ratio'),
    getLatest('coinglass', 'liquidations'),
    getLatest('etf_flow', 'etf_flow'),
    getLatest('stablecoin_transparency', 'tether_current'),
    getLatest('stablecoin_transparency', 'usdc_current'),
    getLatest('fear_greed', 'crypto_fear_greed'),
  ]);

  return NextResponse.json({
    ok: true,
    flow: {
      funding_rate: funding?.funding_rate ?? funding?.avg_funding_rate ?? null,
      long_short_ratio: longShort?.long_short_ratio ?? longShort?.global_long_short_ratio ?? null,
      liquidations_24h_usd: liquidations?.total_liquidation_usd ?? liquidations?.liquidation_total_usd ?? null,
      etf_net_flow_usd: etfFlow?.total_net_flow_usd ?? etfFlow?.net_flow_usd ?? null,
      etf_inflow_24h: etfFlow?.total_inflow_usd ?? null,
      etf_outflow_24h: etfFlow?.total_outflow_usd ?? null,
    },
    stablecoin: {
      usdt_supply_bln: tether?.usdt_total_supply_usd_bln ?? null,
      usdc_supply_bln: usdc?.usdc_total_supply_usd_bln ?? null,
      usdt_change_7d_pct: tether?.change_7d_pct ?? null,
      usdc_change_7d_pct: usdc?.change_7d_pct ?? null,
    },
    sentiment: {
      fear_greed_index: fearGreed?.value ?? fearGreed?.fear_greed_index ?? null,
      classification: fearGreed?.value_classification ?? fearGreed?.classification ?? null,
    },
  });
}
