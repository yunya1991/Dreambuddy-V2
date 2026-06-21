/**
 * Trading Mode — 双模式交易系统
 * ==========================================
 *
 * 两种交易模式的定义、路由与知识库映射
 *
 * mode: "ai_skill"  - AI SKILL 模式 (OKX Agent CLI)
 *       自然语言驱动的灵活交易
 *       知识源: 2-KNOWLEDGE (方法论) + 6-Trading (最佳实践)
 *       特点: 灵活、费 token、无需复杂策略代码
 *
 * mode: "classic"   - 经典交易体系模式
 *       代码驱动的策略化交易
 *       知识源: 10-经典指标系统 (strategy registry + indicator library)
 *       特点: 结构化、低 token 成本、可审计可追溯、支持回测
 *
 * 使用场景:
 *   - 用户在对话 UI 中切换 mode
 *   - S1/S2 根据 mode 加载不同的知识上下文
 *   - S5 根据 mode 生成不同的输出格式
 */

export type TradingMode = "ai_skill" | "classic";

export interface TradingModeConfig {
  mode: TradingMode;
  label: string;
  description: string;
  knowledgeSources: string[];
  outputFormat: "okx_cli_commands" | "classic_strategy_code";
  executionEngine: "okx_agent_cli" | "classic_freqtrade";
}

export const TRADING_MODE_CONFIGS: Record<TradingMode, TradingModeConfig> = {
  ai_skill: {
    mode: "ai_skill",
    label: "AI SKILL 模式",
    description: "自然语言对话驱动的灵活交易，通过 OKX Agent CLI 直接在交易所执行。适合动态决策、快速开仓、基于情报的交易。",
    knowledgeSources: ["2-KNOWLEDGE", "6-Trading"],
    outputFormat: "okx_cli_commands",
    executionEngine: "okx_agent_cli",
  },
  classic: {
    mode: "classic",
    label: "经典交易体系",
    description: "代码驱动的策略化交易，策略通过治理流程上线，由 Freqtrade 等执行引擎自动运行。适合系统化、可回测、低 token 成本的交易。",
    knowledgeSources: ["10-经典指标系统"],
    outputFormat: "classic_strategy_code",
    executionEngine: "classic_freqtrade",
  },
};

/**
 * 从用户消息中推断交易模式
 * 优先根据显式关键词判断，无则默认为 ai_skill
 */
export function inferTradingMode(message: string, explicitMode?: TradingMode): TradingMode {
  if (explicitMode) return explicitMode;

  const msg = message.toLowerCase();

  const classicKeywords = [
    "经典",
    "freqtrade",
    "策略库",
    "策略代码",
    "量化",
    "回测",
    "指标系统",
    "沙箱",
    "审批",
    "信号系统",
    "automated",
    "algorithm",
  ];

  const hasClassicIntent = classicKeywords.some(
    (kw) => msg.includes(kw.toLowerCase())
  );

  if (hasClassicIntent) return "classic";
  return "ai_skill";
}

/**
 * 根据交易模式获取知识上下文
 * 两种模式使用完全不同的知识源：
 *   ai_skill: 2-KNOWLEDGE (方法论) + 6-Trading (OKX Agent 最佳实践)
 *   classic:  10-经典指标系统 (策略注册表 + 指标定义)
 */
export async function getKnowledgeContextForMode(
  mode: TradingMode,
  userMessage: string,
  intentType: string
): Promise<{
  mode: TradingMode;
  context: string;
  knowledgeType: string;
}> {
  if (mode === "classic") {
    // Classic 模式：优先从 10-经典指标系统 策略库获取
    try {
      const { StrategyLibraryAPI } = await import("@/lib/classic-system-client");

      // 尝试从策略注册表中搜索相关策略
      const query = extractStrategyQuery(userMessage);
      const searchResult = await StrategyLibraryAPI.searchStrategies({
        q: query,
        limit: 5,
      });

      if (searchResult.ok && searchResult.data && searchResult.data.entries && searchResult.data.entries.length > 0) {
        const strategies = searchResult.data.entries;
        const strategyContext = buildStrategyContext(strategies, userMessage);

        // 获取系统能力信息
        const capabilities = await StrategyLibraryAPI.getFeederCapabilities();
        const capabilityContext = buildCapabilityContext(capabilities.ok ? capabilities.data : null);

        return {
          mode: "classic",
          knowledgeType: "classic_strategy_registry",
          context:
`## 经典交易体系 - 策略库上下文

### 相关策略 (${strategies.length} 条)
${strategyContext}

### 系统能力
${capabilityContext}

### Classic 模式开发指导
1. 策略需通过治理流程: Draft → Gate → Approval → Apply → Audit
2. 每个策略必须包含: 入场规则、离场规则、仓位管理、风险控制
3. 策略签名需通过 Freqtrade 执行引擎验证
4. 上线前必须通过沙箱测试，指标系统会提供审计结果
5. 策略参数支持运行时动态配置，无需重新部署
`,
        };
      }
    } catch (e) {
      console.log(`[KnowledgeRouting] Classic system unavailable, falling back to general knowledge:`, (e as Error).message);
    }

    // Classic System 不可用时，提供 Classic 模式的方法论指导
    return {
      mode: "classic",
      knowledgeType: "classic_methodology",
      context:
`## 经典交易体系 - 策略开发方法论

注意: 策略库服务暂不可用，以下为通用开发指导

### 策略开发核心原则
1. **明确的入场信号**: 基于技术指标（RSI/MACD/MA/Bollinger 等）或价格行为的清晰入场规则
2. **严格的离场规则**: 止盈、止损、追踪止损、时间止损
3. **仓位管理**: 基于风险百分比或固定分数位
4. **可回测验证**: 所有规则必须可量化，支持历史回测
5. **治理合规**: 策略上线前需通过沙箱测试、审计和审批

### 经典策略类型
- **趋势追踪**: Triple Screen, Moving Average Crossover, Donchian Breakout
- **均值回归**: Bollinger Reversion, RSI Divergence, Pair Trading
- **动量策略**: Relative Strength, Breakout, Momentum Rotation
- **套利/对冲**: Funding Rate Arbitrage, Calendar Spread

### Freqtrade 策略结构要求
entry_signal: price < lower_band AND rsi < 30 AND volume > avg_volume
exit_signal:  price > upper_band OR rsi > 70 OR hit_stop_loss
position_size: risk_pct = 2%, calculate based on stop distance

### 治理流程
1. Draft 创建 → 2. Gate 评估 → 3. 审批 → 4. Apply 应用 → 5. Audit 记录
`,
    };
  }

  // AI SKILL 模式：使用通用知识库（已由 knowledge-loader 处理）
  // 这里不做额外处理，返回标识让后续流程使用默认 RAG
  return {
    mode: "ai_skill",
    knowledgeType: "general_rag",
    context: "",
  };
}

function extractStrategyQuery(message: string): string {
  // 从用户消息中提取交易品种和策略意图
  const symbolMatch = message.match(/(BTC|ETH|SOL|DOGE|LINK|AVAX|XRP)/i);
  const symbol = symbolMatch ? symbolMatch[0].toUpperCase() : "";

  const trendMatch = message.match(/(趋势|动量|均值回归|突破|震荡|arbitrage)/i);
  const trend = trendMatch ? trendMatch[0] : "";

  return [symbol, trend].filter(Boolean).join(" ");
}

function buildStrategyContext(
  strategies: any[],
  _userMessage: string
): string {
  if (!strategies || strategies.length === 0) return "未找到相关策略";

  return strategies
    .map((s, idx) => {
      return `${idx + 1}. **${s.strategy_id || s.name || "Unknown"}** (${s.family || "general"}${s.stage ? `, ${s.stage}` : ""})
   ${s.description || ""}
   ${s.source ? `来源: ${s.source}` : ""}`;
    })
    .join("\n\n");
}

function buildCapabilityContext(capabilities: any): string {
  if (!capabilities) return "系统能力信息不可用";
  return JSON.stringify(capabilities, null, 2);
}
