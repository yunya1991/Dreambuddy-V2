/**
 * DreamBuddy 共享 Python IPC 客户端 (D3-b)
 *
 * 目标：多个 Cordis 插件复用同一个 python-server/server.py 子进程，
 * 把 headless runtime 的常驻 Python 进程从「每插件一个」收敛为「每组一个」。
 *
 * 单例实现：状态挂在 process 级的 globalThis registry 上，
 * 即使各插件目录是独立副本(非符号链接)，也能共享同一个客户端实例。
 * 分组键 = executable + serverPath + env(C 排序后 JSON)：
 *   - 普通插件组：env 为空 → 共用一个 server.py
 *   - superagent-p0 组：DSH_ENABLE_UPGRADE=true → 单独一个(HC-2 总闸门隔离)
 *
 * 生命周期：子进程随 Node 进程退出统一回收，单个插件 dispose 不会 kill 共享进程，
 * 避免误伤仍在使用的其他插件。
 */

import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";

const CURRENT_SCHEMA_VERSION = "1.0.0";
const REGISTRY_KEY = Symbol.for("dreambuddy.shared-ipc.registry");
const EXIT_HOOK_KEY = Symbol.for("dreambuddy.shared-ipc.exit-hook");

function _sortedEnvKey(env) {
  const keys = Object.keys(env || {}).sort();
  return keys.map((k) => `${k}=${env[k]}`).join("&");
}

export class PythonIPCClient {
  constructor(executable, serverPath, env = {}) {
    this.executable = executable;
    this.serverPath = serverPath;
    this.env = { ...process.env, ...env };
    this.schemaVersion = CURRENT_SCHEMA_VERSION;
    this.process = null;
    this.pendingRequests = new Map();
    this.started = false;
    this.startPromise = null;
  }

  async start() {
    if (this.started) return true;
    if (this.startPromise) return this.startPromise;
    this.startPromise = this._doStart();
    try {
      return await this.startPromise;
    } catch (e) {
      // 允许下一次调用重试(FAIL-OPEN 由调用方处理)
      this.startPromise = null;
      throw e;
    }
  }

  async _doStart() {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error("Python IPC server 启动超时 (15s)"));
      }, 15000);

      this.process = spawn(this.executable, [this.serverPath], {
        stdio: ["pipe", "pipe", "pipe"],
        env: this.env,
      });

      // server.py 启动日志：结构化 JSON，message 含 "启动"
      let stderrBuf = "";
      this.process.stderr.on("data", (data) => {
        stderrBuf += data.toString();
        if (stderrBuf.includes("启动") && !this.started) {
          this.started = true;
          clearTimeout(timeout);
          this._handshake().then(() => resolve(true)).catch(reject);
        }
      });

      let stdoutBuf = "";
      this.process.stdout.on("data", (data) => {
        stdoutBuf += data.toString();
        const lines = stdoutBuf.split("\n");
        stdoutBuf = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const resp = JSON.parse(line);
            const pending = this.pendingRequests.get(resp.id);
            if (pending) {
              this.pendingRequests.delete(resp.id);
              pending(resp);
            }
          } catch {}
        }
      });

      this.process.on("exit", () => {
        this.started = false;
        this.process = null;
        this.startPromise = null;
      });

      this.process.on("error", (err) => {
        clearTimeout(timeout);
        reject(new Error(`Python IPC server 启动失败: ${err.message}`));
      });
    });
  }

  async ensureStarted() {
    if (this.started) return true;
    return this.start();
  }

  async _handshake() {
    const resp = await this.send({
      schema_version: this.schemaVersion,
      message_type: "handshake_request",
      client_version: this.schemaVersion,
      id: randomUUID(),
      timestamp: new Date().toISOString(),
    });
    if (!resp.ok) {
      throw new Error(`握手失败: ${resp.error?.message || "unknown"}`);
    }
  }

  async send(request) {
    if (!this.started || !this.process) {
      throw new Error("Python IPC server 未启动");
    }
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(request.id);
        reject(new Error(`IPC 请求超时: ${request.method || request.message_type}`));
      }, 15000);

      this.pendingRequests.set(request.id, (resp) => {
        clearTimeout(timeout);
        resolve(resp);
      });

      this.process.stdin.write(JSON.stringify(request) + "\n");
    });
  }

  async callMethod(method, params = {}) {
    return this.send({
      schema_version: this.schemaVersion,
      message_type: "request",
      method,
      params,
      id: randomUUID(),
      timestamp: new Date().toISOString(),
    });
  }

  stop() {
    if (this.process) {
      this.process.kill("SIGTERM");
      this.process = null;
    }
    this.started = false;
    this.startPromise = null;
  }
}

function _registry() {
  if (!globalThis[REGISTRY_KEY]) {
    globalThis[REGISTRY_KEY] = new Map();
  }
  return globalThis[REGISTRY_KEY];
}

function _cleanupAll() {
  for (const c of _registry().values()) {
    try {
      // 进程即将退出，不需要优雅 drain；SIGTERM 可能被 python 侧忽略，直接 SIGKILL
      if (c.process) c.process.kill("SIGKILL");
    } catch {}
  }
}

function _installExitHooks() {
  if (globalThis[EXIT_HOOK_KEY]) return;
  globalThis[EXIT_HOOK_KEY] = true;
  process.once("exit", _cleanupAll);
  // SIGINT / SIGTERM 时先回收子进程，再以标准退出码退出，避免常驻 server.py 泄漏
  process.once("SIGINT", () => {
    _cleanupAll();
    process.exit(130);
  });
  process.once("SIGTERM", () => {
    _cleanupAll();
    process.exit(143);
  });
}

/**
 * 取共享 IPC 客户端。相同 (executable, serverPath, env) 返回同一实例。
 */
export function getSharedIPC({ serverPath, executable = "python3", env = {} } = {}) {
  if (!serverPath) {
    throw new Error("getSharedIPC: serverPath 必填");
  }
  const registry = _registry();
  const key = `${executable}|${serverPath}|${_sortedEnvKey(env)}`;
  let client = registry.get(key);
  if (!client) {
    client = new PythonIPCClient(executable, serverPath, env);
    registry.set(key, client);
    _installExitHooks();
  }
  return client;
}

/** 查询当前共享客户端数量(诊断用) */
export function sharedIPCStats() {
  return { count: _registry().size, keys: [..._registry().keys()] };
}

/** 停止并清空全部共享客户端(测试用；正常运行时不要调用) */
export function shutdownSharedIPC() {
  for (const c of _registry().values()) {
    try {
      c.stop();
    } catch {}
  }
  _registry().clear();
}
