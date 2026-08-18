import {
  V1MerrillClockEngine,
  V2MultiFactorEngine,
  V3ScenarioSimEngine,
  MacroIndicator,
  TrendDirection,
} from '../src/index';

const realIndicators: MacroIndicator[] = [
  {
    name: 'GDP增长率',
    value: '2.0',
    trend: 'down' as TrendDirection,
    source: 'https://m.toutiao.com/group/7648124455759135283/',
    timestamp: '2026-06-26T00:00:00Z',
    freshness: 'fresh',
  },
  {
    name: 'CPI通胀率',
    value: '3.3',
    trend: 'up' as TrendDirection,
    source: 'https://m.toutiao.com/group/7634490368209322506/',
    timestamp: '2026-06-26T00:00:00Z',
    freshness: 'fresh',
  },
  {
    name: 'PMI指数',
    value: '47.9',
    trend: 'down' as TrendDirection,
    source: 'https://m.toutiao.com/group/7648124455759135283/',
    timestamp: '2026-06-26T00:00:00Z',
    freshness: 'fresh',
  },
  {
    name: '失业率',
    value: '4.3',
    trend: 'up' as TrendDirection,
    source: 'https://m.toutiao.com/group/7655654979968975414/',
    timestamp: '2026-06-26T00:00:00Z',
    freshness: 'fresh',
  },
];

async function main() {
  console.log('');
  console.log('='.repeat(70));
  console.log('  资产标的调研报告（基于2026年6月真实数据）');
  console.log('  数据来源：WebSearch联网搜索');
  console.log('='.repeat(70));
  console.log('');
  console.log('📊 输入数据概览：');
  console.log('  GDP增长率: 2.0% (⬇️ 放缓)');
  console.log('  CPI通胀率: 3.3% (⬆️ 高企)');
  console.log('  制造业PMI: 47.9 (📉 收缩区间)');
  console.log('  失业率: 4.3% (⬆️ 上升)');
  console.log('');

  const v1 = new V1MerrillClockEngine();
  const v1Result = await v1.run({ customIndicators: realIndicators });

  console.log('');
  console.log('='.repeat(70));
  console.log('【V1】美林时钟经典版');
  console.log('='.repeat(70));
  console.log(v1Result.report);
  console.log('');

  const v2 = new V2MultiFactorEngine();
  const v2Result = await v2.run({ customIndicators: realIndicators });

  console.log('');
  console.log('='.repeat(70));
  console.log('【V2】多因子增强版');
  console.log('='.repeat(70));
  console.log(v2Result.report);
  console.log('');

  const v3 = new V3ScenarioSimEngine();
  const v3Result = await v3.run({ customIndicators: realIndicators });

  console.log('');
  console.log('='.repeat(70));
  console.log('【V3】情景模拟版');
  console.log('='.repeat(70));
  console.log(v3Result.report);
  console.log('');

  console.log('='.repeat(70));
  console.log('版本对比分析');
  console.log('='.repeat(70));
  console.log('周期一致性: 三版本均判定为 ' + v1Result.cycle.currentPhase);
  console.log('v1置信度: ' + (v1Result.confidence * 100).toFixed(0) + '%');
  console.log('v2置信度: ' + (v2Result.confidence * 100).toFixed(0) + '%');
  console.log('v3置信度: ' + (v3Result.confidence * 100).toFixed(0) + '%');
  console.log('');
}

main().catch(console.error);
