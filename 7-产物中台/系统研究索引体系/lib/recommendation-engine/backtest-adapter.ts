// ============================================================================
// 推荐策略引擎: 回测适配器
// ============================================================================
// 封装调用 6-TRADING/scripts/backtest_engine_main.py
// 将候选策略参数转换为回测引擎可接受的格式
// ============================================================================

import { spawn } from "child_process";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import type { BacktestResult } from "./types";
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
    const scriptPath = path.join(candidate, "backtest_engine_main.py");
    if (fs.existsSync(scriptPath)) {
      return candidate;
    }
  }

  // 默认返回第一个候选路径
  return candidates[0];
}

function getBacktestScriptPath(): string {
  return path.join(resolveSkillsDir(), "backtest_engine_main.py");
}

// ----------------------------------------------------------------------------
// 输入/输出类型
// ----------------------------------------------------------------------------

export interface BacktestEngineOutput {
  // 核心性能指标（标准化字段，与 BacktestResult 对齐）
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  profit_factor: number;
  total_return: number;
  total_trades: number;
  annual_return: number;
  backtest_status: "OK" | "FAIL" | "ERROR";

  // 原始回测参数
  config: {
    inst_id: string;
    start_date: string;
    end_date: string;
    initial_capital: number;
  };
}

export interface BacktestOptions {
  /** 回测标的，默认 BTC-USDT-SWAP */
  symbol?: string;
  /** 开始日期，格式 YYYY-MM-DD，默认 7 天前 */
  startDate?: string;
  /** 结束日期，格式 YYYY-MM-DD，默认昨天 */
  endDate?: string;
  /** 初始资金，默认 200 */
  capital?: number;
  /** 超时时间（毫秒），默认 5 分钟 */
  timeoutMs?: number;
}

export interface BacktestResultVerbose {
  result: BacktestResult;
  outputPath: string;
  durationMs: number;
  stdout: string;
}

// ----------------------------------------------------------------------------
// 策略参数 → 回测引擎参数转换
// ----------------------------------------------------------------------------

/**
 * 将候选策略参数转换为回测引擎配置
 * 注意：回测引擎使用固定策略逻辑（马丁+Screen1/2），
 * 候选策略的 direction/confidence 等作为入场信号的参考
 */
function buildBacktestConfig(
  candidate: CandidateStrategy,
  options: BacktestOptions
): Record<string, unknown> {
  const now = new Date();
  const endDate = options.endDate || now.toISOString().slice(0, 10);
  const startDate =
    options.startDate ||
    new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);

  return {
    inst_id: options.symbol || "BTC-USDT-SWAP",
    start_date: startDate,
    end_date: endDate,
    initial_capital: options.capital || 200,
    // 候选策略的 regime/direction 作为额外上下文传给引擎
    _strategy_name: candidate.name,
    _strategy_direction: candidate.direction,
    _strategy_regime: candidate.regime,
  };
}

// ----------------------------------------------------------------------------
// 核心回测函数
// ----------------------------------------------------------------------------

/**
 * 对单个候选策略运行回测
 */
export async function runBacktest(
  candidate: CandidateStrategy,
  options: BacktestOptions = {}
): Promise<BacktestEngineOutput> {
  const scriptPath = getBacktestScriptPath();
  const outputDir = path.join(os.homedir(), ".workbuddy", "artifacts", "recommendation", "backtests");
  const outputFile = path.join(
    outputDir,
    `backtest_${candidate.name.replace(/[^a-zA-Z0-9_\-]/g, "_")}_${Date.now()}.json`
  );

  // 确保输出目录存在
  fs.mkdirSync(outputDir, { recursive: true });

  const config = buildBacktestConfig(candidate, options);
  const timeoutMs = options.timeoutMs || 5 * 60 * 1000;

  return new Promise((resolve, reject) => {
    const args = [
      scriptPath,
      "--inst",
      config.inst_id as string,
      "--from",
      config.start_date as string,
      "--to",
      config.end_date as string,
      "--capital",
      String(config.initial_capital),
      "--output",
      outputFile,
    ];

    let stdout = "";
    let stderr = "";
    let timedOut = false;

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
      if (timedOut) {
        reject(new Error(`回测超时（${timeoutMs}ms）`));
        return;
      }

      // 读取输出文件
      if (fs.existsSync(outputFile)) {
        try {
          const raw = JSON.parse(fs.readFileSync(outputFile, "utf-8"));
          resolve({
            sharpe_ratio: raw.sharpe_ratio ?? 0,
            max_drawdown: raw.max_drawdown ?? 999,
            win_rate: raw.win_rate ?? 0,
            profit_factor: raw.profit_factor ?? 0,
            total_return: raw.total_return ?? 0,
            total_trades: raw.total_trades ?? 0,
            annual_return: raw.annual_return ?? 0,
            backtest_status: raw.max_drawdown > 20 ? "FAIL" : "OK",
            config: {
              inst_id: raw.config?.inst_id || config.inst_id,
              start_date: raw.config?.start_date || config.start_date,
              end_date: raw.config?.end_date || config.end_date,
              initial_capital: raw.config?.initial_capital || config.initial_capital,
            },
          });
        } catch (parseError) {
          reject(new Error(`解析回测输出失败: ${parseError}`));
        }
      } else {
        // 输出文件不存在但进程成功，可能引擎没有 --output 参数
        // 从 stdout 解析基本指标
        const parsed = parseBacktestOutput(stdout);
        if (parsed) {
          resolve(parsed);
        } else {
          reject(new Error(`回测输出文件不存在且无法解析 stdout: ${stderr}`));
        }
      }
    });

    proc.on("error", (error) => {
      reject(new Error(`回测进程错误: ${error.message}`));
    });

    setTimeout(() => {
      timedOut = true;
      proc.kill();
    }, timeoutMs);
  });
}

/**
 * 批量运行回测（对多个候选策略）
 */
export async function runBatchBacktest(
  candidates: CandidateStrategy[],
  options: BacktestOptions = {}
): Promise<BacktestEngineOutput[]> {
  const results: BacktestEngineOutput[] = [];

  for (const candidate of candidates) {
    try {
      const result = await runBacktest(candidate, options);
      results.push(result);
    } catch (error) {
      // 单个失败不影响其他
      console.error(`[backtest-adapter] 回测失败 ${candidate.name}:`, error);
      results.push({
        sharpe_ratio: 0,
        max_drawdown: 999,
        win_rate: 0,
        profit_factor: 0,
        total_return: -999,
        total_trades: 0,
        annual_return: -999,
        backtest_status: "ERROR",
        config: {
          inst_id: options.symbol || "BTC-USDT-SWAP",
          start_date: options.startDate || "",
          end_date: options.endDate || "",
          initial_capital: options.capital || 200,
        },
      });
    }
  }

  return results;
}

// ----------------------------------------------------------------------------
// 辅助函数：从 stdout 解析回测结果
// ----------------------------------------------------------------------------

function parseBacktestOutput(stdout: string): BacktestEngineOutput | null {
  // 尝试从 stdout 中解析关键指标
  const lines = stdout.split("\n");
  const metrics: Record<string, number | string> = {};

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.includes("sharpe") || trimmed.includes("Sharpe")) {
      const match = trimmed.match(/[\d\.\-]+/);
      if (match) metrics.sharpe_ratio = parseFloat(match[0]);
    }
    if (trimmed.includes("最大回撤") || trimmed.includes("max_drawdown")) {
      const match = trimmed.match(/([\d\.]+)/);
      if (match) metrics.max_drawdown = parseFloat(match[0]);
    }
    if (trimmed.includes("胜率") || trimmed.includes("win_rate")) {
      const match = trimmed.match(/([\d\.]+)/);
      if (match) metrics.win_rate = parseFloat(match[0]);
    }
    if (trimmed.includes("盈亏比") || trimmed.includes("profit_factor")) {
      const match = trimmed.match(/([\d\.]+)/);
      if (match) metrics.profit_factor = parseFloat(match[0]);
    }
    if (trimmed.includes("总收益率") || trimmed.includes("total_return")) {
      const match = trimmed.match(/([\d\.\-]+)/);
      if (match) metrics.total_return = parseFloat(match[0]);
    }
  }

  if (metrics.sharpe_ratio !== undefined) {
    return {
      sharpe_ratio: metrics.sharpe_ratio as number,
      max_drawdown: (metrics.max_drawdown as number) || 999,
      win_rate: (metrics.win_rate as number) || 0,
      profit_factor: (metrics.profit_factor as number) || 0,
      total_return: (metrics.total_return as number) || 0,
      total_trades: (metrics.total_trades as number) || 0,
      annual_return: (metrics.annual_return as number) || 0,
      backtest_status: (metrics.max_drawdown as number) > 20 ? "FAIL" : "OK",
      config: {
        inst_id: "BTC-USDT-SWAP",
        start_date: "",
        end_date: "",
        initial_capital: 200,
      },
    };
  }

  return null;
}

// ----------------------------------------------------------------------------
// 策略回测结果 → 标准化 BacktestResult
// ----------------------------------------------------------------------------

export function convertToBacktestResult(
  candidate: CandidateStrategy,
  engineOutput: BacktestEngineOutput,
  baselineMetrics: {
    sharpe: number;
    maxDD: number;
    totalReturn: number;
  },
  backtestPeriod: "7D" | "30D" | "180D",
  baselineVersion: "v9" | "v15"
): BacktestResult {
  // 基线对比判定（使用 baseline-provider 的逻辑）
  const sharpeBetter = engineOutput.sharpe_ratio >= baselineMetrics.sharpe - 0.05;
  const ddBetter = engineOutput.max_drawdown <= baselineMetrics.maxDD + 0.5;
  const returnBetter = engineOutput.total_return >= baselineMetrics.totalReturn - 1.0;
  const betterCount = [sharpeBetter, ddBetter, returnBetter].filter(Boolean).length;

  return {
    strategyId: candidate.name, // 临时 ID
    backtestPeriod,
    symbol: engineOutput.config.inst_id,
    baselineVersion,

    // 策略性能
    sharpeRatio: engineOutput.sharpe_ratio,
    maxDrawdown: engineOutput.max_drawdown,
    winRate: engineOutput.win_rate,
    profitFactor: engineOutput.profit_factor,
    totalReturn: engineOutput.total_return,
    tradeCount: engineOutput.total_trades,

    // 基线性能
    baselineSharpe: baselineMetrics.sharpe,
    baselineMaxDrawdown: baselineMetrics.maxDD,
    baselineTotalReturn: baselineMetrics.totalReturn,

    // 对比判定
    isBetterThanBaseline: betterCount >= 3,
    betterCount,

    reportPath: undefined,
    rawMetrics: engineOutput as unknown as Record<string, unknown>,
  };
}
