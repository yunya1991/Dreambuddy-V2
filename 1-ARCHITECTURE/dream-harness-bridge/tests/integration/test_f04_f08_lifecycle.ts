/**
 * F-04: Plugin 生命周期 + F-08: 进程健康检查
 *
 * 测试目标:
 * 1. start: spawn Python server 成功，进程存活
 * 2. stop: SIGTERM 优雅关闭，进程退出
 * 3. health-check: isAlive 返回 true（存活）/ false（已停止）
 * 4. stop 后 isAlive 返回 false
 * 5. 重复 stop 不抛异常（幂等）
 * 6. 进程退出事件被捕获
 *
 * 来源: SPEC v0.3 七补.1 F-04 + 七补.2 F-08
 * 调研: A5 插件生命周期 + B1 Sidecar 模式
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import type { ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import {
  startPythonIPCServer,
  stopPythonIPCServer,
  isAlive,
  checkHeartbeat,
} from "../../packages/bridge-core/src/python-ipc";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

describe("F-04 + F-08: Plugin 生命周期 + 进程健康检查", () => {
  let pyServer: ChildProcess | null = null;

  beforeEach(() => {
    pyServer = null;
  });

  afterEach(async () => {
    if (pyServer) {
      await stopPythonIPCServer(pyServer);
      pyServer = null;
    }
  });

  describe("1. start: spawn Python server", () => {
    it("spawn 成功，返回 ChildProcess 且 pid > 0", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });

      expect(pyServer).toBeDefined();
      expect(pyServer!.pid).toBeGreaterThan(0);
    });

    it("启动后进程存活（isAlive=true）", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });

      expect(isAlive(pyServer!)).toBe(true);
      expect(pyServer!.killed).toBe(false);
      expect(pyServer!.exitCode).toBeNull();
    });
  });

  describe("2. stop: SIGTERM 优雅关闭", () => {
    it("stop 后进程退出（exitCode 或 signalCode 表明已终止）", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });
      expect(isAlive(pyServer!)).toBe(true);

      await stopPythonIPCServer(pyServer!);

      // SIGTERM 终止时 exitCode=null、signalCode="SIGTERM"；正常退出时 exitCode=数字
      // 两者其一非空即表明进程已退出
      const exited =
        pyServer!.exitCode !== null || pyServer!.signalCode !== null;
      expect(exited).toBe(true);
      expect(isAlive(pyServer!)).toBe(false);
    });

    it("stop 后 isAlive 返回 false", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });
      expect(isAlive(pyServer!)).toBe(true);

      await stopPythonIPCServer(pyServer!);

      expect(isAlive(pyServer!)).toBe(false);
    });
  });

  describe("3. health-check: isAlive / checkHeartbeat", () => {
    it("存活进程 isAlive=true", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });

      expect(isAlive(pyServer!)).toBe(true);
    });

    it("已停止进程 isAlive=false", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });
      await stopPythonIPCServer(pyServer!);

      expect(isAlive(pyServer!)).toBe(false);
    });

    it("checkHeartbeat 存活进程返回 true", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });

      const hb = await checkHeartbeat(pyServer!);
      expect(hb).toBe(true);
    });

    it("checkHeartbeat 已停止进程返回 false", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });
      await stopPythonIPCServer(pyServer!);

      const hb = await checkHeartbeat(pyServer!);
      expect(hb).toBe(false);
    });
  });

  describe("4. 重复 stop 幂等", () => {
    it("重复 stop 不抛异常（幂等）", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });

      await stopPythonIPCServer(pyServer!);

      // 第二次 stop 应幂等，不抛异常
      await expect(stopPythonIPCServer(pyServer!)).resolves.toBeUndefined();

      // 第三次也不抛异常
      await expect(stopPythonIPCServer(pyServer!)).resolves.toBeUndefined();

      // 幂等后进程仍处于已退出状态
      expect(isAlive(pyServer!)).toBe(false);
    });
  });

  describe("5. 进程退出事件被捕获", () => {
    it("stop 触发 exit 事件", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });

      let exitCaptured = false;
      pyServer!.once("exit", () => {
        exitCaptured = true;
      });

      await stopPythonIPCServer(pyServer!);

      expect(exitCaptured).toBe(true);
    });

    it("进程意外退出（SIGKILL）exit 事件被捕获", async () => {
      pyServer = await startPythonIPCServer({
        serverPath: PYTHON_SERVER_PATH,
      });

      const exitPromise = new Promise<void>((resolve) => {
        pyServer!.once("exit", () => resolve());
      });

      // 模拟进程意外退出
      pyServer!.kill("SIGKILL");

      await exitPromise;

      expect(isAlive(pyServer!)).toBe(false);
      // exitCode 或 killed 至少其一表明进程已退出
      const exited = pyServer!.exitCode !== null || pyServer!.killed;
      expect(exited).toBe(true);
    });
  });
});
