/**
 * L1 意图注册表 — 单一事实源 (SPEC v1.0 §5 三层路由器) v3
 * ==========================================
 * 所有 L1 可执行意图在此注册，路由器与执行链路从此处读取。
 * 新增 L1 意图只需在此注册一处。
 *
 * v2: 通用意图（data_query/data_insight）增加 requiredPattern 执行前置校验——
 * 模型预测为通用意图时（权重高会吸收一切问法），消息需通过特征校验才执行，
 * 否则视为 L1 未命中走 L2（置信度门控的注册表实现，非数据类问法不再被误吞）。
 *
 * v3 (P2.2): 预留 route_confidence 置信度门控信号入口——
 * Python 侧 34 系统 core/route_confidence.py（C3 匹配度 + C4 预测误差）产出
 * RouteConfidenceSignal，经链路透传后由 canHandleL1WithSignal 消费：
 * 有信号时以信号为准（route_confidence >= 0.65 且 decision=L1_DIRECT → L1 零 token 直答，
 * 否则转 L2 并透传 l1_intent_hint）；信号缺失/非法时 FAIL-OPEN 退回 v2 静态校验兜底。
 * 阈值跨系统唯一，禁止在此另立第二套（SSoT v4.0 §16.5）。
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
    // 查询特征: "查询动词/时间限定" 与 "数据实体" 必须共现
    // （避免 现在/当前/多少 这类泛词把 path/fundamental 等意图吞成 data_query）
    requiredPattern:
      /(?=.*(?:查|查询|搜|检索|多少|几|最新|现在|当前|今天|本周|数据|情况))(?=.*(?:CPI|非农|PCE|GDP|PMI|恐惧贪婪|稳定币|USDT|多空比|资金费率|TVL|美联储|利率|期权|衍生品|链上|快讯|行情|指数|价格|现价|K线|成交量|持仓量|未平仓|合约|市值|涨幅|跌幅|净流入|净流出|增发|算力|经济数据|宏观数据|活跃度|BTC|ETH|SOL|数据))/i,
  },
  {
    intent: 'data_insight',
    // 变化含义特征: 需同时含具体指标词与变化/含义问法（避免开放性分析问题误放行）
    requiredPattern:
      /(?=.*(CPI|PCE|PMI|非农|失业率|恐惧贪婪|稳定币|USDT|多空比|资金费率|TVL|美联储|利率|加息|降息|期权|通胀|就业|巨鲸|机构|交易所|ETF|增发|持仓量|成交量|未平仓|市值|占比|市占率|波动率|活跃度|流动性|链上|美股|纳指|黄金|原油|算力))(?=.*(意味着|意味什么|意味|说明什么|说明|代表什么|什么影响|怎么解读|什么含义|含义|超预期|不及预期|会怎么样|会怎样|怎么看|为什么))/,
  },
  {
    // 文档检索优先：出现文档类名词时，"风控/估值"只是检索主题而非意图本身
    // 数据来源: 41-文件索引系统（BM25 倒排索引，经 /api/search 同入口消费）
    intent: 'doc_search',
    fallbackPattern:
      /(查|搜|检索|找|有没有|在哪|放哪|路径|怎么写的).*(文档|资料|SPEC|规范|手册|指南|知识库|wiki|白皮书)|(文档|资料|SPEC|规范|手册|指南|知识库|wiki|白皮书).*(查|搜|找|有没有|在哪|放哪|路径|怎么写的|吗)|全文检索/,
  },
  {
    // 巨鲸数据先于事件演变：问到「巨鲸+动向/最近/流入流出」是确定性数据检索，
    // 不是事件流跟踪（与 l1_route_signal.py 对齐；该意图不参与 recall 门控）
    intent: 'whale_flow',
    fallbackPattern:
      /(?=.*(巨鲸|鲸鱼|whale|大户))(?=.*(动向|动态|数据|流入|流出|净流|转账|动作|最近|当前|现在|多少|情况|怎么样|查询|查一下))/i,
  },
  {
    // 事件演变先于事件分析：问"后续/演变/进展"是跟踪，不是单次解读
    intent: 'event_line_query',
    fallbackPattern:
      /(?=.*(事件|快讯(?!数)|监管|巨鲸|解锁|ETF|地缘|美联储|政策|局势|币种))(?=.*(演变|后续|进展|动态|动向|变化|趋势|局势))/,
  },
  {
    intent: 'contradiction_insight',
    fallbackPattern:
      /(?=.*(矛盾|一致|占主导|背离|打架|共振|冲突|统一|更重要|哪个更))(?=.*(维度|资金面|技术面|情绪面|宏观|主要矛盾|主矛盾|占主导|共振|冲突))/,
  },
  {
    intent: 'path_insight',
    fallbackPattern:
      /最小阻力|往哪走|往哪边走|往哪个方向|该多还是空|交汇|综合看|综合判断|综合信号|最优路径|信号指向|能不能上车|能上车吗|能追吗|还能追|该不该买|该不该卖|满仓还是空仓|加仓还是减仓|要不要现在进场|该进场还是|布局多还是空|该买还是该卖|先测试.*还是|怎么走|适合做多|适合做空/,
  },
  {
    intent: 'technical_analysis',
    fallbackPattern:
      /技术面|技术指标|技术形态|卦象|置信度|K线|均线|MACD|RSI|布林|背离|支撑位|压力位/,
  },
  {
    intent: 'fundamental_valuation',
    fallbackPattern: /估值|基本面|贵不贵|贵吗|便宜吗|值不值|值得买/,
  },
  {
    intent: 'asset_class_trend',
    fallbackPattern:
      /跨资产|资产对比|各类资产|各大类资产|大类资产|不同资产|资产轮动|趋势对比|美股和加密|贵金属和加密|(?=.*(美股|港股|A股|纳指|标普|黄金|原油|贵金属|加密))(?=.*(怎么样|如何|表现|强弱|哪个强|谁强|谁更强|对比|走势|趋势|轮动))|(?=.*(BTC|ETH|SOL))(?=.*(哪个强|谁强|谁更强))/,
  },
  {
    // 经济日历先于事件分析：「议息/FOMC/非农 + 什么时候/下次/日程」问的是日程，
    // 不是事件解读；否则会被 event_analysis 的「议息」关键词吞掉
    intent: 'calendar_event',
    fallbackPattern:
      /(?:经济日历|财经日历|宏观日历)|(?=.*(议息|FOMC|美联储会议|利率决议|非农|NFP|CPI|PPI|经济数据|数据公布))(?=.*(什么时候|何时|哪天|几号|下次|下一次|最近一次|日程|日历|时间表|公布时间|发布时间|安排))/i,
  },
  {
    intent: 'event_analysis',
    fallbackPattern:
      /FOMC|事件驱动|这次事件|金融事件|事件分析|超预期事件|price in|priced|加息事件|降息事件|鲍威尔|议息|发布会|讲话|会议纪要|公布后|落地|怎么反应|影响多大|表态|(?:公布|发布).*事件|事件.*(?:解读|反应|影响)/,
  },
  {
    intent: 'risk_control',
    fallbackPattern:
      /风控|风险度|止盈|止损|调控状态|仓位状态|持仓风控|移动止盈|风险大不大|风险大吗|风险高不高|风险敞口|要不要跑|要不要减仓|减仓控制|控制风险|平掉|平仓(?!量)/,
  },
  {
    // S1: 指标历史序列（指标别名 + 时间窗口/走势词双条件，与 l1_route_signal.py 对齐）
    intent: 'metric_series',
    fallbackPattern:
      /(?=.*(CPI|PPI|M2|VIX|MVRV|SOPR|NUPL|恐惧贪婪|fear ?greed|fng|资金费率|多空比|持仓量|美元指数|美债|纳指|标普|BTC|ETH|SOL|黄金|活跃地址|哈希率|算力|DeFi ?TVL|TVL|ETF|降息概率|新闻数|快讯数))(?=.*(近[0-9一二三四五六七八九十两]+(天|日|周|个月|月|年)|过去[0-9一二三四五六七八九十两]+(天|日|周|个月|月|年)|最近[0-9一二三四五六七八九十两]+(天|日|周|个月|月|年)|(近|过去|最近)?半年|[0-9]+(天|日|周|个月|月|年)|走势|趋势|历史序列|时间序列|历史数据))/i,
  },
  {
    intent: 'price_query',
    // 数据类实体（费率/TVL/未平仓等）并列时让位 data_query，避免只答一半
    fallbackPattern:
      /^(?!.*(?:资金费率|费率|TVL|CPI|PCE|非农|未平仓|持仓量|成交量|算力|多空比|快讯|经济数据|宏观数据|合约|增发))(?:(?=.*(?:BTC|ETH|SOL|比特币|以太坊|大饼|狗狗币|黄金|原油|纳指|标普))(?=.*(?:多少|啥价|什么价|几个钱))|.*(?:什么价|价格|现价|实时价|最新价|多少钱|涨到多少|跌到多少|报价))/,
  },
  {
    // L1 事件罗列 (39 SPEC v1.2 §9.7): 最近事件/快讯罗列整理
    intent: 'event_listing',
    fallbackPattern:
      /最近.*(事件|快讯|新闻|动态)|最新.*(事件|快讯|新闻)|.*(货币政策|监管|地缘|经济数据).*(事件|新闻|快讯)|发生了什么|.*新闻$|.*快讯$/,
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

// ============================================================
// v3 (P2.2): route_confidence 置信度门控信号（预留入口）
// 镜像 Python 侧 34 系统 core/route_confidence.py RouteConfidenceResult.to_dict()
// ============================================================

/** L1 直答门限（跨系统唯一，= Python route_confidence.THRESHOLD_HIGH） */
export const ROUTE_CONFIDENCE_THRESHOLD_HIGH = 0.65;

export const ROUTE_DECISION_L1_DIRECT = 'L1_DIRECT';
export const ROUTE_DECISION_L2_HANDOFF = 'L2_HANDOFF';

export type RouteDecision =
  | typeof ROUTE_DECISION_L1_DIRECT
  | typeof ROUTE_DECISION_L2_HANDOFF;

/**
 * L1 路由置信度门控信号（C3 匹配度 + C4 预测误差）。
 * 由 Python 侧 route_confidence.evaluate_route 产出，经 API/SSE 透传到前端。
 */
export interface RouteConfidenceSignal {
  /** 门控置信度：match − 0.3(predErr>0.3) − 0.2(density<3)，范围 0~1 */
  route_confidence: number;
  decision: RouteDecision;
  match_score: number;
  case_density: number;
  prediction_error: number | null;
  /** match>=0.8 & density>=5（仅信号透传，门控决策仍以 route_confidence 为准） */
  fast_path: boolean;
  /** true = recall 空/C4 降级/静态兜底等 FAIL-OPEN 状态 */
  degraded: boolean;
  reasons?: string[];
}

/** 信号类型守卫（防御非法/半结构 payload，失败则走静态兜底）。 */
export function isRouteConfidenceSignal(v: unknown): v is RouteConfidenceSignal {
  if (typeof v !== 'object' || v === null) return false;
  const s = v as Record<string, unknown>;
  return (
    typeof s.route_confidence === 'number' &&
    Number.isFinite(s.route_confidence) &&
    (s.decision === ROUTE_DECISION_L1_DIRECT ||
      s.decision === ROUTE_DECISION_L2_HANDOFF)
  );
}

/**
 * L1.canHandle（置信度门控版）:
 * - 信号合法：以信号为准 —— decision=L1_DIRECT 且 route_confidence>=0.65 才由 L1 执行，
 *   否则转 L2（调用方透传 l1_intent_hint）；
 * - 信号缺失/非法（FAIL-OPEN）：退回 v2 静态 canHandleL1（requiredPattern/fallbackPattern）；
 * - 未注册意图恒为 false（信号不能放行 L1 不会执行的意图）。
 */
export function canHandleL1WithSignal(
  intent: string,
  message: string,
  signal?: RouteConfidenceSignal | null,
): boolean {
  const def = L1_INTENT_REGISTRY.find((d) => d.intent === intent);
  if (!def) return false;
  if (isRouteConfidenceSignal(signal)) {
    return (
      signal.decision === ROUTE_DECISION_L1_DIRECT &&
      signal.route_confidence >= ROUTE_CONFIDENCE_THRESHOLD_HIGH
    );
  }
  return canHandleL1(intent, message);
}
