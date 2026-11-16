'use client';

// 能力选择抽屉（TASKS-20261116 T2-2 / T2-3）
// 目录来自 manifest（93 条）；预览 = stats_validate + 一次真实取数；
// 不满足前置（缺参/样本不足/运行时缺参）→ 添加禁用并显示缺什么。

import { useEffect, useMemo, useState } from 'react';
import { V3Badge } from '@/components/V3Badge';
import {
  explainCapability,
  listCapabilities,
  resolveCapability,
  runCapability,
  validateCapability,
  type CapabilityItem,
} from '@/lib/visual/api';
import { defaultArgsForSchema } from '@/lib/visual/config';
import type { PanelSpec, VisualKind } from '@/lib/visual/panelKey';
import type { CapabilitySchema } from './types';

// SPEC-54 R9：关闭后回到「args: {} + 直接 run」的旧行为，用于灰度回滚
const SCHEMA_V2 = process.env.NEXT_PUBLIC_CARDS_SCHEMA_V2 !== 'false';

const CODE_HINT: Record<string, string> = {
  missing_args: '还缺参数',
  unsupported: '当前无数据源',
  product_missing: '上游产物未生成',
  sample_insufficient: '样本不足',
  invalid_params: '参数不合法',
  not_found: '能力不存在',
  error: '能力不可用',
};

interface CapabilityPickerProps {
  open: boolean;
  mode: 'tab' | 'card';
  mounted?: string[];
  onClose: () => void;
  onPick: (panel: PanelSpec) => void;
}

interface PreviewState {
  id: string;
  ok: boolean;
  missing: string[];
  warnings: string[];
  reason?: string;
  kind?: VisualKind;
  schema?: CapabilitySchema;
}

const DOMAINS: { key: string; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'A', label: 'A 指标' },
  { key: 'E', label: 'E 关系' },
  { key: 'G', label: 'G 横截面' },
  { key: 'J', label: 'J 科研' },
  { key: 'K', label: 'K 出口' },
];

export function CapabilityPicker({
  open,
  mode,
  mounted = [],
  onClose,
  onPick,
}: CapabilityPickerProps) {
  const [items, setItems] = useState<CapabilityItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [domain, setDomain] = useState('');
  const [busyId, setBusyId] = useState('');
  const [preview, setPreview] = useState<PreviewState | null>(null);

  useEffect(() => {
    if (!open || items.length > 0) return;
    let alive = true;
    setLoading(true);
    setError(null);
    listCapabilities({ limit: 200 })
      .then((response) => {
        if (!alive) return;
        if (!response.ok) {
          setError(response.error || '目录不可用（manifest 未就绪）');
          return;
        }
        setItems(response.items ?? []);
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'fetch_failed');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open, items.length]);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return items.filter((item) => {
      if (domain && item.domain !== domain) return false;
      if (!keyword) return true;
      const haystack = [item.capability_id, item.intent, ...(item.methods || []), ...(item.data_scope || [])]
        .join(' ')
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [items, domain, query]);

  async function handlePreview(item: CapabilityItem) {
    setBusyId(item.capability_id);
    setPreview(null);
    try {
      if (SCHEMA_V2) {
        // 新路径：explain 拿 schema → resolve 走服务端装配（默认资产/基准/区间）
        const explained = await explainCapability(item.capability_id);
        const schema = explained.schema;
        const resolved = await resolveCapability(item.capability_id, {});
        setPreview({
          id: item.capability_id,
          ok: Boolean(resolved.ok),
          missing: resolved.missing_params ?? [],
          warnings: [],
          reason: resolved.ok
            ? undefined
            : `${CODE_HINT[resolved.code] ?? resolved.code}${resolved.reason ? `：${resolved.reason}` : ''}`,
          kind:
            ((resolved.data?.visual?.kind as VisualKind | undefined) ??
              ((
                (resolved.data?.data as Record<string, unknown> | undefined)?.visual as
                  | { kind?: VisualKind }
                  | undefined
              )?.kind as VisualKind | undefined)),
          schema,
        });
        return;
      }
      const validated = await validateCapability(item.capability_id, {});
      if (!validated.ok) {
        setPreview({
          id: item.capability_id,
          ok: false,
          missing: validated.missing_params ?? [],
          warnings: validated.warnings ?? [],
          reason: validated.reason,
        });
        return;
      }
      const run = await runCapability(item.capability_id, {});
      setPreview({
        id: item.capability_id,
        ok: Boolean(run.ok),
        missing: [],
        warnings: validated.warnings ?? [],
        reason: run.ok ? undefined : run.reason || '运行缺参',
        kind: (run.result?.visual?.kind as VisualKind) || undefined,
      });
    } catch (err: unknown) {
      setPreview({
        id: item.capability_id,
        ok: false,
        missing: [],
        warnings: [],
        reason: err instanceof Error ? err.message : 'preview_failed',
      });
    } finally {
      setBusyId('');
    }
  }

  function handleAdd(item: CapabilityItem) {
    const current = preview?.id === item.capability_id ? preview : null;
    const args =
      SCHEMA_V2 && current?.schema ? defaultArgsForSchema(current.schema) : {};
    onPick({
      capability_id: item.capability_id,
      title: `${item.capability_id} · ${item.intent}`,
      kind: current?.kind,
      args,
    });
    onClose();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 bg-slate-950/70" onClick={onClose} role="presentation">
      <aside
        className="absolute right-0 top-0 flex h-full w-full max-w-[520px] flex-col border-l border-slate-800 bg-slate-900"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="border-b border-slate-800 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-100">
                {mode === 'tab' ? '新建 tab（从能力库选择）' : '添加能力卡片'}
              </h3>
              <p className="mt-0.5 text-[11px] text-slate-500">
                目录来自 capability_manifest · 只列可执行能力 · 预览会先 validate 再取一次数
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-2 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            >
              关闭
            </button>
          </div>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索能力 ID / 意图 / 方法号（如 D-E17、B14）"
            className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none"
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {DOMAINS.map((entry) => (
              <button
                key={entry.key || 'all'}
                type="button"
                onClick={() => setDomain(entry.key)}
                className={`rounded-md border px-2 py-0.5 text-[10px] ${
                  domain === entry.key
                    ? 'border-indigo-500/50 bg-indigo-500/15 text-indigo-200'
                    : 'border-slate-800 bg-slate-950/50 text-slate-400 hover:text-slate-200'
                }`}
              >
                {entry.label}
              </button>
            ))}
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-2">
          {loading && <p className="py-6 text-center text-xs text-slate-500">加载能力目录…</p>}
          {error && <p className="py-6 text-center text-xs text-rose-400">降级：{error}</p>}
          {!loading && !error && filtered.length === 0 && (
            <p className="py-6 text-center text-xs text-slate-500">没有匹配的能力</p>
          )}

          {filtered.map((item) => {
            const isMounted = mounted.includes(item.capability_id);
            const isPreview = preview?.id === item.capability_id;
            return (
              <div key={item.capability_id} className="border-b border-slate-800/70 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs text-slate-200">
                      {item.capability_id} · {item.intent}
                    </p>
                    <p className="mt-0.5 font-mono text-[10px] text-slate-500">
                      min_n {item.min_n ?? '—'} · {(item.methods || []).slice(0, 3).join('/') || '—'} ·{' '}
                      {(item.data_scope || []).join('+') || '—'}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {isMounted && <V3Badge variant="default" label="已挂载" />}
                    <button
                      type="button"
                      onClick={() => handlePreview(item)}
                      disabled={busyId === item.capability_id}
                      className="rounded-md border border-slate-700 px-2 py-0.5 text-[10px] text-slate-300 hover:border-slate-500 disabled:opacity-50"
                    >
                      {busyId === item.capability_id ? '预览中…' : '预览'}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleAdd(item)}
                      disabled={isMounted || !isPreview || !preview?.ok}
                      className="rounded-md border border-indigo-500/40 bg-indigo-500/15 px-2 py-0.5 text-[10px] text-indigo-200 disabled:border-slate-800 disabled:bg-transparent disabled:text-slate-600"
                    >
                      添加
                    </button>
                  </div>
                </div>
                {isPreview && (
                  <div className="mt-1.5 rounded-md border border-slate-800 bg-slate-950/50 px-2 py-1.5 text-[10px]">
                    {preview.ok ? (
                      <span className="text-emerald-400">可执行（预览取数成功）</span>
                    ) : (
                      <span className="text-amber-400">
                        不可执行
                        {preview.missing.length > 0 && ` · 缺参 ${preview.missing.join(', ')}`}
                        {preview.warnings.length > 0 && ` · ${preview.warnings.join('；')}`}
                        {preview.reason && ` · ${preview.reason}`}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <footer className="border-t border-slate-800 px-4 py-2.5 text-[10px] text-slate-500">
          已挂载 {mounted.length} 张卡 · 不看预览不能添加（避免挂上永远为空的卡）
        </footer>
      </aside>
    </div>
  );
}

export default CapabilityPicker;
