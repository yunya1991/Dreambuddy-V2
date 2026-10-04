/**
 * 意图描述库 — 用于 LLM Zero-shot 识别和训练样本库
 *
 * 每个意图包含:
 * - id: 意图 ID
 * - name: 中文名称
 * - description: 详细描述（用于 LLM prompt）
 * - keywords: 关键词列表（用于规则预过滤和 LLM 辅助）
 * - examples: 示例用户输入（用于 Few-shot）
 *
 * 用途:
 * 1. LLM Zero-shot prompt 的意图定义部分
 * 2. 规则预过滤的关键词匹配
 * 3. 训练样本库的基础
 * 4. 澄清选项的生成
 */

export interface IntentDescription {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  examples: string[];
}

/**
 * 完整意图描述库（DreamOS 7 型策略意图 + 通用意图）
 * 这些描述用于 LLM 识别时的意图定义，提供详细的边界和区分点
 */
export const INTENT_DESCRIPTIONS: IntentDescription[] = [
  // ============ 市场查询类 ============
  {
    id: 'market_query',
    name: '市场行情查询',
    description: '查询交易品种的实时价格、涨跌幅、成交量、K线等基础行情数据。用户只想"看数据"，不需要分析或建议。通常包含"价格""行情""多少""涨跌""成交量"等查询动词。',
    keywords: ['价格', '行情', '多少', '涨跌', '涨了', '跌了', '现价', '报价', '成交量', 'k线', '走势'],
    examples: ['BTC现在多少钱', 'ETH今天涨了多少', 'SOL的成交量', '看看BNB的行情'],
  },

  // ============ 分析类 ============
  {
    id: 'deep_analysis',
    name: '深度分析',
    description: '对交易品种进行多维度深度分析，包括技术面、基本面、资金面、情绪面等。用户想"理解为什么"或"判断方向"，需要综合分析和结论。',
    keywords: ['分析', '研究', '看看', '怎么样', '能买吗', '能涨吗', '会跌吗', '为什么', '怎么看', '评估'],
    examples: ['分析一下BTC的走势', 'ETH怎么样能买吗', 'BTC为什么跌了', 'SOL的技术面分析'],
  },
  {
    id: 'triple_chain',
    name: '全链分析+规划+执行',
    description: '用户要求对某个标的进行完整的分析-规划-执行闭环，包括深度分析、交易策略制定、仓位管理、执行下单等。是最高复杂度的意图，需要调用多个子系统。',
    keywords: ['全链', '完整', '全面', '一条龙', '分析规划执行', '全套'],
    examples: ['对BTC做一次完整的分析规划执行', '全面分析ETH并给出交易计划', '一条龙分析SOL并执行'],
  },

  // ============ 策略/模拟类 ============
  {
    id: 'scenario_sim',
    name: '情景推演/假设分析',
    description: '在假设条件下进行情景推演和模拟分析。用户提出"如果...会怎样"的假设性问题，需要基于假设场景进行推理和预测。',
    keywords: ['如果', '假如', '假设', '万一', '要是', '情景', '推演', '模拟'],
    examples: ['如果BTC跌破5万会怎样', '假如美联储降息对ETH的影响', '万一SOL暴涨怎么操作'],
  },
  {
    id: 'strategy_verify',
    name: '策略验证/回测',
    description: '验证某个交易策略的有效性，或进行历史回测。用户想知道"这个策略能不能赚钱"，需要历史数据回测和统计分析。',
    keywords: ['回测', '验证', '策略', '测试', '历史表现', '胜率', '收益率'],
    examples: ['回测一下BTC的均线策略', '验证这个策略的胜率', '测试ETH的突破策略'],
  },

  // ============ 交易执行类 ============
  {
    id: 'execute_trade',
    name: '交易执行/下单',
    description: '执行具体的交易操作，包括买入、卖出、开仓、平仓等。用户明确要"交易"，包含明确的标的、方向、数量等参数。需要二次确认后执行。',
    keywords: ['买入', '卖出', '开仓', '平仓', '做多', '做空', '下单', '交易', '买', '卖'],
    examples: ['买入1个BTC', '平掉ETH的多单', '做空SOL', '开多BNB'],
  },
  {
    id: 'risk_alert_response',
    name: '风险告警响应',
    description: '应对系统发出的风险告警或止损止盈提醒。用户收到告警后询问"怎么办"，需要基于当前持仓和风险状况给出建议。',
    keywords: ['告警', '提醒', '止损', '止盈', '爆仓', '风险', '怎么办', '要不要平'],
    examples: ['BTC止损告警了怎么办', 'ETH快爆仓了要不要平', '收到风险提醒怎么处理'],
  },

  // ============ 问答/系统类 ============
  {
    id: 'simple_qa',
    name: '简单问答/非交易话题',
    description: '简单的问答或非交易相关话题。包括问候、感谢、闲聊、知识性问题等。不涉及具体交易操作或分析。',
    keywords: ['你好', '谢谢', '再见', '是什么', '为什么', '怎么', '能不能', '可以'],
    examples: ['你好', '谢谢你', '什么是区块链', '你能做什么'],
  },
  {
    id: 'command',
    name: '系统命令',
    description: '用户发出的系统操作命令，如清空会话、导出数据、刷新状态等。不涉及交易逻辑，是对系统本身的操作。',
    keywords: ['清空', '重置', '刷新', '导出', '重启', '清理'],
    examples: ['清空会话', '导出分析结果', '刷新数据'],
  },
  {
    id: 'system_config',
    name: '系统配置/设置',
    description: '修改系统配置或参数设置，如风控阈值、交易偏好、API key 等。用户想"调整系统行为"。',
    keywords: ['设置', '配置', '修改', '调整', '参数', '阈值', '偏好'],
    examples: ['设置止损阈值', '修改风控参数', '配置API key'],
  },
  {
    id: 'credits_query',
    name: '查询余额/积分',
    description: '查询账户余额、积分、使用量等账户信息。',
    keywords: ['余额', '积分', '额度', '使用量', '还剩', '花费'],
    examples: ['我还有多少积分', '余额查询', '这个月用了多少额度'],
  },
  {
    id: 'artifact_query',
    name: '查询历史记录/产物',
    description: '查询历史分析记录、交易记录、生成的报告等系统产物。',
    keywords: ['历史', '记录', '上次', '之前', '报告', '产物', '日志'],
    examples: ['看看上次的分析', '历史交易记录', '之前的BTC报告'],
  },

  // ============ 澄清 ============
  {
    id: 'need_clarification',
    name: '需要澄清',
    description: '用户意图不明确，需要进一步询问确认。当信息不足以确定意图时使用，提供2-3个最可能的选项。',
    keywords: [],
    examples: ['帮我看看', '分析一下', '这个怎么样'],
  },
];

/**
 * 生成 LLM prompt 中的意图定义部分
 * 格式: "intent_id (名称): 描述"
 */
export function buildIntentDescriptionsPrompt(): string {
  return INTENT_DESCRIPTIONS
    .map((d) => `- ${d.id} (${d.name}): ${d.description}`)
    .join('\n');
}

/**
 * 生成 LLM prompt 中的关键词提示部分
 * 帮助 LLM 快速匹配意图
 */
export function buildIntentKeywordsPrompt(): string {
  return INTENT_DESCRIPTIONS
    .filter((d) => d.keywords.length > 0)
    .map((d) => `- ${d.id}: ${d.keywords.join('、')}`)
    .join('\n');
}

/**
 * 根据意图 ID 获取描述
 */
export function getIntentDescription(intentId: string): IntentDescription | undefined {
  return INTENT_DESCRIPTIONS.find((d) => d.id === intentId);
}

/**
 * 子系统能力映射 — 意图到 DreamOS 子系统的路由关系
 * 帮助 LLM 理解每个意图会调用什么能力，辅助意图区分
 */
export const INTENT_SUBSYSTEM_MAP: Record<string, string[]> = {
  market_query: ['C1_tech_scan', '行情数据'],
  deep_analysis: ['C1_tech_scan', 'C2_momentum', 'C3_volatility', 'A1-A8 分析链'],
  triple_chain: ['C链', 'A链', 'F链', 'V15_EXECUTOR'],
  scenario_sim: ['A链分析', '情景推演引擎'],
  strategy_verify: ['回测引擎', '策略验证'],
  execute_trade: ['V15_EXECUTOR', '订单系统'],
  risk_alert_response: ['F链风控', 'V15_EXECUTOR'],
  simple_qa: ['无（直接回答）'],
  command: ['系统控制'],
  system_config: ['配置管理'],
  credits_query: ['账户系统'],
  artifact_query: ['产物中心'],
  need_clarification: ['无（等待用户输入）'],
};

/**
 * 生成子系统能力映射的 prompt 部分
 */
export function buildSubsystemMapPrompt(): string {
  return Object.entries(INTENT_SUBSYSTEM_MAP)
    .map(([intent, subsystems]) => `- ${intent} → ${subsystems.join(', ')}`)
    .join('\n');
}

/**
 * 相似意图区分提示 — 帮助 LLM 区分边界模糊的意图
 */
export const INTENT_BOUNDARY_HINTS: string[] = [
  'market_query vs deep_analysis: 只问"多少钱/涨跌"是 market_query；问"怎么样/能不能买/为什么"是 deep_analysis',
  'deep_analysis vs triple_chain: 只要求分析是 deep_analysis；要求"分析+策略+执行"完整闭环是 triple_chain',
  'scenario_sim vs deep_analysis: 有"如果/假设/万一"等假设词是 scenario_sim；直接问现状是 deep_analysis',
  'execute_trade vs risk_alert_response: 主动要求买卖是 execute_trade；响应告警/止损提醒是 risk_alert_response',
  'simple_qa vs need_clarification: 明确的非交易问题是 simple_qa；交易相关但信息不足是 need_clarification',
];
