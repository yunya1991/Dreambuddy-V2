/**
 * S5_执行 步骤实现
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 * 职责: 生成执行计划、跟踪调整
 */

import type {
  S5ExecuteInput,
  S5ExecuteOutput,
} from "../types";

/**
 * 生成执行清单
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
 * 执行S5执行
 */
export async function executeS5Execute(
  input: S5ExecuteInput
): Promise<S5ExecuteOutput> {
  const {
    backtest,
    recommend,
    confirmExecution,
  } = input;

  // 如果不推荐执行，返回提示信息
  if (!recommend) {
    return {
      checklist: ["策略验证未通过，建议调整参数后重新验证"],
      alerts: [],
      warnings: ["策略风险较高，不建议执行"],
      trackingPlan: "无",
    };
  }

  const entryPlan = (input as any).entryPlan;
  const riskManagement = (input as any).riskManagement;
  const price = (input as any).price ?? 0;

  // 从输入中获取风险评估信息
  const consecutiveLosses = (input as any).backtest?.riskAssessment?.consecutiveLosses ?? 3;

  // 生成执行清单
  const checklist = generateChecklist(entryPlan, riskManagement, confirmExecution);

  // 生成跟踪提醒
  const alerts = generateAlerts(
    entryPlan.entryPoint,
    riskManagement.stopLoss,
    riskManagement.takeProfit,
    price
  );

  // 生成风险提示
  const warnings = generateWarnings(
    entryPlan.positionSize,
    consecutiveLosses
  );

  // 跟踪计划
  const trackingPlan = generateTrackingPlan(
    entryPlan.positionSize,
    entryPlan.entryPoint,
    riskManagement.stopLoss,
    riskManagement.takeProfit
  );

  return {
    checklist,
    alerts,
    warnings,
    trackingPlan,
  };
}

/**
 * 格式化执行结果为Markdown
 */
export function formatS5ExecuteResult(
  output: S5ExecuteOutput,
  context?: { strategyName: string; confirmed: boolean }
): string {
  const confirmed = context?.confirmed ?? false;

  return `## ⚡ S5_执行计划

${confirmed ? "### ✅ 执行确认\n策略已确认执行，请在交易终端完成以下操作：\n" : "### 📋 执行清单\n请按以下步骤执行：\n"}
${output.checklist.map(item => `- ${item}`).join("\n")}

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
