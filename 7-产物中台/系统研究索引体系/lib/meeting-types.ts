// Meeting room types

export interface Camp {
  id: string;
  name: string;
  color: string;
  bgColor: string;
  borderColor: string;
  masters: string[];
}

export interface Statement {
  campId: string;
  master: string;
  content: string;
  round: number;
  type: 'opening' | 'rebuttal' | 'final';
  timestamp: number;
}

export type MeetingStatus = 'scheduled' | 'active' | 'completed';

export interface Meeting {
  id: string;
  title: string;
  topic: string;
  trigger: string;
  camps: Camp[];
  status: MeetingStatus;
  startTime: string;
  endTime?: string;
  conclusions?: string;
  bias?: number;
  confidence?: number;
  sourceYaml?: string;
}

export const CAMPS: Camp[] = [
  {
    id: 'bullish', name: '多头阵营', color: '#639922', bgColor: '#EAF3DE', borderColor: '#C0DD97',
    masters: ['Soros', 'Druckenmiller', 'Buffett', "O'Neil"],
  },
  {
    id: 'neutral', name: '中立阵营', color: '#BA7517', bgColor: '#FAEEDA', borderColor: '#FAC775',
    masters: ['Tharp', 'Livermore', 'Talmans', 'Michele'],
  },
  {
    id: 'bearish', name: '空头阵营', color: '#E24B4A', bgColor: '#FCEBEB', borderColor: '#F7C1C1',
    masters: ['PTJ', 'Dalio'],
  },
];

// Debate script for SSE streaming (3 rounds × 3 camps)
export const DEBATE_SCRIPT: Statement[] = [
  // Round 1: Opening statements
  { campId: 'bullish', master: 'Soros', content: '当前市场处于趋势延续阶段。从反身性角度，多头的自我强化效应正在加速，价格上升吸引更多买盘。我建议继续持有多头头寸。', round: 1, type: 'opening', timestamp: 0 },
  { campId: 'bearish', master: 'PTJ', content: '宏观风险正在积聚。美联储政策的不确定性和地缘政治风险被市场低估。我建议降低风险敞口，至少部分获利了结。', round: 1, type: 'opening', timestamp: 0 },
  { campId: 'neutral', master: 'Tharp', content: '从期望值角度，当前风险回报比已偏离理想区间。建议将仓位降至系统允许的50%，等待更明确的信号。', round: 1, type: 'opening', timestamp: 0 },

  // Round 1: Bull support + Bear counter
  { campId: 'bullish', master: 'Druckenmiller', content: '同意Soros。流动性环境依然宽松，加密市场与纳斯达克的正相关性在增强。只要科技股继续上涨，BTC就有支撑。', round: 1, type: 'opening', timestamp: 0 },
  { campId: 'bearish', master: 'Dalio', content: '必须指出，债务周期正处于危险阶段。全球债务/GDP比率达到历史极值，这将是所有风险资产的系统性威胁。', round: 1, type: 'opening', timestamp: 0 },
  { campId: 'neutral', master: 'Livermore', content: '市场永远是对的。当前我没有看到明确的顶部信号，但成交量正在萎缩，这是一个警示。持有但不加仓。', round: 1, type: 'opening', timestamp: 0 },

  // Round 2: Cross-debate
  { campId: 'bullish', master: 'Soros', content: '回应Dalio的债务担忧：加密资产某种程度上是对债务危机的对冲。在通胀环境中，BTC的表现优于传统避险资产。', round: 2, type: 'rebuttal', timestamp: 0 },
  { campId: 'bearish', master: 'PTJ', content: '加密资产的避险属性尚未在真正的危机中得到验证。2020年3月的暴跌显示其仍然是风险资产。不要自欺欺人。', round: 2, type: 'rebuttal', timestamp: 0 },
  { campId: 'neutral', master: 'Tharp', content: '两位的观点都有道理。关键是仓位管理——如果多头，仓位应该小到你能承受"加密非避险"这一情景。', round: 2, type: 'rebuttal', timestamp: 0 },
  { campId: 'bullish', master: 'Buffett', content: '(远程接入)投资的第一原则是不要亏钱。但加密资产的波动特性需要不同的评估框架。当前风险溢价是合理的。', round: 2, type: 'rebuttal', timestamp: 0 },

  // Round 3: Final rebuttal
  { campId: 'bullish', master: 'Druckenmiller', content: '最终陈述：趋势是我们的朋友。多头方向不变，但同意将杠杆从3x降至2x以应对短期波动风险。这是对中性阵营的尊重。', round: 3, type: 'final', timestamp: 0 },
  { campId: 'bearish', master: 'Dalio', content: '最终陈述：系统性风险不是"是否"的问题，而是"何时"的问题。至少应该设置严格的止损，保护本金。', round: 3, type: 'final', timestamp: 0 },
  { campId: 'neutral', master: 'Livermore', content: '最终陈述：综合各方观点，建议方向偏多但保守——持有现有仓位，不加仓，设置移动止损保护利润。这是我对多空双方观点的最佳平衡。', round: 3, type: 'final', timestamp: 0 },
];
