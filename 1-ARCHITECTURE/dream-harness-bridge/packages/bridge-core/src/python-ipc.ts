/**
 * F-01: Python IPC Server 启动/停止
 *
 * 职责:
 * 1. spawn Python IPC server 子进程
 * 2. 停止 Python IPC server 子进程（F-08 优雅关闭 + 孤儿进程清理）
 * 3. 提供 ChildProcess 句柄给 protocol-client 做握手
 *
 * 来源: SPEC v0.3 七补.1 F-01 + 七补.2 F-08
 * 调研: B1 Sidecar 模式 + A5 插件生命周期
 */

import { spawn, ChildProcess } from "node:child_process";
import { resolve } from "node:path";

export interface StartPythonIPCServerOptions {
  serverPath: string;
  schemaVersion?: string;
  pythonExecutable?: string;
  cwd?: string;
  env?: Record<string, string>;
}

export async function startPythonIPCServer(
  options: StartPythonIPCServerOptions
): Promise<ChildProcess> {
  const {
    serverPath,
    schemaVersion,
    pythonExecutable = "python3",
    cwd,
    env = {},
  } = options;

  const resolvedPath = resolve(cwd ?? process.cwd(), serverPath);

  const pyEnv = {
    ...process.env,
    ...env,
    // F-01: 通过环境变量传递 schema_version
    ...(schemaVersion ? { DHB_SCHEMA_VERSION: schemaVersion } : {}),
  };

  const child = spawn(pythonExecutable, [resolvedPath], {
    stdio: ["pipe", "pipe", "pipe"],
    cwd,
    env: pyEnv,
  });

  // 监听 stderr（F-14 调试工具配套：结构化日志）
  // 同时用于启动检测（Python server 启动时会输出 stderr INFO 日志）
  const startupPromise = new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error("Python IPC server 启动超时（3s）"));
    }, 3000);

    const onStderrData = (chunk: Buffer) => {
      const lines = chunk.toString().trim().split("\n");
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const logEntry = JSON.parse(line);
          console.error(
            `[Python IPC stderr] [${logEntry.level}] ${logEntry.message}`
          );
          // 检测启动日志
          if (logEntry.level === "INFO" && logEntry.message.includes("启动")) {
            clearTimeout(timeout);
            resolve();
          }
        } catch {
          console.error(`[Python IPC stderr] ${line}`);
        }
      }
    };

    if (child.stderr) {
      child.stderr.on("data", onStderrData);
    }

    // 如果进程立即退出，说明启动失败
    child.once("exit", (code) => {
      clearTimeout(timeout);
      if (code !== null) {
        reject(
          new Error(`Python IPC server 启动后立即退出: code=${code}`)
        );
      }
    });
  });

  // 监听进程退出（F-08 健康检查）
  child.on("exit", (code, signal) => {
    console.log(
      `[Python IPC] 进程退出: code=${code} signal=${signal} pid=${child.pid}`
    );
  });

  child.on("error", (err) => {
    console.error(`[Python IPC] 进程错误: ${err.message}`);
  });

  // 等待 Python server 启动（stderr 输出启动日志）
  await startupPromise;

  return child;
}

export async function stopPythonIPCServer(
  child: ChildProcess,
  timeoutMs: number = 5000
): Promise<void> {
  if (child.killed || child.exitCode !== null) {
    return;
  }

  // F-08: 优雅关闭 — 发 SIGTERM，等待 drain in-flight requests
  child.kill("SIGTERM");

  // 等待进程退出
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      // 超时强制 kill（F-08: SIGTERM → SIGKILL 降级序列）
      if (!child.killed) {
        console.warn(
          `[Python IPC] SIGTERM 超时 ${timeoutMs}ms，发送 SIGKILL`
        );
        child.kill("SIGKILL");
      }
      resolve();
    }, timeoutMs);

    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/**
 * F-08: 检查 Python server 是否存活
 */
export function isAlive(child: ChildProcess): boolean {
  return !child.killed && child.exitCode === null;
}

/**
 * F-08: 心跳检查（读 stderr HEARTBEAT 行）
 */
export async function checkHeartbeat(
  child: ChildProcess,
  timeoutMs: number = 10000
): Promise<boolean> {
  // Phase 0 POC: 简化版 — 检查进程是否存活
  // Phase 1: 完整版 — 读 stderr HEARTBEAT 行
  return isAlive(child);
}
