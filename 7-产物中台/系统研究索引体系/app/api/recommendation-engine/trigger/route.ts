// ============================================================================
// 推荐策略引擎: 手动触发 API
// ============================================================================
// POST /api/recommendation-engine/trigger
// 手动触发一轮推荐策略生成（跳过定时）
// ============================================================================

import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";
import os from "os";

export const dynamic = "force-dynamic";

// 引擎脚本路径
function getEngineScriptPath(): string {
  const base = path.join(os.homedir(), "WorkBuddy", "dreambuddy-v2", "7-产物中台", "系统研究索引体系", "scripts", "recommendation-engine", "engine.py");
  return base;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}));
    const force = body.force === true;
    const baseline = body.baseline || "v9";

    const enginePath = getEngineScriptPath();

    // 检查引擎脚本是否存在
    const fs = await import("node:fs");
    if (!fs.existsSync(enginePath)) {
      return NextResponse.json(
        {
          success: false,
          error: `引擎脚本不存在: ${enginePath}`,
          hint: "请确保引擎脚本已创建并位于正确路径",
        },
        { status: 404 }
      );
    }

    // 构建命令
    const args = ["python3", enginePath];
    if (force) args.push("--force");
    args.push("--baseline", baseline);

    const runId = `manual-${Date.now()}`;

    return new Promise((resolve) => {
      let output = "";
      let errorOutput = "";

      const proc = spawn("python3", [
        enginePath,
        ...(force ? ["--force"] : []),
        "--baseline",
        baseline,
      ]);

      proc.stdout.on("data", (data) => {
        output += data.toString();
      });

      proc.stderr.on("data", (data) => {
        errorOutput += data.toString();
      });

      proc.on("close", (code) => {
        if (code === 0) {
          resolve(
            NextResponse.json({
              success: true,
              runId,
              message: "引擎运行成功",
              output: output.slice(-2000), // 保留最后 2000 字符
            })
          );
        } else {
          resolve(
            NextResponse.json(
              {
                success: false,
                runId,
                error: `引擎运行失败 (exit code: ${code})`,
                output: output.slice(-2000),
                stderr: errorOutput.slice(-1000),
              },
              { status: 500 }
            )
          );
        }
      });

      // 超时保护：5 分钟
      setTimeout(() => {
        proc.kill();
        resolve(
          NextResponse.json(
            {
              success: false,
              runId,
              error: "引擎运行超时（5分钟）",
              output: output.slice(-2000),
            },
            { status: 504 }
          )
        );
      }, 5 * 60 * 1000);
    });
  } catch (error) {
    console.error("[recommendation-engine/trigger]", error);
    return NextResponse.json(
      { success: false, error: "触发引擎失败" },
      { status: 500 }
    );
  }
}
