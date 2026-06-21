
import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchModels, selectModel, reloadModels, fetchModelArtifacts } from '../lib/api';
import type { ModelArtifact } from '../lib/api';
import { Brain, RefreshCw, Check, Activity } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { cn } from '../lib/utils';

export const ModelsCard: React.FC = () => {
  const queryClient = useQueryClient();
  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ['models'],
    queryFn: fetchModels,
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const artifactsQuery = useQuery({
    queryKey: ['models', 'artifacts'],
    queryFn: fetchModelArtifacts,
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });

  const artifactsByName = React.useMemo(() => {
    const m = new Map<string, ModelArtifact>();
    const arr = (artifactsQuery.data?.artifacts ?? []) as ModelArtifact[];
    for (const a of arr) {
      const name = String(a?.name ?? '');
      if (!name) continue;
      m.set(name, a);
    }
    return m;
  }, [artifactsQuery.data?.artifacts]);

  const [nowMs, setNowMs] = React.useState(0);
  React.useEffect(() => {
    setNowMs(Date.now());
  }, [artifactsQuery.dataUpdatedAt]);
  const fmtAge = (mtimeMs: number | undefined) => {
    if (!mtimeMs || !Number.isFinite(mtimeMs)) return '-';
    const d = Math.max(0, nowMs - Number(mtimeMs));
    if (d < 60_000) return 'just now';
    if (d < 3_600_000) return `${Math.round(d / 60_000)}m`;
    if (d < 86_400_000) return `${Math.round(d / 3_600_000)}h`;
    return `${Math.round(d / 86_400_000)}d`;
  };

  const fmtBytes = (b: number | undefined) => {
    if (b == null || !Number.isFinite(b)) return '-';
    const n = Number(b);
    if (n < 1024) return `${Math.round(n)}B`;
    if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)}KB`;
    if (n < 1024 ** 3) return `${(n / (1024 ** 2)).toFixed(1)}MB`;
    return `${(n / (1024 ** 3)).toFixed(1)}GB`;
  };

  const shortPath = (p: string | undefined) => {
    const s = String(p ?? '');
    if (!s) return '-';
    const parts = s.split('/').filter(Boolean);
    if (parts.length <= 4) return `/${parts.join('/')}`;
    return `…/${parts.slice(-4).join('/')}`;
  };

  const rawModels = data?.models ?? [];
  const visibleModels = (() => {
    const filtered = rawModels.filter((m) => {
      const s = String(m || '');
      const sl = s.toLowerCase();
      if (!s) return false;
      if (sl.includes('scaler')) return false;
      if (sl.includes('calibration')) return false;
      if (sl.endsWith('_state.pth') || sl.endsWith('state.pth')) return false;
      return true;
    });

    const familyOf = (m: string): string | null => {
      const sl = m.toLowerCase();
      if (sl.includes('xgb')) return 'xgb';
      if (sl.includes('lstm')) return 'lstm';
      if (sl.includes('transformer')) return 'transformer';
      if (sl.includes('randomforest') || sl.startsWith('rf') || sl.includes('_rf')) return 'rf';
      if (sl.startsWith('nn') || sl.includes('_nn') || sl.includes('mlp')) return 'nn';
      if (sl.startsWith('lr') || sl.includes('_lr')) return 'lr';
      return null;
    };

    const rank = (m: string) => {
      const sl = m.toLowerCase();
      const extRank = sl.endsWith('.pkl') ? 0 : sl.endsWith('.pth') ? 1 : 2;
      const preferModel = sl.includes('_model') || sl.includes('model');
      const preferShort = sl.includes('_short');
      const preferAtt = sl.includes('att');
      const modelRank = preferModel ? 0 : preferShort ? 1 : preferAtt ? 2 : 3;
      return [extRank, modelRank, sl.length, sl] as const;
    };

    const byFamily = new Map<string, string>();
    const other: string[] = [];
    for (const m of filtered) {
      const fam = familyOf(m);
      if (!fam) {
        other.push(m);
        continue;
      }
      const prev = byFamily.get(fam);
      if (!prev) {
        byFamily.set(fam, m);
        continue;
      }
      const a = rank(m);
      const b = rank(prev);
      const better = a[0] !== b[0] ? a[0] < b[0]
        : a[1] !== b[1] ? a[1] < b[1]
        : a[2] !== b[2] ? a[2] < b[2]
        : a[3] < b[3];
      if (better) byFamily.set(fam, m);
    }

    other.sort((a, b) => a.localeCompare(b));
    const order = ['xgb', 'lstm', 'rf', 'transformer', 'rule', 'nn', 'lr'];
    const out: string[] = [];
    for (const k of order) {
      const v = byFamily.get(k);
      if (v) out.push(v);
    }
    for (const v of byFamily.values()) {
      if (!out.includes(v)) out.push(v);
    }
    out.push(...other);
    return out;
  })();

  const selectMutation = useMutation({
    mutationFn: selectModel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['models'] });
      queryClient.invalidateQueries({ queryKey: ['metrics'] });
    }
  });

  const reloadMutation = useMutation({
    mutationFn: reloadModels,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['models'] });
    }
  });

  const handleActivate = (modelName: string) => {
    selectMutation.mutate(modelName);
  };

  return (
    <Card className="h-full">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-lg font-medium">Model Management</CardTitle>
        <Brain className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="flex justify-between items-center mb-4">
          <span className="text-sm text-gray-500">
            Available Models ({visibleModels.length}/{rawModels.length})
            {isFetching ? ' · Updating…' : ''}
          </span>
          <Button 
            variant="outline" 
            size="sm" 
            onClick={() => reloadMutation.mutate()}
            disabled={reloadMutation.isPending}
          >
            <RefreshCw size={14} className={cn("mr-2", reloadMutation.isPending && "animate-spin")} />
            Reload
          </Button>
        </div>

        <div className="text-xs text-slate-500 mb-3">
          Models dir: <span className="font-mono" title={artifactsQuery.data?.models_dir ?? ''}>{shortPath(artifactsQuery.data?.models_dir)}</span>
        </div>

        {isLoading && (
          <div className="text-sm text-slate-500">Loading models…</div>
        )}

        {!isLoading && error && (
          <div className="text-sm text-red-600">Failed to load models</div>
        )}

        <div className="space-y-2 max-h-[320px] overflow-y-auto pr-2">
          <div 
            className={cn(
              "flex items-center justify-between p-3 rounded-md border cursor-pointer transition-colors hover:bg-slate-50",
              data?.active === '__committee__' ? "border-green-500 bg-green-50 hover:bg-green-50" : "border-slate-200"
            )}
            onClick={() => handleActivate('__committee__')}
          >
            <div className="flex items-center space-x-3">
              <div className={cn("p-2 rounded-full", data?.active === '__committee__' ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-500")}>
                <Activity size={16} />
              </div>
              <div>
                <div className="font-medium text-sm">Committee Ensemble</div>
                <div className="text-xs text-slate-500">Multi-model voting</div>
              </div>
            </div>
            {data?.active === '__committee__' && <Check size={16} className="text-green-600" />}
          </div>

          {visibleModels.map(m => (
            (() => {
              const a = artifactsByName.get(m);
              const loaded = Boolean(a?.loaded);
              const age = fmtAge(a?.mtime_ms);
              const size = fmtBytes(a?.size_bytes);
              const kind = String(a?.kind ?? '');
              const hasMeta = Boolean(a);

              return (
            <div 
              key={m}
              className={cn(
                "flex items-center justify-between p-3 rounded-md border cursor-pointer transition-colors hover:bg-slate-50",
                data?.active === m ? "border-blue-500 bg-blue-50 hover:bg-blue-50" : "border-slate-200"
              )}
              onClick={() => handleActivate(m)}
            >
              <div className="flex items-center space-x-3">
                 <div className={cn("p-2 rounded-full", data?.active === m ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-500")}>
                  <Brain size={16} />
                </div>
                <div>
                  <div className="font-medium text-sm truncate max-w-[150px]" title={m}>{m}</div>
                  <div className="text-xs text-slate-500 flex items-center gap-2">
                    {hasMeta ? (
                      <span className="font-mono" title={a?.path ?? ''}>{kind || 'artifact'} · {size} · {age}</span>
                    ) : (
                      <span className="font-mono">artifact: -</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {hasMeta ? (
                  loaded ? (
                    <Badge className="bg-emerald-600">Loaded</Badge>
                  ) : (
                    <Badge variant="outline">Disk</Badge>
                  )
                ) : (
                  <Badge variant="outline">Unknown</Badge>
                )}
                {data?.active === m && <Check size={16} className="text-blue-600" />}
              </div>
            </div>
              );
            })()
          ))}
        </div>
      </CardContent>
    </Card>
  );
};
