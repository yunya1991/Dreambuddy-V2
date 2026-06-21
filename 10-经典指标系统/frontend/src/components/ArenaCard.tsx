import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchArenaHistory, fetchArenaState, resetArena, updateConfig } from '../lib/api';
import { Trophy } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';

export const ArenaCard: React.FC<{ mode?: 'entry' | 'exit' }> = ({ mode = 'entry' }) => {
  const queryClient = useQueryClient();
  const { data: arenaState } = useQuery({
    queryKey: ['arena', 'state', mode],
    queryFn: () => fetchArenaState(mode),
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: arenaHistory } = useQuery({
    queryKey: ['arena', 'history', mode],
    queryFn: () => fetchArenaHistory(20, mode),
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const resetMutation = useMutation({
    mutationFn: () => resetArena(mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['arena'] });
    },
  });

  const setArenaEnabledMutation = useMutation({
    mutationFn: (enabled: boolean) => updateConfig({ arena_enabled: enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['arena'] });
    },
  });

  const enabled = Boolean(arenaState?.enabled);
  const pool = Number(arenaState?.pool_u ?? 0);
  const models = arenaState?.models ?? [];
  const history = arenaHistory?.history ?? [];
  const apiOk = Boolean(arenaState?.ok);

  return (
    <Card className="h-full">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-lg font-medium">Arena ({mode === 'exit' ? 'Exit' : 'Entry'})</CardTitle>
        <Trophy className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        {!apiOk && (
          <div className="border border-rose-200 bg-rose-50 text-rose-900 rounded px-3 py-2 text-sm mb-4">
            Arena API unavailable
          </div>
        )}
        <div className="flex items-center justify-between mb-4">
          <div className="text-sm text-slate-600">
            {enabled ? (
              <span>
                Pool: <span className="font-semibold text-slate-900">{pool.toFixed(2)}u</span>
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <span>Arena disabled</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setArenaEnabledMutation.mutate(true)}
                  disabled={setArenaEnabledMutation.isPending}
                >
                  Enable
                </Button>
              </span>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => resetMutation.mutate()}
            disabled={!enabled || resetMutation.isPending}
          >
            Reset
          </Button>
        </div>

        {enabled && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2">
              <div className="overflow-y-auto max-h-[220px] border border-slate-100 rounded-md">
                <table className="w-full text-sm text-left">
                  <thead className="text-xs text-gray-500 uppercase bg-gray-50/50 sticky top-0">
                    <tr>
                      <th className="px-3 py-2">Model</th>
                      <th className="px-3 py-2">Weight</th>
                      <th className="px-3 py-2">Capital</th>
                      <th className="px-3 py-2">Takes</th>
                      <th className="px-3 py-2">W/L</th>
                      <th className="px-3 py-2">Revives</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {models.map((m) => (
                      <tr key={m.id ?? m.name} className="hover:bg-slate-50/50">
                        <td
                          className="px-3 py-2 font-medium text-gray-900 truncate max-w-[220px]"
                          title={m.id ? `${m.name} (${m.id})` : m.name}
                        >
                          {m.name}
                        </td>
                        <td className="px-3 py-2 text-gray-700">{Number(m.weight ?? 0).toFixed(4)}</td>
                        <td className="px-3 py-2 text-gray-700">{Number(m.capital_u ?? 0).toFixed(2)}u</td>
                        <td className="px-3 py-2 text-gray-700">{m.takes}</td>
                        <td className="px-3 py-2 text-gray-700">
                          {m.wins}/{m.losses}
                        </td>
                        <td className="px-3 py-2 text-gray-700">{m.revives}</td>
                      </tr>
                    ))}
                    {models.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-3 py-6 text-center text-gray-500">
                          No arena models
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <div className="overflow-y-auto max-h-[220px] border border-slate-100 rounded-md">
                <table className="w-full text-sm text-left">
                  <thead className="text-xs text-gray-500 uppercase bg-gray-50/50 sticky top-0">
                    <tr>
                      <th className="px-3 py-2">Time</th>
                      <th className="px-3 py-2">Pair</th>
                      <th className="px-3 py-2">Ret</th>
                      <th className="px-3 py-2">Winner</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {history.map((h) => (
                      <tr key={h.id} className="hover:bg-slate-50/50">
                        <td className="px-3 py-2 text-gray-500">{new Date(h.ts).toLocaleTimeString()}</td>
                        <td className="px-3 py-2 font-medium text-gray-900">{h.pair}</td>
                        <td className="px-3 py-2 text-gray-700">{Number(h.ret ?? 0).toFixed(4)}</td>
                        <td className="px-3 py-2 text-gray-700 truncate max-w-[120px]" title={String(h.winner ?? '')}>
                          {h.winner ?? ''}
                        </td>
                      </tr>
                    ))}
                    {history.length === 0 && (
                      <tr>
                        <td colSpan={4} className="px-3 py-6 text-center text-gray-500">
                          No settlements yet
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
