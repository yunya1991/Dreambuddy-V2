'use client';

import { useEffect } from 'react';

/**
 * Next.js 构建产物哈希在每次 build 后变化，旧静态 chunk 会被删除。
 * 已打开的标签页若仍持有旧构建的 chunk 清单，路由跳转时请求旧 chunk 就会 404，
 * 表现为「页面出错了 / Loading chunk N failed」。
 *
 * 这里做兜底：识别到 chunk 加载失败时强制整页重载一次，让浏览器拿到当前构建的
 * chunk 清单。用 sessionStorage 打时间戳避免失败时无限刷新。
 */

const CHUNK_ERROR_PATTERN =
  /Loading chunk \d+ failed|ChunkLoadError|Loading CSS chunk \d+ failed|Failed to fetch dynamically imported module|error loading dynamically imported module/i;

const RELOAD_TS_KEY = 'dreambuddy:chunk-reload-at';
const RELOAD_COOLDOWN_MS = 30_000;

export function isChunkLoadError(input: unknown): boolean {
  if (!input) return false;
  if (typeof input === 'string') return CHUNK_ERROR_PATTERN.test(input);
  if (input instanceof Error) {
    return CHUNK_ERROR_PATTERN.test(`${input.name} ${input.message}`);
  }
  const maybe = input as { message?: unknown; name?: unknown };
  if (typeof maybe.message === 'string') {
    return CHUNK_ERROR_PATTERN.test(`${String(maybe.name ?? '')} ${maybe.message}`);
  }
  return false;
}

/** 触发一次整页重载；冷却窗口内重复调用会返回 false，避免刷新死循环。 */
export function reloadOnce(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const last = Number(window.sessionStorage.getItem(RELOAD_TS_KEY) ?? 0);
    if (Number.isFinite(last) && Date.now() - last < RELOAD_COOLDOWN_MS) return false;
    window.sessionStorage.setItem(RELOAD_TS_KEY, String(Date.now()));
  } catch {
    // sessionStorage 不可用（隐私模式等）时直接重载
  }
  window.location.reload();
  return true;
}

/**
 * 挂在根布局上的监听器：chunk 加载失败有时不会进入 error boundary
 * （例如动态 import 的 promise rejection），这里从 window 层兜住。
 */
export function ChunkLoadGuard() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      if (isChunkLoadError(event.error) || isChunkLoadError(event.message)) {
        reloadOnce();
      }
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      if (isChunkLoadError(event.reason)) {
        reloadOnce();
      }
    };

    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
    };
  }, []);

  return null;
}
