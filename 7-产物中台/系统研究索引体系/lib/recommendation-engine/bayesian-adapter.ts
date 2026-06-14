// ============================================================================
// 推荐策略引擎: 贝叶斯优化适配器
// ============================================================================
// 封装调用 6-TRADING/scripts/bayesian_opt_engine.py
// 接收候选策略的回测结果，输出优化后的参数
// ============================================================================

import { spawn } from "child_process";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import type { BayesianOptimizedParams, OptimizedParamValues } from "./types";
import type { BacktestEngineOutput } from "./backtest-adapter";
import type { CandidateStrategy } from "./types";

// ----------------------------------------------------------------------------
// 路径配置
// ----------------------------------------------------------------------------

function resolveSkillsDir(): string {
  const home = os.homedir();
  const candidates = [
    path.join(home, "WorkBuddy", "dreambuddy-v2", "6-TRADING", "scripts"),
    path.join(home, "WorkBuddy", "dreambuddy-v2", "6-TRADING"),
    path.join(process.cwd(), "..", "..", "6-TRADING", "scripts"),
  ];

  for (const candidate of candidates) {
    const scriptPath = path.join(candidate, "bayesian_opt_engine.py");
    if (fs.existsSync(scriptPath)) {
      return candidate;
    }
  }

  return candidates[0];
}

function getBayesianScriptPath(): string {
  return path.join(resolveSkillsDir(), "bayesian_opt_engine.py");
}

// ----------------------------------------------------------------------------
// 优化参数空间 (9维)
// ----------------------------------------------------------------------------

export const BAYESIAN_PARAM_SPACE = {
  strong_score_threshold: { min: 55, max: 75 },   // θ1
  weak_score_threshold:   { min: 40, max: 60 },   // θ2
  short_score_threshold:  { min: 25, max: 45 },   // θ3
  level_spacing_k:       { min: 0.3, max: 1.0 },  // θ4
  tp_level_1:           { min: 1.5, max: 4.0 },  // θ5
  tp_level_2:           { min: 2.5, max: 5.0 },  // θ6
  tp_level_3:           { min: 4.0, max: 8.0 },  // θ7
  base_pos_pct:         { min: 50, max: 150 },    // θ8
  sl_cooldown_days:      { min: 0, max: 7 },       // θ9
} as const;

export type BayesianParamName = keyof typeof BAYESIAN_PARAM_SPACE;

// ----------------------------------------------------------------------------
// 优化选项
// ----------------------------------------------------------------------------

export interface BayesianOptimizationOptions {
  /** 优化目标，默认 sharpe */
  objective?: "sharpe" | "profit_factor" | "calmar";
  /** 优化轮数，默认 200 */
  rounds?: number;
  /** 快速模式（少量迭代，用于测试），默认 false */
  quickMode?: boolean;
  /** 超时时间（毫秒），默认 30 分钟 */
  timeoutMs?: number;
}

// ----------------------------------------------------------------------------
// 核心优化函数
// ----------------------------------------------------------------------------

/**
 * 对候选策略运行贝叶斯参数优化
 */
export async function runBayesianOptimization(
  candidate: CandidateStrategy,
  backtestOutput: BacktestEngineOutput,
  options: BayesianOptimizationOptions = {}
): Promise<BayesianOptimizedParams | null> {
  const scriptPath = getBayesianScriptPath();
  const outputDir = path.join(
    os.homedir(),
    ".workbuddy",
    "artifacts",
    "recommendation",
    "optimization"
  );
  const reportFile = path.join(outputDir, `backtest_report_${Date.now()}.json`);
  const outputFile = path.join(
    outputDir,
    `optimization_${candidate.name.replace(/[^a-zA-Z0-9_\-]/g, "_")}_${Date.now()}.md`
  );

  fs.mkdirSync(outputDir, { recursive: true });

  // 先写入回测报告（bayesian_opt_engine.py 需要读取此报告）
  const backtestReport = {
    backtest_status: backtestOutput.backtest_status,
    sharpe_ratio: backtestOutput.sharpe_ratio,
    max_drawdown: backtestOutput.max_drawdown,
    win_rate: backtestOutput.win_rate,
    profit_factor: backtestOutput.profit_factor,
    total_return: backtestOutput.total_return,
    annual_return: backtestOutput.annual_return,
    total_trades: backtestOutput.total_trades,
  };

  try {
    fs.writeFileSync(reportFile, JSON.stringify(backtestReport, null, 2));
  } catch {
    // 写入失败则跳过（引擎会使用内联基线）
  }

  const objective = options.objective || "sharpe";
  const timeoutMs = options.timeoutMs || 30 * 60 * 1000;

  return new Promise((resolve, reject) => {
    const args = [
      scriptPath,
      "--report",
      reportFile,
      "--objective",
      objective,
      "--output",
      outputFile,
    ];

    if (options.quickMode) {
      args.push("--quick");
    }

    let stdout = "";
    let stderr = "";

    const proc = spawn("python3", args, {
      timeout: timeoutMs,
      stdio: ["ignore", "pipe", "pipe"],
    });

    proc.stdout?.on("data", (data) => {
      stdout += data.toString();
    });

    proc.stderr?.on("data", (data) => {
      stderr += data.toString();
    });

    proc.on("close", (code) => {
      // 解析优化结果
      const optimizedParams = parseOptimizationOutput(stdout, candidate);

      if (optimizedParams) {
        resolve(optimizedParams);
      } else {
        // 优化失败时返回 null
        console.warn(
          `[bayesian-adapter] 优化失败 ${candidate.name}，使用原始参数: ${stderr}`
        );
        resolve(null);
      }
    });

    proc.on("error", (error) => {
      console.error(`[bayesian-adapter] 优化进程错误: ${error.message}`);
      resolve(null); // 不拒绝，返回 null 让调用方使用原始参数
    });
  });
}

/**
 * 批量运行贝叶斯优化
 */
export async function runBatchBayesianOptimization(
  candidates: CandidateStrategy[],
  backtestOutputs: BacktestEngineOutput[],
  options: BayesianOptimizationOptions = {}
): Promise<(BayesianOptimizedParams | null)[]> {
  const results: (BayesianOptimizedParams | null)[] = [];

  for (let i = 0; i < candidates.length; i++) {
    const candidate = candidates[i];
    const backtestOutput = backtestOutputs[i];

    // 只对通过基线的策略进行优化
    if (
      backtestOutput.backtest_status === "OK" &&
      backtestOutput.sharpe_ratio > 0
    ) {
      try {
        const result = await runBayesianOptimization(
          candidate,
          backtestOutput,
          options
        );
        results.push(result);
      } catch (error) {
        console.error(`[bayesian-adapter] 优化异常 ${candidate.name}:`, error);
        results.push(null);
      }
    } else {
      results.push(null);
    }
  }

  return results;
}

// ----------------------------------------------------------------------------
// 辅助函数：从 stdout 解析优化结果
// ----------------------------------------------------------------------------

function parseOptimizationOutput(
  stdout: string,
  candidate: CandidateStrategy
): BayesianOptimizedParams | null {
  // 从 stdout 中提取优化后的参数
  // bayesian_opt_engine.py 会输出类似以下格式的参数信息
  const lines = stdout.split("\n");
  const paramValues: Partial<Record<BayesianParamName, number>> = {};

  for (const line of lines) {
    const trimmed = line.trim();

    // 解析参数名=值的格式
    for (const [paramName, range] of Object.entries(BAYESIAN_PARAM_SPACE)) {
      const pattern = new RegExp(`${paramName}[\\s:=]+([\\d.]+)`, "i");
      const match = trimmed.match(pattern);
      if (match) {
        const val = parseFloat(match[1]);
        if (val >= range.min && val <= range.max) {
          paramValues[paramName as BayesianParamName] = val;
        }
      }
    }
  }

  // 检查是否解析到足够的参数（至少解析到主要参数）
  const paramCount = Object.keys(paramValues).length;

  if (paramCount >= 5) {
    // 构建优化后的参数
    const optimizedParams: OptimizedParamValues = {
      entryThreshold: paramValues.strong_score_threshold || 65,
      levelSpacingK: paramValues.level_spacing_k || 0.5,
      stopLossMult: 20, // 固定值，stop_loss_pct = 20%
      tpLevel1: paramValues.tp_level_1 || 2.0,
      tpLevel2: paramValues.tp_level_2 || 3.5,
      tpLevel3: paramValues.tp_level_3 || 5.0,
      weakPosPct: paramValues.base_pos_pct || 100,
      strongPosPct: paramValues.base_pos_pct || 100,
    };

    // 计算改进幅度
    const improvement = {
      sharpeImprovement: 0, // 需要优化前后的对比
      ddImprovement: 0,
    };

    return {
      strategyId: candidate.name,
      originalParams: candidate,
      optimizedParams,
      optimizationRounds: 200,
      improvement,
      confidence: Math.min(paramCount / 9, 1.0), // 置信度 = 解析到的参数数量/9
    };
  }

  // 尝试从输出文件解析
  return null;
}

// ----------------------------------------------------------------------------
// 默认参数生成
// ----------------------------------------------------------------------------

/**
 * 生成默认优化参数（当贝叶斯优化不可用时）
 */
export function generateDefaultOptimizedParams(
  candidate: CandidateStrategy
): OptimizedParamValues {
  // 基于候选策略的 confidence 和 direction 生成合理默认值
  const confidence = candidate.confidence / 100;

  return {
    entryThreshold: 55 + confidence * 20,     // 55-75
    levelSpacingK: 0.5 + (1 - confidence) * 0.3, // 0.5-0.8
    stopLossMult: 20,                         // 固定20%
    tpLevel1: 2.0 + confidence * 2.0,        // 2-4
    tpLevel2: 3.5 + confidence * 1.5,        // 3.5-5
    tpLevel3: 5.0 + confidence * 3.0,        // 5-8
    weakPosPct: 50 + confidence * 50,         // 50-100
    strongPosPct: 60 + confidence * 40,       // 60-100
  };
}
