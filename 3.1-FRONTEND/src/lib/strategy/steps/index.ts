/**
 * 策略思维链 - 步骤导出
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 */

export * from "./research";
export * from "./analysis";
export * from "./design";
export * from "./validate";
export * from "./execute";

// ============================================================
// 步骤执行工厂
// ============================================================

import { executeS1Research, formatS1ResearchResult } from "./research";
import { executeS2Analysis, formatS2AnalysisResult } from "./analysis";
import { executeS3Design, formatS3DesignResult } from "./design";
import { executeS4Validate, formatS4ValidateResult } from "./validate";
import { executeS5Execute, formatS5ExecuteResult } from "./execute";

import type {
  StrategyStepId,
  S1ResearchInput,
  S2AnalysisInput,
  S3DesignInput,
  S4ValidateInput,
  S5ExecuteInput,
} from "../types";

/**
 * 执行策略步骤
 */
export async function executeStrategyStep(
  stepId: StrategyStepId,
  input: S1ResearchInput | S2AnalysisInput | S3DesignInput | S4ValidateInput | S5ExecuteInput
): Promise<string> {
  switch (stepId) {
    case "S1_RESEARCH":
      const s1Output = await executeS1Research(input as S1ResearchInput);
      return formatS1ResearchResult(s1Output);

    case "S2_ANALYSIS":
      const s2Output = await executeS2Analysis(input as S2AnalysisInput);
      return formatS2AnalysisResult(s2Output, {
        symbol: (input as any).symbol,
        displayName: (input as any).displayName,
        price: (input as any).price,
        support: (input as any).support,
        resistance: (input as any).resistance,
      });

    case "S3_DESIGN":
      const s3Output = await executeS3Design(input as S3DesignInput);
      return formatS3DesignResult(s3Output, {
        symbol: (input as any).symbol,
        displayName: (input as any).displayName,
      });

    case "S4_VALIDATE":
      const s4Output = await executeS4Validate(input as S4ValidateInput);
      return formatS4ValidateResult(s4Output, {
        strategyName: (input as any).strategyName,
      });

    case "S5_EXECUTE":
      const s5Output = await executeS5Execute(input as S5ExecuteInput);
      return formatS5ExecuteResult(s5Output, {
        strategyName: (input as any).strategyName,
        confirmed: (input as any).confirmExecution ?? false,
      });

    default:
      return "未知步骤";
  }
}

/**
 * 获取步骤执行函数
 */
export function getStepExecutor(stepId: StrategyStepId) {
  switch (stepId) {
    case "S1_RESEARCH":
      return { execute: executeS1Research, format: formatS1ResearchResult };
    case "S2_ANALYSIS":
      return { execute: executeS2Analysis, format: formatS2AnalysisResult };
    case "S3_DESIGN":
      return { execute: executeS3Design, format: formatS3DesignResult };
    case "S4_VALIDATE":
      return { execute: executeS4Validate, format: formatS4ValidateResult };
    case "S5_EXECUTE":
      return { execute: executeS5Execute, format: formatS5ExecuteResult };
    default:
      return null;
  }
}
