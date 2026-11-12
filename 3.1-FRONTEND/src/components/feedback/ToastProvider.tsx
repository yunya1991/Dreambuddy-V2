'use client';

import { create } from 'zustand';

export type ToastType = 'success' | 'error' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  durationMs: number;
}

interface ToastStore {
  toasts: Toast[];
  show: (toast: Omit<Toast, 'id'>) => string;
  dismiss: (id: string) => void;
}

/** Toast 状态 store — 全局单例，零外部依赖 */
export const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],
  show: (toast) => {
    const id = Math.random().toString(36).slice(2, 10);
    const fullDuration = toast.durationMs ?? 3000;
    const full: Toast = { ...toast, durationMs: fullDuration, id };
    set((s) => ({ toasts: [...s.toasts, full] }));
    if (full.durationMs > 0) {
      setTimeout(() => get().dismiss(id), full.durationMs);
    }
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

/** 便捷 hook：直接 show({ type: 'error', message: 'xxx' }) */
export function useToast() {
  const show = useToastStore((s) => s.show);
  const dismiss = useToastStore((s) => s.dismiss);
  return { show, dismiss };
}

/** ToastProvider — 在 dashboard layout 根挂一次即可 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <ToastViewport />
    </>
  );
}

const TYPE_STYLES: Record<ToastType, string> = {
  success: 'border-[var(--color-status-success)] bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]',
  error: 'border-[var(--color-status-danger)] bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]',
  info: 'border-[var(--color-status-info)] bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]',
};

function ToastViewport() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div
      data-testid="toast-viewport"
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          data-testid={`toast-${t.type}`}
          role="status"
          className={`pointer-events-auto rounded-md border px-4 py-3 text-sm shadow-lg ${TYPE_STYLES[t.type]}`}
        >
          <span className="mr-2">
            {t.type === 'success' ? '✓' : t.type === 'error' ? '✗' : 'ℹ'}
          </span>
          <span>{t.message}</span>
          <button
            type="button"
            aria-label="关闭"
            onClick={() => dismiss(t.id)}
            className="ml-3 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
