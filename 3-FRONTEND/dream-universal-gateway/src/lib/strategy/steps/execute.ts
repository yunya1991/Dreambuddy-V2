/**
 * S5_执行 步骤实现
 *
 * 版本: v2.0 (双交易模式)
 * 日期: 2026-06-15
 * 职责: 根据 TradingMode 生成不同格式的执行计划
 *   - ai_skill: 生成 OKX Agent CLI 命令（自然语言驱动，费 Token）
 *   - classic: 生成经典策略代码（Freqtrade 格式，代码驱动，可回测）
 */

import type {
  S5ExecuteInput,
  S5ExecuteOutput,
} from "../types";

export type TradingMode = "ai_skill" | "classic";

/**
 * AI SKILL 模式：生成 OKX Agent CLI 命令清单
 * 通过自然语言驱动的灵活交易，直接在交易所执行
 */
function generateOKXCLIChecklist(
  entryPlan: {
    symbol?: string;
    entryPoint: string;
    positionSize: number;
  },
  riskManagement: {
    stopLoss: string;
    takeProfit: string;
  },
  confirmExecution: boolean = false
): { checklist: string[]; cliCommands: string[]; executionNotes: string[] } {
  const symbol = entryPlan.symbol || "BTC-USDT-SWAP";
  const entry = parseFloat(entryPlan.entryPoint);
  const sl = parseFloat(riskManagement.stopLoss);
  const tp = parseFloat(riskManagement.takeProfit);
  const posPct = entryPlan.positionSize;

  // OKX Agent CLI 命令
  const cliCommands = [
    `# 检查账户余额与可用保证金`,
    `okx account balance --ccy USDT`,
    ``,
    `# 获取当前 ${symbol} 行情`,
    `okx market ticker --instId ${symbol}`,
    ``,
    `# 限价入场 (市价单则用 ordType=market)`,
    `okx trade place-order --instId ${symbol} --tdMode cross --side buy --ordType limit --sz ${posPct}% --px ${entry.toFixed(2)}`,
    ``,
    `# 设置止损 (触发后以市价平仓)`,
    `okx trade place-algo --instId ${symbol} --algoOrdType stop_loss --side sell --sz ${posPct}% --triggerPx ${sl.toFixed(2)} --ordType market`,
    ``,
    `# 设置止盈 (触发后以限价卖出)`,
    `okx trade place-algo --instId ${symbol} --algoOrdType take_profit --side sell --sz ${posPct}% --triggerPx ${tp.toFixed(2)} --ordType limit --px ${tp.toFixed(2)}`,
    ``,
    `# 监控当前持仓与浮动盈亏`,
    `okx account positions --instId ${symbol}`,
  ];

  // 面向用户的可读清单
  const checklist = [
    `📊 确认品种: ${symbol}，当前价约 $${entry.toFixed(2)}`,
    `💰 仓位比例: ${posPct}% (建议单笔风险 ≤ 2%)`,
    `🎯 入场价: $${entry.toFixed(2)}（突破/回调确认后进场）`,
    `🛑 止损价: $${sl.toFixed(2)}（严格执行，亏损 ${(((entry - sl) / entry) * 100).toFixed(2)}%）`,
    `✅ 止盈价: $${tp.toFixed(2)}（盈亏比 ${((tp - entry) / (entry - sl)).toFixed(2)}:1）`,
    `🔔 启动价格监控: 当价格触及入场/止损/止盈时触发提醒`,
    `📝 记录交易日志: 入场理由、情绪状态、事后复盘`,
  ];

  if (confirmExecution) {
    checklist.push(`✅ 交易已确认执行，请通过 OKX Agent CLI 完成下单`);
  }

  const executionNotes = [
    `⚠️ AI SKILL 模式依赖 OKX Agent 的自然语言理解能力，需消耗 Token`,
    `⚠️ 适合灵活决策、基于情报/事件驱动的交易`,
    `💡 如需系统化/可回测，请切换到 classic 模式生成策略代码`,
    `💡 执行前请确认 API 密钥配置正确（/api/config/api-keys）`,
  ];

  return { checklist, cliCommands, executionNotes };
}

/**
 * Classic 模式：生成 Freqtrade 策略代码
 * 代码驱动的策略化交易，支持回测，低 Token 成本
 */
function generateClassicStrategyCode(
  entryPlan: {
    symbol?: string;
    entryPoint: string;
    positionSize: number;
  },
  riskManagement: {
    stopLoss: string;
    takeProfit: string;
  },
  _confirmExecution: boolean = false
): {
  checklist: string[];
  strategyCode: string;
  backtestCommand: string;
  deployNotes: string[];
} {
  const symbol = entryPlan.symbol || "BTC/USDT";
  const entry = parseFloat(entryPlan.entryPoint);
  const sl = parseFloat(riskManagement.stopLoss);
  const tp = parseFloat(riskManagement.takeProfit);
  const slPct = ((entry - sl) / entry).toFixed(4);
  const tpPct = ((tp - entry) / entry).toFixed(4);

  // 生成 Freqtrade 策略模板
  const strategyId = `${symbol.replace(/[^\w]/g, "_")}_v1_${Date.now()}`;
  const strategyCode = `# ============================================================
# ${strategyId}.py
# 经典交易体系 - Freqtrade 策略代码
# 生成时间: ${new Date().toISOString()}
# 交易对: ${symbol}
# 入场: $${entry.toFixed(2)} | 止损: $${sl.toFixed(2)} (${(parseFloat(slPct) * 100).toFixed(2)}%) | 止盈: $${tp.toFixed(2)} (${(parseFloat(tpPct) * 100).toFixed(2)}%)
# ============================================================

from freqtrade.strategy import IStrategy, merge_informative_pair
from pandas import DataFrame
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib


class ${strategyId.split('_')[0].upper()}Strategy(IStrategy):
    """
    经典指标驱动策略 - 基于 RSI + 移动均线 + 布林带
    特性: 可回测、可审计、可高频复用
    """

    # 策略版本标识
    INTERFACE_VERSION = 3

    # 时间框架
    timeframe = '1h'

    # 每个交易对可同时持仓数 (1 表示同时间只持 1 单)
    max_open_trades = 1

    # 止损 (策略内配置，也可 runtime 通过 API 动态覆盖)
    stoploss = -${slPct}

    # 止盈 (固定比例，也可改为 trailing)
    minimal_roi = {
        "0": ${tpPct}
    }

    # 是否使用 trailing_stop (可灵活开启/关闭)
    trailing_stop = False
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    def informative_pairs(self):
        # 可引入多时间框架信息
        return []

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # RSI (相对强弱指数) - 检测超买超卖
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # 移动均线 - 判断趋势方向
        dataframe['ma20'] = ta.MA(dataframe, timeperiod=20)
        dataframe['ma50'] = ta.MA(dataframe, timeperiod=50)
        dataframe['ma200'] = ta.MA(dataframe, timeperiod=200)

        # 布林带 - 判断波动率与边界
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_lower'] = bollinger['lower']
        dataframe['bb_middle'] = bollinger['mid']
        dataframe['bb_upper'] = bollinger['upper']
        dataframe['bb_width'] = (dataframe['bb_upper'] - dataframe['bb_lower']) / dataframe['bb_middle']

        # MACD - 趋势动量确认
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        # 成交量相对强度
        dataframe['volume_ma'] = ta.MA(dataframe['volume'], timeperiod=20)
        dataframe['volume_ratio'] = dataframe['volume'] / dataframe['volume_ma']

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        入场条件 (经典三信号确认):
        1. RSI < 35 且回升 (超卖反转)
        2. 价格触及/跌破布林下轨后回升
        3. MACD 金叉 (hist 由负转正)
        4. 成交量放大确认
        """
        dataframe.loc[
            (
                (dataframe['rsi'] < 35) &
                (dataframe['close'] <= dataframe['bb_lower'] * 1.005) &
                (dataframe['macdhist'] > dataframe['macdhist'].shift(1)) &
                (dataframe['macdhist'].shift(1) <= 0) &
                (dataframe['volume_ratio'] > 1.2) &
                (dataframe['close'] > dataframe['ma200'])  # 长期趋势向上
            ),
            'enter_long'] = 1

        # 空仓信号
        dataframe.loc[
            (
                (dataframe['rsi'] > 65) &
                (dataframe['close'] >= dataframe['bb_upper'] * 0.995) &
                (dataframe['macdhist'] < dataframe['macdhist'].shift(1)) &
                (dataframe['macdhist'].shift(1) >= 0) &
                (dataframe['close'] < dataframe['ma200'])
            ),
            'enter_short'] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        离场条件 (经典四信号):
        1. RSI > 65 (超买)
        2. 价格触及布林上轨
        3. MACD 死叉
        4. 价格跌破 ma20
        """
        dataframe.loc[
            (
                (dataframe['rsi'] > 65) |
                (dataframe['close'] >= dataframe['bb_upper']) |
                (dataframe['macdhist'] < 0) |
                (dataframe['close'] < dataframe['ma20'])
            ),
            'exit_long'] = 1

        dataframe.loc[
            (
                (dataframe['rsi'] < 35) |
                (dataframe['close'] <= dataframe['bb_lower'])
            ),
            'exit_short'] = 1

        return dataframe
`;

  const checklist = [
    `📦 策略代码已生成: ${strategyId}.py`,
    `🎯 入场规则: RSI超卖 + 布林下轨 + MACD金叉 + 成交量放大`,
    `🛑 止损规则: ${(parseFloat(slPct) * 100).toFixed(2)}% (固定比例，可动态配置)`,
    `✅ 止盈规则: ${(parseFloat(tpPct) * 100).toFixed(2)}% (可切换为追踪止盈)`,
    `📊 时间框架: 1h (可修改 timeframe 参数)`,
    `⚙️ 资金管理: 单笔风险 ≤ 2%，仓位=${entryPlan.positionSize}%`,
    `🔬 下一步: 执行回测 → 沙箱测试 → 审计 → 上线`,
  ];

  const backtestCommand = `freqtrade backtesting --strategy ${strategyId.split('_')[0].upper()}Strategy --timerange 20240101-20251231 --timeframe 1h`;

  const deployNotes = [
    `📝 治理流程: Draft → Gate 评估 → 审批 → Apply 应用 → Audit 记录`,
    `🧪 沙箱测试: freqtrade trade --dry-run --strategy <StrategyName>`,
    `📊 回测建议: 至少覆盖 3 个月历史数据，关注 max_drawdown / profit_factor`,
    `🔧 参数优化: freqtrade hyperopt --strategy <StrategyName> --hyperopt-loss SharpeHyperOptLoss`,
    `⚠️ 经典模式不消耗 LLM Token，仅消耗交易所行情/交易 API`,
    `💡 上线监控: 配合 Hermes-Cron 定期检查状态与健康指标`,
  ];

  return { checklist, strategyCode, backtestCommand, deployNotes };
}

/**
 * 生成执行清单 (通用/兼容 v1 版本)
 */
function generateChecklist(
  entryPlan: {
    entryPoint: string;
    positionSize: number;
  },
  riskManagement: {
    stopLoss: string;
    takeProfit: string;
  },
  confirmExecution: boolean = false
): string[] {
  const checklist = [
    "1. 检查账户余额是否充足",
    "2. 确认当前价格符合入场条件",
    `3. 设置止损单: $${riskManagement.stopLoss}`,
    `4. 买入 ${entryPlan.positionSize}% 仓位 @ $${entryPlan.entryPoint}`,
    `5. 设置止盈单: $${riskManagement.takeProfit}`,
    "6. 记录交易日志（时间、价格、仓位）",
  ];

  if (confirmExecution) {
    checklist.push("7. ✅ 确认执行完成");
  }

  return checklist;
}

/**
 * 生成跟踪提醒
 */
function generateAlerts(
  entryPoint: string,
  stopLoss: string,
  takeProfit: string,
  price: number
): Array<{ price: string; action: string }> {
  const entry = parseFloat(entryPoint);
  const sl = parseFloat(stopLoss);
  const tp = parseFloat(takeProfit);

  const alerts: Array<{ price: string; action: string }> = [];

  // 加仓提醒（价格上涨2%）
  const addPrice = (entry * 1.02).toFixed(2);
  alerts.push({
    price: `$${addPrice}`,
    action: "价格强势上涨，可考虑加仓",
  });

  // 警戒提醒（下跌1%）
  const warnPrice = (entry * 0.99).toFixed(2);
  alerts.push({
    price: `$${warnPrice}`,
    action: "价格下跌，需密切关注",
  });

  // 止损提醒
  alerts.push({
    price: `$${sl}`,
    action: "触及止损位，必须离场",
  });

  // 止盈提醒
  alerts.push({
    price: `$${tp}`,
    action: "达到目标位，可分批止盈",
  });

  return alerts;
}

/**
 * 生成风险提示
 */
function generateWarnings(
  positionSize: number,
  consecutiveLosses: number
): string[] {
  const warnings: string[] = [];

  // 仓位警告
  if (positionSize > 50) {
    warnings.push("⚠️ 仓位较重(>50%)，请确保风险承受能力足够");
  }

  // 连续亏损警告
  if (consecutiveLosses > 3) {
    warnings.push("⚠️ 策略历史上可能出现连续亏损，请设置好心理预期");
  }

  // 基本风险提示
  warnings.push("⚠️ 本策略仅供参考，不构成投资建议");
  warnings.push("⚠️ 请根据自身风险承受能力决定是否执行");
  warnings.push("⚠️ 真实交易前建议先进行模拟盘测试");

  return warnings;
}

/**
 * 制定跟踪计划
 */
function generateTrackingPlan(
  positionSize: number,
  entryPoint: string,
  stopLoss: string,
  takeProfit: string
): string {
  const entry = parseFloat(entryPoint);
  const sl = parseFloat(stopLoss);
  const tp = parseFloat(takeProfit);

  return `### 跟踪计划

**入场后**
- 每4小时检查一次价格
- 记录价格变化和情绪变化

**盈利时**
- 价格达到${(entry * 1.03).toFixed(2)}时，考虑上调止损到入场价
- 价格达到${(entry * 1.05).toFixed(2)}时，考虑止盈50%

**亏损时**
- 价格跌破${(sl * 1.01).toFixed(2)}时准备止损
- 严格遵守止损纪律，不要扛单

**止盈策略**
- 分批止盈：${tp}止盈50%，剩余设置追踪止损`;
}

/**
 * 执行 S5 — 根据 TradingMode 生成对应输出格式
 *
 * - ai_skill (默认): OKX Agent CLI 命令 + 自然语言执行清单
 *   适用场景: 动态决策、快速开仓、基于情报/消息面的交易
 *   特点: 灵活、费 Token、无需复杂策略代码
 *
 * - classic: Freqtrade 策略代码 + 回测/部署指南
 *   适用场景: 系统化交易、需要历史回测、稳定复用的策略
 *   特点: 结构化、低 Token 成本、可审计、可追踪
 */
export async function executeS5Execute(
  input: S5ExecuteInput & { tradingMode?: TradingMode; symbol?: string }
): Promise<S5ExecuteOutput & {
  mode: TradingMode;
  cliCommands?: string[];
  executionNotes?: string[];
  strategyCode?: string;
  backtestCommand?: string;
  deployNotes?: string[];
}> {
  const {
    backtest,
    recommend,
    confirmExecution,
  } = input;

  // 决定使用哪种模式（默认 ai_skill）
  const mode: TradingMode = (input as any).tradingMode || "ai_skill";

  // 如果不推荐执行，返回提示信息
  if (!recommend) {
    return {
      mode,
      checklist: ["策略验证未通过，建议调整参数后重新验证"],
      alerts: [],
      warnings: ["策略风险较高，不建议执行"],
      trackingPlan: "无",
    };
  }

  const entryPlanRaw = (input as any).entryPlan;
  const riskManagement = (input as any).riskManagement;
  const price = (input as any).price ?? 0;
  const symbol = (input as any).symbol || (input as any).entities?.symbol || "BTC";

  // 兼容 entryPlan 可能为 null 的情况（从 backtest 推断）
  const entryPlan = entryPlanRaw || {
    symbol,
    entryPoint: String(price || 30000),
    positionSize: (input as any).positionSize || 30,
  };

  if (entryPlan && !entryPlan.symbol) {
    entryPlan.symbol = symbol;
  }

  // 从输入中获取风险评估信息
  const consecutiveLosses = (input as any).backtest?.riskAssessment?.consecutiveLosses ?? 3;

  // ========== 按模式分发 ==========
  if (mode === "classic") {
    // CLASSIC 模式: 生成 Freqtrade 策略代码
    const classic = generateClassicStrategyCode(entryPlan, riskManagement, confirmExecution);

    // 同时保留 v1 的 alerts/warnings/trackingPlan 作为辅助信息
    const alerts = generateAlerts(
      entryPlan.entryPoint,
      riskManagement.stopLoss,
      riskManagement.takeProfit,
      price
    );
    const warnings = generateWarnings(
      entryPlan.positionSize,
      consecutiveLosses
    );
    const trackingPlan = generateTrackingPlan(
      entryPlan.positionSize,
      entryPlan.entryPoint,
      riskManagement.stopLoss,
      riskManagement.takeProfit
    );

    return {
      mode: "classic",
      checklist: classic.checklist,
      alerts,
      warnings,
      trackingPlan,
      strategyCode: classic.strategyCode,
      backtestCommand: classic.backtestCommand,
      deployNotes: classic.deployNotes,
    };
  }

  // 默认 AI SKILL 模式: 生成 OKX Agent CLI 命令
  const skill = generateOKXCLIChecklist(entryPlan, riskManagement, confirmExecution);

  const alerts = generateAlerts(
    entryPlan.entryPoint,
    riskManagement.stopLoss,
    riskManagement.takeProfit,
    price
  );
  const warnings = generateWarnings(
    entryPlan.positionSize,
    consecutiveLosses
  );
  const trackingPlan = generateTrackingPlan(
    entryPlan.positionSize,
    entryPlan.entryPoint,
    riskManagement.stopLoss,
    riskManagement.takeProfit
  );

  return {
    mode: "ai_skill",
    checklist: skill.checklist,
    alerts,
    warnings,
    trackingPlan,
    cliCommands: skill.cliCommands,
    executionNotes: skill.executionNotes,
  };
}

/**
 * 格式化执行结果为Markdown（支持双模式渲染）
 */
export function formatS5ExecuteResult(
  output: S5ExecuteOutput & {
    mode?: TradingMode;
    cliCommands?: string[];
    executionNotes?: string[];
    strategyCode?: string;
    backtestCommand?: string;
    deployNotes?: string[];
  },
  context?: { strategyName: string; confirmed: boolean }
): string {
  const confirmed = context?.confirmed ?? false;
  const mode = output.mode || "ai_skill";

  const modeBadge =
    mode === "classic"
      ? `📦 **模式: 经典交易体系 (Freqtrade)** | 低 Token · 可回测 · 可审计`
      : `🤖 **模式: AI SKILL (OKX Agent CLI)** | 高灵活 · 费 Token · 自然语言驱动`;

  let modeSection = "";

  if (mode === "classic" && output.strategyCode) {
    modeSection = `
### 🧠 策略代码 (Freqtrade)

\`\`\`python
${output.strategyCode}
\`\`\`

### 🔬 回测与部署

**回测命令:**
\`\`\`bash
${output.backtestCommand}
\`\`\`

**部署与治理:**
${output.deployNotes?.map(n => `- ${n}`).join("\n") || ""}
`;
  } else if (mode === "ai_skill" && output.cliCommands) {
    modeSection = `
### 🤖 OKX Agent CLI 命令

\`\`\`bash
${output.cliCommands.join("\n")}
\`\`\`

### 💡 AI SKILL 执行要点
${output.executionNotes?.map(n => `- ${n}`).join("\n") || ""}
`;
  }

  return `## ⚡ S5_执行计划

${modeBadge}

${confirmed ? "### ✅ 执行确认\n策略已确认执行，请在下方完成对应操作：\n" : "### 📋 执行清单\n请按以下步骤执行：\n"}
${output.checklist.map(item => `- ${item}`).join("\n")}

${modeSection}

${output.alerts.length > 0 ? `### 🔔 跟踪提醒
| 价格 | 操作 |
|------|------|
${output.alerts.map(a => `| ${a.price} | ${a.action} |`).join("\n")}
` : ""}

### ⚠️ 风险提示
${output.warnings.map(w => w).join("\n")}

---

${output.trackingPlan}

---

**祝您交易顺利！**`;
}

// ============================================================
// Classic System 集成钩子
// ============================================================

import { onStrategyExecuteComplete, type CompleteStrategyChain } from "@/lib/classic-system-hooks";

/**
 * S5 Execute 完成后自动推送到 Classic System
 * 
 * 此函数在 S5 Execute 步骤完成时调用
 * 会自动将策略推送到 classic-system 进行治理流程
 */
export async function onExecuteCompleteWithPush(
  chain: CompleteStrategyChain
): Promise<{ success: boolean; pipelineResult?: any; error?: string }> {
  try {
    console.log(`[S5 Hook] 开始推送策略到 Classic System...`);
    const result = await onStrategyExecuteComplete(chain, {
      onProgress: (state) => {
        console.log(`[Pipeline/${state.phase}] ${state.success ? "✅" : "❌"} ${state.message}`);
      },
    });

    if (result.success) {
      console.log(`[S5 Hook] ✅ 策略推送成功: ${result.strategyName}`);
      return { success: true, pipelineResult: result };
    } else {
      console.error(`[S5 Hook] ❌ 策略推送失败: ${result.error}`);
      return { success: false, error: result.error };
    }
  } catch (error: any) {
    console.error(`[S5 Hook] 推送异常:`, error);
    return { success: false, error: error.message };
  }
}