'use client';

import { useEffect } from 'react';

/**
 * 全局错误边界（global-error.tsx）
 * 仅在 App Router 全局崩溃（包括 layout.tsx）时渲染。
 * 不展示堆栈；提供回到首页。
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.warn('[GlobalErrorBoundary] crash:', error?.message);
  }, [error]);

  return (
    <html lang="zh">
      <body className="bg-[var(--color-bg-primary)] text-[var(--color-text-primary)]">
        <div className="flex min-h-screen items-center justify-center p-8">
          <div className="text-center">
            <h1 className="mb-2 text-2xl font-bold text-[var(--color-status-danger)]">
              应用崩溃
            </h1>
            <p className="mb-4 text-[var(--color-text-secondary)]">
              {error?.message ?? '发生了未知错误'}
            </p>
            <button
              type="button"
              onClick={reset}
              className="rounded-md bg-[var(--color-sacg-a)] px-4 py-2 text-sm text-white hover:opacity-90"
            >
              返回首页
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
