/**
 * GAP-21 DSH 运行时副作用探针（自包含 bundle 包入口）
 *
 * 一个文件同时承担两个角色，便于作为 `dsh plugin add` 的 bundle 包分发：
 *   1) 采集器：hook timer / connection / handle，subscription 由 loader 登记；
 *   2) Cordis 插件：patch `Fiber.prototype.effect`，把归属与订阅登记接上。
 *
 * 采集器也可脱离插件单独使用：
 *   node --import ./index.mjs ...
 *   await withOwner(pluginId, () => applyPlugin(ctx));
 *   const snap = snapshot(); // 交给 Python A3-3 验收
 *
 * 说明：
 * - timer / connection / handle 由本模块 hook（clear/close/exit 时自动注销）。
 * - subscription 无法从 Node 外部枚举 Cordis ctx，必须由 loader 调
 *   registerSubscription(owner, id) 登记；未开启订阅采集时 complete=false，
 *   Python 侧会拒绝把它当作卸载证据。
 * - Cordis 的 `ctx.on` 最终走 `fiber.effect(..., 'ctx.on("<event>")')`，因此只需
 *   patch `Fiber.prototype.effect` 即可同时拿到订阅与副作用归属，无需改 Cordis/DSH。
 */

import { AsyncLocalStorage } from 'node:async_hooks';
import childProcess from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';

/* ---------------------------------------------------------------- 采集器 */

const owners = new AsyncLocalStorage();
const timers = new Map();
const sockets = new Map();
const handles = new Map();
const subscriptions = new Map();
let subscriptionTracking = false;
let counter = 0;

const nextId = (prefix) => `${prefix}:${++counter}`;
const ownerOf = () => owners.getStore() || 'unknown';

export function withOwner(pluginId, fn) {
  return owners.run(pluginId, fn);
}

export function enableSubscriptionTracking() {
  subscriptionTracking = true;
}

export function registerSubscription(pluginId, id) {
  subscriptions.set(id, pluginId);
  return id;
}

export function unregisterSubscription(id) {
  subscriptions.delete(id);
}

const nativeSetInterval = globalThis.setInterval;
const nativeSetTimeout = globalThis.setTimeout;
const nativeClearInterval = globalThis.clearInterval;
const nativeClearTimeout = globalThis.clearTimeout;

globalThis.setInterval = function (fn, ms, ...args) {
  const id = nextId('timer');
  const handle = nativeSetInterval(fn, ms, ...args);
  timers.set(id, { id, owner: ownerOf(), handle });
  return handle;
};

globalThis.setTimeout = function (fn, ms, ...args) {
  const id = nextId('timer');
  const owner = ownerOf();
  const wrapped = function (...cbArgs) {
    timers.delete(id);
    return fn.apply(this, cbArgs);
  };
  const handle = nativeSetTimeout(wrapped, ms, ...args);
  timers.set(id, { id, owner, handle });
  return handle;
};

function clearTracked(handle, map, nativeClear) {
  for (const [id, record] of map) {
    if (record.handle === handle) {
      map.delete(id);
      break;
    }
  }
  nativeClear(handle);
}

globalThis.clearInterval = (handle) => clearTracked(handle, timers, nativeClearInterval);
globalThis.clearTimeout = (handle) => clearTracked(handle, timers, nativeClearTimeout);

const nativeConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  if (!this.__probeId) {
    const id = nextId('conn');
    this.__probeId = id;
    sockets.set(id, { id, owner: ownerOf() });
    this.once('close', () => sockets.delete(id));
  }
  return nativeConnect.apply(this, args);
};

const nativeWatch = fs.watch;
fs.watch = function (...args) {
  const watcher = nativeWatch.apply(this, args);
  const id = nextId('handle');
  handles.set(id, { id, owner: ownerOf() });
  const nativeClose = watcher.close.bind(watcher);
  watcher.close = () => {
    handles.delete(id);
    return nativeClose();
  };
  return watcher;
};

const nativeSpawn = childProcess.spawn;
childProcess.spawn = function (...args) {
  const child = nativeSpawn.apply(this, args);
  const id = nextId('handle');
  handles.set(id, { id, owner: ownerOf() });
  child.once('exit', () => handles.delete(id));
  return child;
};

function collect(map) {
  return [...map.values()].map(({ id, owner }) => ({ id, owner }));
}

export function snapshot(now = new Date().toISOString()) {
  const unavailable = subscriptionTracking ? [] : ['subscription'];
  const pluginIds = new Set();
  for (const record of [...timers.values(), ...sockets.values(), ...handles.values()]) {
    if (record.owner !== 'unknown') pluginIds.add(record.owner);
  }
  for (const owner of subscriptions.values()) {
    if (owner !== 'unknown') pluginIds.add(owner);
  }
  return {
    schema_version: '1.0',
    plugins: [...pluginIds].sort(),
    effects: {
      subscription: [...subscriptions].map(([id, owner]) => ({ id, owner })),
      connection: collect(sockets),
      handle: collect(handles),
      timer: collect(timers),
    },
    probe: {
      complete: subscriptionTracking,
      source: 'dsh-node-instrument',
      at: now,
      unavailable,
    },
  };
}

export function reset() {
  timers.clear();
  sockets.clear();
  handles.clear();
  subscriptions.clear();
  subscriptionTracking = false;
  counter = 0;
}

/* ------------------------------------------------------------ Cordis 插件 */

const patched = new WeakSet();

function fiberName(fiber) {
  const runtimeName = fiber.runtime?.name;
  if (runtimeName) return runtimeName;
  try {
    return fiber.name || 'unknown';
  } catch {
    return 'unknown';
  }
}

function subscriptionId(owner, label) {
  const raw = label.slice('ctx.on('.length, -1);
  let event = raw;
  try {
    event = JSON.parse(raw);
  } catch {
    // 非字符串事件（如 symbol）保留原始文本
  }
  return `sub:${owner}:${String(event)}`;
}

export function installProbe(target) {
  enableSubscriptionTracking();
  const proto =
    typeof target === 'function' ? target.prototype : Object.getPrototypeOf(target);
  if (!proto || typeof proto.effect !== 'function') {
    throw new TypeError('installProbe 需要 Fiber 实例或 Fiber 类（含 effect）');
  }
  if (patched.has(proto)) return () => {};

  const originalEffect = proto.effect;

  proto.effect = function effect(callback, label = 'anonymous') {
    const owner = fiberName(this);
    const isSubscription =
      typeof label === 'string' && label.startsWith('ctx.on(');

    const dispose = originalEffect.call(
      this,
      () => withOwner(owner, callback),
      label,
    );
    if (!isSubscription) return dispose;

    const id = subscriptionId(owner, label);
    registerSubscription(owner, id);
    // fiber 销毁时注销（不依赖调用方手动 dispose）
    originalEffect.call(
      this,
      () => () => unregisterSubscription(id),
      'probe.subscription.cleanup',
    );
    return () => {
      unregisterSubscription(id);
      return dispose();
    };
  };

  patched.add(proto);
  return () => {
    proto.effect = originalEffect;
    patched.delete(proto);
  };
}

export const name = 'dreambuddy-side-effect-probe';

export function apply(ctx) {
  const uninstall = installProbe(ctx.fiber);
  ctx.effect(() => uninstall, 'dreambuddy.probe.install');
}
