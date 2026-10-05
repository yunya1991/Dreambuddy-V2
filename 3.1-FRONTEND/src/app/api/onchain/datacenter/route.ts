import { NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);
// 统一接入 19-数据访问层（DAL），不再直连 18-数据获取中心的 data_center.db
const DB_PATH = path.join(process.cwd(), '..', '19-数据访问层', 'data', 'dreambuddy_core.db');

async function queryDb(sql: string): Promise<any[]> {
  try {
    const { stdout } = await execFileAsync('sqlite3', ['-json', DB_PATH, sql], { timeout: 8000 });
    return stdout.trim() ? JSON.parse(stdout) : [];
  } catch {
    return [];
  }
}

async function getLatestMetric(subCategory: string, metricName: string): Promise<number | null> {
  const rows = await queryDb(
    `SELECT metric_value FROM mm_metrics WHERE sub_category='${subCategory}' AND metric_name='${metricName}' ORDER BY timestamp DESC LIMIT 1`
  );
  if (!rows[0]) return null;
  const v = Number(rows[0].metric_value);
  return isFinite(v) ? v : null;
}

export async function GET() {
  const [
    totalFlow,
    tetherSupply, tetherChg7d,
    usdcSupply, usdcChg7d,
    fearGreed,
    liqTotal,
    fundingScore,
  ] = await Promise.all([
    getLatestMetric('etf_flow', 'total_flow'),
    getLatestMetric('tether_current', 'usdt_circulating_usd_bln'),
    getLatestMetric('tether_current', 'change_7d_pct'),
    getLatestMetric('usdc_current', 'usdc_circulating_usd_bln'),
    getLatestMetric('usdc_current', 'change_7d_pct'),
    getLatestMetric('crypto_fear_greed', 'value'),
    getLatestMetric('derivatives_spot', 'fut_liq_total_24h_usd'),
    getLatestMetric('fear_greed_enhanced', 'funding'),
  ]);

  // 恐惧贪婪分类
  let classification: string | null = null;
  if (fearGreed != null) {
    if (fearGreed < 25) classification = '极度恐惧';
    else if (fearGreed < 45) classification = '恐惧';
    else if (fearGreed < 55) classification = '中性';
    else if (fearGreed < 75) classification = '贪婪';
    else classification = '极度贪婪';
  }

  return NextResponse.json({
    ok: true,
    source: '19-DAL',
    flow: {
      // total_flow 单位为百万美元，转回美元
      funding_rate: fundingScore,
      long_short_ratio: null,
      liquidations_24h_usd: liqTotal,
      etf_net_flow_usd: totalFlow != null ? totalFlow * 1e6 : null,
      etf_inflow_24h: null,
      etf_outflow_24h: null,
    },
    stablecoin: {
      usdt_supply_bln: tetherSupply,
      usdc_supply_bln: usdcSupply,
      usdt_change_7d_pct: tetherChg7d,
      usdc_change_7d_pct: usdcChg7d,
    },
    sentiment: {
      fear_greed_index: fearGreed,
      classification,
    },
  });
}
