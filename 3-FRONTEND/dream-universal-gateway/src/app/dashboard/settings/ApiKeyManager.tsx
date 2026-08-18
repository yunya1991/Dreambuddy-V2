'use client';

import { useApiConfigStore } from '@/stores';
import { V3Card, V3Badge, V3Button, V3StatusDot, IconPlus, IconRefresh } from '@/components';

const envLabels = { dev: '开发', staging: '测试', prod: '生产' };
const statusLabels = { active: '活跃', inactive: '停用', error: '异常' };
const statusVariant = { active: 'success' as const, inactive: 'default' as const, error: 'danger' as const };

export function ApiKeyManager() {
  const { profiles } = useApiConfigStore();

  return (
    <V3Card title="API Key 管理" actions={<V3Button size="sm" variant="secondary"><IconPlus className="w-3.5 h-3.5" /> 添加</V3Button>}>
      {profiles.length === 0 ? (
        <div className="flex flex-col items-center py-6">
          <svg className="w-8 h-8 text-slate-600 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" /></svg>
          <p className="text-sm text-slate-500">暂无 API Key</p>
        </div>
      ) : (
        <div className="space-y-2">
          {profiles.map(p => (
            <div key={p.id} className="flex items-center justify-between p-3 rounded-lg bg-slate-800/50 border border-slate-700/30">
              <div className="flex items-center gap-3">
                <V3StatusDot status={p.status === 'active' ? 'success' : p.status === 'error' ? 'error' : 'idle'} size="sm" />
                <div>
                  <p className="text-sm text-slate-200">{p.name}</p>
                  <p className="text-[10px] text-slate-500">{p.provider} · {p.category}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <V3Badge variant={statusVariant[p.status]} label={statusLabels[p.status]} />
                <V3Badge variant="default" label={envLabels[p.environment]} />
              </div>
            </div>
          ))}
        </div>
      )}
    </V3Card>
  );
}
