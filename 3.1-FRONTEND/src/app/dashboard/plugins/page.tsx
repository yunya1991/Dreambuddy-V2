'use client';

// SPEC-52 F5 — DSH 插件市场（白名单驱动；只在 sandbox profile 启停，不触碰交易热路径）

import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  dshPlugins,
  plugins,
  type DshProfileInfo,
  type PluginGroup,
  type PluginItem,
} from '@/lib/plugins-client';
import { ProductLockedNotice, useProductEntitlement } from '@/components/features/product/ProductGate';
import { V3Badge, V3Button, V3Card } from '@/components';
import { queryKey, queryStaleTime } from '@/lib/query-keys';

type TabId = PluginGroup | 'dsh';

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'own', label: '自有' },
  { id: 'official', label: '官方' },
  { id: 'community', label: '社区' },
  { id: 'dsh', label: 'DSH插件' },
];

function statusBadge(item: PluginItem) {
  if (item.status === 'approved') return <V3Badge variant="success" dot>approved</V3Badge>;
  if (item.status === 'forbidden') return <V3Badge variant="danger" dot>forbidden</V3Badge>;
  return <V3Badge variant="warning" dot>candidate</V3Badge>;
}

export default function PluginsPage() {
  const [tab, setTab] = useState<TabId>('own');
  const [actionError, setActionError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { entitled } = useProductEntitlement();

  const listQuery = useQuery({
    queryKey: queryKey('plugins', 'list'),
    queryFn: () => plugins.list(),
    staleTime: queryStaleTime('settings'),
    retry: false,
  });

  const toggle = useMutation({
    mutationFn: (item: PluginItem) => plugins.setEnabled(item.id, !item.enabled),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: queryKey('plugins', 'list') });
      queryClient.invalidateQueries({ queryKey: queryKey('plugins', 'audit') });
    },
    onError: (e: Error) => setActionError(e.message),
  });

  // DSH 真实插件安装（dsh plugin --profile sandbox add/remove）
  const dshQuery = useQuery({
    queryKey: queryKey('plugins', 'dsh-profile'),
    queryFn: () => dshPlugins.profile('sandbox'),
    staleTime: queryStaleTime('settings'),
    retry: false,
    enabled: tab === 'dsh',
  });

  const dshInstall = useMutation({
    mutationFn: (id: string) => dshPlugins.install(id, 'sandbox'),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: queryKey('plugins', 'dsh-profile') });
      queryClient.invalidateQueries({ queryKey: queryKey('plugins', 'audit') });
    },
    onError: (e: Error) => setActionError(e.message),
  });

  const dshUninstall = useMutation({
    mutationFn: (id: string) => dshPlugins.uninstall(id, 'sandbox'),
    onSuccess: () => {
      setActionError(null);
      queryClient.invalidateQueries({ queryKey: queryKey('plugins', 'dsh-profile') });
      queryClient.invalidateQueries({ queryKey: queryKey('plugins', 'audit') });
    },
    onError: (e: Error) => setActionError(e.message),
  });

  const items = useMemo(
    () =>
      tab === 'dsh'
        ? []
        : (listQuery.data?.items ?? []).filter((item) => item.group === tab),
    [listQuery.data, tab],
  );

  const installable = useMemo(() => {
    const installedNames = new Set((dshQuery.data?.installed ?? []).map((item) => item.name));
    return (listQuery.data?.items ?? []).filter(
      (item) =>
        item.source !== 'local' &&
        item.status !== 'forbidden' &&
        item.enableable &&
        item.permittedProfiles.includes('sandbox') &&
        !installedNames.has(item.id),
    );
  }, [listQuery.data, dshQuery.data]);

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-100">插件</h1>
          <p className="mt-1 text-xs text-gray-500">
            DSH 插件白名单驱动 · deny-by-default · 仅在 sandbox profile 启停，不进入交易热路径
          </p>
        </div>
        <V3Badge variant="info">F5</V3Badge>
      </div>

      {!entitled && <ProductLockedNotice />}

      <div className="flex items-center gap-2">
        {TABS.map((item) => {
          const count =
            item.id === 'dsh'
              ? dshQuery.data?.installed.length ?? 0
              : listQuery.data?.counts?.[item.id] ?? 0;
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`rounded-md border px-3 py-1.5 text-xs transition-colors ${
                active
                  ? 'border-blue-500/40 bg-blue-500/15 text-blue-300'
                  : 'border-gray-700/40 bg-gray-800/30 text-gray-400 hover:text-gray-200'
              }`}
            >
              {item.label} <span className="ml-1 opacity-70">{count}</span>
            </button>
          );
        })}
      </div>

      {listQuery.isError && (
        <div className="rounded-md border border-red-700/40 bg-red-900/15 px-3 py-2 text-xs text-red-300">
          {(listQuery.error as Error).message}
        </div>
      )}
      {actionError && (
        <div className="rounded-md border border-red-700/40 bg-red-900/15 px-3 py-2 text-xs text-red-300">
          {actionError}
        </div>
      )}

      {tab === 'dsh' ? (
        <DshPluginsPanel
          profile={dshQuery.data}
          loading={dshQuery.isLoading}
          error={dshQuery.isError ? (dshQuery.error as Error).message : null}
          installable={installable}
          entitled={entitled}
          busy={dshInstall.isPending || dshUninstall.isPending}
          onInstall={(id) => dshInstall.mutate(id)}
          onUninstall={(id) => dshUninstall.mutate(id)}
        />
      ) : (
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <V3Card
            key={item.id}
            title={item.id}
            subtitle={`${item.source} · ${item.version || '*'}`}
            actions={statusBadge(item)}
            padding="sm"
          >
            <div className="space-y-2 text-xs text-gray-400">
              <div className="flex flex-wrap items-center gap-1.5">
                <V3Badge variant={item.riskLevel === 'forbidden' ? 'danger' : 'default'}>
                  risk:{item.riskLevel}
                </V3Badge>
                <V3Badge variant={item.sandboxVerified ? 'success' : 'warning'}>
                  sandbox:{String(item.sandboxVerified)}
                </V3Badge>
                <V3Badge variant={item.failOpenVerified ? 'success' : 'warning'}>
                  fail-open:{String(item.failOpenVerified)}
                </V3Badge>
                {item.enabled && <V3Badge variant="info">已启用 · {item.enabledProfile}</V3Badge>}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {item.permissions.map((perm) => (
                  <span key={perm} className="rounded bg-gray-800/70 px-1.5 py-0.5 font-mono text-[10px] text-gray-400">
                    {perm}
                  </span>
                ))}
              </div>
              {item.notes && <p className="line-clamp-2 leading-relaxed text-gray-500">{item.notes}</p>}
              {item.rejectReason && <p className="text-red-400/80">不可启用：{item.rejectReason}</p>}
              <div className="flex justify-end pt-1">
                <V3Button
                  size="sm"
                  variant={item.enabled ? 'danger' : 'secondary'}
                  disabled={!item.enableable || !entitled || toggle.isPending}
                  onClick={() => toggle.mutate(item)}
                >
                  {item.enabled ? '停用' : '沙箱启用'}
                </V3Button>
              </div>
            </div>
          </V3Card>
        ))}
        {!listQuery.isLoading && items.length === 0 && (
          <div className="rounded-md border border-gray-700/40 bg-gray-800/20 px-3 py-6 text-center text-xs text-gray-500">
            该分组暂无插件
          </div>
        )}
      </div>
      )}
    </div>
  );
}

// ── DSH 真实插件（profile 安装态）────────────────────────────

function DshPluginsPanel({
  profile,
  loading,
  error,
  installable,
  entitled,
  busy,
  onInstall,
  onUninstall,
}: {
  profile: DshProfileInfo | undefined;
  loading: boolean;
  error: string | null;
  installable: PluginItem[];
  entitled: boolean;
  busy: boolean;
  onInstall: (id: string) => void;
  onUninstall: (id: string) => void;
}) {
  if (error) {
    return (
      <div className="rounded-md border border-red-700/40 bg-red-900/15 px-3 py-2 text-xs text-red-300">
        {error}
      </div>
    );
  }
  if (loading || !profile) {
    return <p className="py-6 text-center text-xs text-gray-500">读取 DSH profile…</p>;
  }

  return (
    <div className="space-y-3">
      <V3Card
        title={`${profile.profile} profile`}
        subtitle={profile.dir}
        actions={<V3Badge variant={profile.exists ? 'success' : 'danger'}>{profile.exists ? 'ready' : 'missing'}</V3Badge>}
        padding="sm"
      >
        <div className="flex flex-wrap gap-1.5 text-[10px] text-gray-500">
          <span className="rounded bg-gray-800/70 px-1.5 py-0.5 font-mono">
            DSH_HOME={profile.home}
          </span>
          <span className="rounded bg-gray-800/70 px-1.5 py-0.5 font-mono">
            bundles={profile.bundles.length}
          </span>
          <span className="rounded bg-gray-800/70 px-1.5 py-0.5 font-mono">
            installable={profile.installable_profiles.join(',')}
          </span>
        </div>
      </V3Card>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <V3Card title="已安装" subtitle="package.json dependencies" padding="sm">
          <ul className="space-y-2 text-xs">
            {profile.installed.map((item) => (
              <li key={item.name} className="flex items-center justify-between gap-2 border-b border-gray-800/50 pb-2">
                <div className="min-w-0">
                  <div className="truncate text-gray-300">{item.name}</div>
                  <div className="font-mono text-[10px] text-gray-500">
                    {item.spec}
                    {item.whitelist ? ` · ${item.whitelist.status}/${item.whitelist.group}` : ' · 未登记'}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {item.is_core && <V3Badge variant="info">core</V3Badge>}
                  {item.in_bundles && <V3Badge variant="success">bundle</V3Badge>}
                  <V3Button
                    size="sm"
                    variant="danger"
                    disabled={item.is_core || busy || !entitled}
                    onClick={() => onUninstall(item.name)}
                  >
                    卸载
                  </V3Button>
                </div>
              </li>
            ))}
          </ul>
        </V3Card>

        <V3Card title="可安装（白名单 ∩ sandbox）" subtitle="dsh plugin --profile sandbox add" padding="sm">
          {installable.length === 0 ? (
            <p className="py-3 text-xs text-gray-500">白名单内已无可安装的 npm 插件</p>
          ) : (
            <ul className="space-y-2 text-xs">
              {installable.map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-2 border-b border-gray-800/50 pb-2">
                  <div className="min-w-0">
                    <div className="truncate text-gray-300">{item.id}</div>
                    <div className="font-mono text-[10px] text-gray-500">
                      {item.version || '*'} · {item.source} · {item.status}
                    </div>
                  </div>
                  <V3Button size="sm" variant="secondary" disabled={busy || !entitled} onClick={() => onInstall(item.id)}>
                    安装
                  </V3Button>
                </li>
              ))}
            </ul>
          )}
        </V3Card>
      </div>
    </div>
  );
}
