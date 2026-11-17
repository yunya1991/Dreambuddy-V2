/**
 * l1-answer-guard 单测（DESIGN-20261118 §4 / §5）
 * 覆盖 G1 六条规则与 G3 判定分支；judge 用注入函数替身，不依赖真实模型。
 */
import {
  extractEntities,
  runG1,
  reviewL1Answer,
  buildJudgePrompt,
  type GateInput,
} from './l1-answer-guard';

const basePrice: GateInput = {
  message: '查询比特币价格',
  intent: 'price_query',
  answer: 'BTC 实时价格（OKX BTC-USDT）：63766.8 USDT，24h涨跌 -1.79%，最高 65535.2',
  data: { price: 63766.8, change24h: -1.79 },
};

describe('G1 规则门', () => {
  it('正常行情卡通过（AC2 回归基线）', () => {
    expect(runG1(basePrice).verdict).toBe('pass');
  });

  it('R1 空答 / 占位模板判 fail', () => {
    expect(runG1({ ...basePrice, answer: '' }).verdict).toBe('fail');
    expect(runG1({ ...basePrice, answer: '🧠 **S2 分析**\n\n> 多维度分析与评估中...' }).verdict).toBe('fail');
  });

  it('R2 价格意图缺少数值判 fail', () => {
    const r = runG1({ ...basePrice, answer: 'BTC 目前走势不错，可以关注。' });
    expect(r.verdict).toBe('fail');
    expect(r.reasons).toContain('R2:missing_price');
  });

  it('R3 问 ETH 却只答 BTC 判 fail', () => {
    const r = runG1({
      message: '以太坊现在价格多少',
      intent: 'price_query',
      answer: 'BTC 实时价格：63766.8 USDT',
    });
    expect(r.verdict).toBe('fail');
    expect(r.reasons).toContain('R3:entity_mismatch');
  });

  it('R4 问下跌却只讲上涨判 fail', () => {
    const r = runG1({
      message: '比特币会不会下跌',
      intent: 'data_insight',
      answer: 'BTC 当前 63766.8，整体上涨趋势延续，看多为主。',
    });
    expect(r.verdict).toBe('fail');
    expect(r.reasons).toContain('R4:direction_conflict');
  });

  it('R5 答案含旧日期判 uncertain', () => {
    const r = runG1({ ...basePrice, answer: 'BTC 价格 63000（2024-01-01 数据）' });
    expect(r.verdict).toBe('uncertain');
    expect(r.reasons).toContain('R5:stale_data');
  });

  it('R6 多指标只答其一部分判 fail（客观缺失，无需 judge）', () => {
    const r = runG1({
      message: '看下 BTC 的资金费率和持仓量',
      intent: 'data_query',
      answer: 'BTC 资金费率 0.0011%',
      data: { funding: 0.0011 },
    });
    expect(r.verdict).toBe('fail');
    expect(r.missing).toContain('持仓量');
  });

  it('实体词表复用 entity_aliases.json（茅台 → 600519.SH）', () => {
    expect(extractEntities('茅台今天怎么样')).toContain('600519.SH');
    expect(extractEntities('比特币和以太坊')).toEqual(expect.arrayContaining(['BTC', 'ETH']));
  });
});

describe('G3 LLM 轻审', () => {
  const uncertainInput: GateInput = {
    message: '看下 BTC 的资金费率',
    intent: 'data_query',
    answer: 'BTC 资金费率 0.0011%（2024-01-01 数据）',
  };

  it('allowJudge=false 时不审核，保持 uncertain', async () => {
    const r = await reviewL1Answer(uncertainInput, { allowJudge: false });
    expect(r.verdict).toBe('uncertain');
    expect(r.judgeMs).toBeUndefined();
  });

  it('judge 判 fail → 接管信号', async () => {
    const r = await reviewL1Answer(uncertainInput, {
      allowJudge: true,
      judge: async () => '{"verdict":"fail","reasons":["stale_answer"],"missing":["最新时间戳"]}',
    });
    expect(r.verdict).toBe('fail');
    expect(r.missing).toContain('最新时间戳');
  });

  it('judge 判 pass → 放行', async () => {
    const r = await reviewL1Answer(uncertainInput, {
      allowJudge: true,
      judge: async () => '{"verdict":"pass","reasons":[],"missing":[]}',
    });
    expect(r.verdict).toBe('pass');
  });

  it('judge 抛错/超时 → FAIL-OPEN 标 timeout', async () => {
    const r = await reviewL1Answer(uncertainInput, {
      allowJudge: true,
      judge: async () => {
        throw new Error('judge_timeout');
      },
    });
    expect(r.verdict).toBe('timeout');
  });

  it('judge 输出非 JSON → timeout 兜底，不抛错', async () => {
    const r = await reviewL1Answer(uncertainInput, {
      allowJudge: true,
      judge: async () => '我觉得还行',
    });
    expect(r.verdict).toBe('timeout');
  });

  it('硬 fail 不调用 judge（省 token）', async () => {
    let called = false;
    const r = await reviewL1Answer({ ...basePrice, answer: '' }, {
      allowJudge: true,
      judge: async () => {
        called = true;
        return '{"verdict":"pass"}';
      },
    });
    expect(r.verdict).toBe('fail');
    expect(called).toBe(false);
  });

  it('judge prompt 包含问题、答案与缺失项', () => {
    const prompt = buildJudgePrompt(uncertainInput, { reasons: ['R5:stale_data'], missing: ['最新时间戳'] });
    expect(prompt).toContain('看下 BTC 的资金费率');
    expect(prompt).toContain('2024-01-01');
    expect(prompt).toContain('最新时间戳');
  });
});
