'use client';

import { useEffect } from 'react';
import { isChunkLoadError, reloadOnce } from '@/lib/chunk-load-guard';

/**
 * App Router 错误边界（error.tsx）
 * 仅在 App Router 页面崩溃时渲染；不展示堆栈；提供重试。
 * chunk 加载失败（旧构建引用）自动整页重载，避免用户停在错误页。
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (isChunkLoadError(error)) {
      console.warn('[ErrorBoundary] chunk load failed, reloading:', error.message);
      reloadOnce();
      return;
    }
    console.warn('[ErrorBoundary] page error:', error?.message);
  }, [error]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center p-8">
      <div className="text-center">
        <h2 className="mb-2 text-lg font-semibold text-[var(--color-status-danger)]">
          页面出错了
        </h2>
        <p className="mb-4 text-[var(--color-text-secondary)]">
          {error?.message ?? '请稍后重试'}
        </p>
        <button
          type="button"
          onClick={reset}
          className="rounded-md bg-[var(--color-sacg-a)] px-4 py-2 text-sm text-white hover:opacity-90"
        >
          重试
        </button>
      </div>
    </div>
  );
}
