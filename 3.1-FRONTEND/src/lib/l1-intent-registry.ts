/**
 * L1 意图注册表 — 单一事实源 (SPEC v1.0 §5 三层路由器) v2
 * ==========================================
 * 所有 L1 可执行意图在此注册，路由器与执行链路从此处读取。
 * 新增 L1 意图只需在此注册一处。
 *
 * v2: 通用意图（data_query/data_insight）增加 requiredPattern 执行前置校验——
 * 模型预测为通用意图时（权重高会吸收一切问法），消息需通过特征校验才执行，
 * 否则视为 L1 未命中走 L2（置信度门控的注册表实现，非数据类问法不再被误吞）。
 */

export interface L1IntentDef {
  intent: string;
  /** 关键词兜底正则（命中则覆盖模型预测） */
  fallbackPattern?: RegExp;
  /** 执行前置校验（通用意图必填：模型预测命中后还需通过此校验才执行） */
  requiredPattern?: RegExp;
}

export const L1_INTENT_REGISTRY: L1IntentDef[] = [
  {
    intent: 'data_query',
    // 查询特征: 数据源关键词或查询动词（查/多少/最新/价格等）
    requiredPattern: /查|查询|多少|最新|现在|当前|什么价|价格|行情|指数|TVL|CPI|非农|美联储|fred|defillama|恐惧贪婪|稳定币|多空比|资金费率|链上|快讯|期权|衍生品/i,
  },
  {
    intent: 'data_insight',
    // 变化含义特征: 需同时含具体指标词与变化/含义问法（避免开放性分析问题误放行）
    requiredPattern: /(?=.*(CPI|非农|恐惧贪婪|稳定币|多空比|资金费率|TVL|美联储|利率|期权|通胀|就业))(?=.*(意味着|说明什么|什么影响|怎么解读|含义|超预期|不及预期|转向|上升|下降|增长|减少|流入|流出))/,
  },
  {
    intent: 'contradiction_insight',
    fallbackPattern: /(?=.*(矛盾|一致))(?=.*(维度|资金面|技术面|情绪面|宏观|主要矛盾))/,
  },
  {
    intent: 'path_insight',
    fallbackPattern: /最小阻力|往哪走|该多还是空|交汇|综合看|综合判断|最优路径/,
  },
  {
    intent: 'technical_analysis',
    fallbackPattern: /技术面|技术指标|卦象|置信度/,
  },
  {
    intent: 'fundamental_valuation',
    fallbackPattern: /估值|基本面分析|估值百分位|估值高不高/,
  },
  {
    intent: 'asset_class_trend',
    fallbackPattern: /跨资产|资产对比|各类资产|趋势对比|美股和加密|贵金属和加密/,
  },
  {
    intent: 'event_analysis',
    fallbackPattern: /FOMC|事件驱动|这次事件|金融事件|事件分析|超预期|price in|priced_in|加息事件|降息事件/,
  },
  {
    intent: 'risk_control',
    fallbackPattern: /风控|风险度|止盈|止损|调控状态|仓位状态|持仓风控|移动止盈/,
  },
  {
    intent: 'price_query',
    fallbackPattern: /什么价|价格|现价|实时价|最新价|多少钱|现在.*价/,
  },
];

/**
 * L1.canHandle: 意图是否可由 L1 执行。
 * - 特征词兜底命中的意图（有 fallbackPattern）: 直接可执行；
 * - 通用意图（data_query/data_insight）: 模型预测命中后还需通过 requiredPattern 校验。
 */
export function canHandleL1(intent: string, message: string): boolean {
  const def = L1_INTENT_REGISTRY.find((d) => d.intent === intent);
  if (!def) return false;
  if (def.requiredPattern) {
    return def.requiredPattern.test(message);
  }
  return true;
}

/** 关键词兜底: 按注册表顺序匹配特征词，命中返回对应意图，未命中返回 ''。 */
export function fallbackIntent(message: string): string {
  for (const d of L1_INTENT_REGISTRY) {
    if (d.fallbackPattern && d.fallbackPattern.test(message)) {
      return d.intent;
    }
  }
  return '';
}
