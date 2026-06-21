import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchEngineeringIndex, type EngineeringIndexResponse } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';

type Row = { k: string; v: string };

const _rowsFromRecord = (obj: Record<string, unknown> | null | undefined): Row[] => {
  if (!obj) return [];
  return Object.entries(obj)
    .map(([k, v]) => ({ k, v: String(v ?? '') }))
    .filter((x) => x.v.trim().length > 0)
    .sort((a, b) => a.k.localeCompare(b.k));
};

const _copy = async (txt: string): Promise<boolean> => {
  const v = String(txt ?? '').trim();
  if (!v) return false;
  try {
    await navigator.clipboard.writeText(v);
    return true;
  } catch {
    return false;
  }
};

const SectionCard: React.FC<{ title: string; right?: React.ReactNode; children: React.ReactNode }> = ({ title, right, children }) => {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>{title}</span>
          {right ?? null}
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
};

export const EngineeringIndexPage: React.FC = () => {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['engineering', 'index'],
    queryFn: fetchEngineeringIndex,
    refetchOnWindowFocus: false,
  });

  const backendRoutes = useMemo(() => {
    const xs = ((data as EngineeringIndexResponse | undefined)?.backend?.routes ?? []).map((x) => String(x ?? '').trim()).filter(Boolean);
    return Array.from(new Set(xs)).sort((a, b) => a.localeCompare(b));
  }, [data]);

  const backendFns = useMemo(() => {
    const xs = ((data as EngineeringIndexResponse | undefined)?.backend?.functions ?? []).map((x) => String(x ?? '').trim()).filter(Boolean);
    return Array.from(new Set(xs)).sort((a, b) => a.localeCompare(b));
  }, [data]);

  const stateFiles = useMemo(() => _rowsFromRecord((data as EngineeringIndexResponse | undefined)?.state_files as Record<string, unknown> | undefined), [data]);
  const pages = useMemo(() => _rowsFromRecord((data as EngineeringIndexResponse | undefined)?.frontend?.pages as Record<string, unknown> | undefined), [data]);
  const faq = useMemo(() => _rowsFromRecord((data as EngineeringIndexResponse | undefined)?.faq as Record<string, unknown> | undefined), [data]);

  const docsPath = String((data as EngineeringIndexResponse | undefined)?.docs?.path ?? '').trim();
  const docsSection = String((data as EngineeringIndexResponse | undefined)?.docs?.section ?? '').trim();
  const backendEntry = String((data as EngineeringIndexResponse | undefined)?.backend?.entry ?? '').trim();
  const frontendApp = String((data as EngineeringIndexResponse | undefined)?.frontend?.app ?? '').trim();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-2xl font-bold">Engineering Index</div>
          <div className="text-sm text-slate-600">用于快速定位核心链路、风控入口、配置与状态落点</div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={isFetching ? 'secondary' : 'outline'}>{isFetching ? 'refreshing' : 'ready'}</Badge>
          <Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>Refresh</Button>
        </div>
      </div>

      {isLoading ? (
        <SectionCard title="Loading">
          <div className="text-slate-500">Loading...</div>
        </SectionCard>
      ) : error ? (
        <SectionCard title="Error" right={<Button variant="outline" onClick={() => void refetch()}>Retry</Button>}>
          <div className="text-red-600">{String((error as Error)?.message ?? error)}</div>
        </SectionCard>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <SectionCard title="Docs">
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-600">path</span>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono truncate">{docsPath || '-'}</span>
                  <Button variant="ghost" size="sm" onClick={() => void _copy(docsPath)} disabled={!docsPath}>Copy</Button>
                </div>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-600">section</span>
                <span className="font-mono">{docsSection || '-'}</span>
              </div>
            </div>
          </SectionCard>

          <SectionCard title="Backend">
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-600">entry</span>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono truncate">{backendEntry || '-'}</span>
                  <Button variant="ghost" size="sm" onClick={() => void _copy(backendEntry)} disabled={!backendEntry}>Copy</Button>
                </div>
              </div>

              <div className="text-slate-600">routes</div>
              <div className="flex flex-wrap gap-2">
                {backendRoutes.length ? backendRoutes.map((x) => (
                  <Button key={x} variant="outline" size="sm" onClick={() => void _copy(x)} className="font-mono">{x}</Button>
                )) : <span className="text-slate-400">-</span>}
              </div>

              <div className="text-slate-600">functions</div>
              <div className="flex flex-wrap gap-2">
                {backendFns.length ? backendFns.map((x) => (
                  <Button key={x} variant="outline" size="sm" onClick={() => void _copy(x)} className="font-mono">{x}</Button>
                )) : <span className="text-slate-400">-</span>}
              </div>
            </div>
          </SectionCard>

          <SectionCard title="Frontend">
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-600">app</span>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono truncate">{frontendApp || '-'}</span>
                  <Button variant="ghost" size="sm" onClick={() => void _copy(frontendApp)} disabled={!frontendApp}>Copy</Button>
                </div>
              </div>

              <div className="text-slate-600">pages</div>
              <div className="space-y-2">
                {pages.length ? pages.map((it) => (
                  <div key={it.k} className="flex items-center justify-between gap-3">
                    <Badge variant="outline">{it.k}</Badge>
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-mono truncate">{it.v}</span>
                      <Button variant="ghost" size="sm" onClick={() => void _copy(it.v)}>Copy</Button>
                    </div>
                  </div>
                )) : <div className="text-slate-400">-</div>}
              </div>
            </div>
          </SectionCard>

          <SectionCard title="State / Config Files">
            <div className="space-y-2 text-sm">
              {stateFiles.length ? stateFiles.map((it) => (
                <div key={it.k} className="flex items-center justify-between gap-3">
                  <Badge variant="outline">{it.k}</Badge>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-mono truncate">{it.v}</span>
                    <Button variant="ghost" size="sm" onClick={() => void _copy(it.v)}>Copy</Button>
                  </div>
                </div>
              )) : <div className="text-slate-400">-</div>}
            </div>
          </SectionCard>

          <SectionCard title="FAQ">
            <div className="space-y-2 text-sm">
              {faq.length ? faq.map((it) => (
                <div key={it.k} className="flex items-center justify-between gap-3">
                  <Badge variant="outline">{it.k}</Badge>
                  <span className="font-mono">{it.v}</span>
                </div>
              )) : <div className="text-slate-400">-</div>}
            </div>
          </SectionCard>
        </div>
      )}
    </div>
  );
};

