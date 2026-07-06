'use client';

import React, { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { V3Card } from '@/components';
import { V3Button } from '@/components';
import { V3Badge } from '@/components';
import { V3StatusDot } from '@/components';
import { IconPlus, IconRefresh, IconSearch } from '@/components';

interface ApiKeyEntry {
  category: string;
  provider: string;
  isConfigured: boolean;
  isVerified?: boolean;
  environment?: string;
  lastVerifiedAt?: string;
}

export function ApiKeyManager() {
  const [keys, setKeys] = useState<ApiKeyEntry[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchKeys();
  }, []);

  const fetchKeys = async () => {
    setLoading(true);
    try {
      const data = await api.get<{ keys: ApiKeyEntry[] }>('/api/config/api-keys');
      setKeys(data?.keys || []);
    } catch {
      // 静默处理
    } finally {
      setLoading(false);
    }
  };

  return (
    <V3Card
      title="API 密钥"
      subtitle="交易所 / LLM / 数据源"
      actions={
        <V3Button variant="ghost" size="sm" onClick={fetchKeys} loading={loading} icon={<IconRefresh className="w-3.5 h-3.5" />}>
          刷新
        </V3Button>
      }
      padding="sm"
    >
      {keys.length === 0 ? (
        <div className="text-center py-8 text-gray-500 text-xs">暂无配置的 API 密钥</div>
      ) : (
        <div className="space-y-2">
          {keys.map((key, i) => (
            <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800/20 border border-gray-700/20">
              <div className="flex items-center gap-2.5">
                <V3StatusDot status={key.isConfigured ? 'success' : 'idle'} />
                <div>
                  <span className="text-xs font-medium text-gray-200">{key.provider}</span>
                  <span className="text-[10px] text-gray-500 ml-2">{key.category}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {key.environment && (
                  <V3Badge variant={key.environment === 'live' ? 'danger' : 'default'}>
                    {key.environment}
                  </V3Badge>
                )}
                {key.isVerified && <V3Badge variant="success">已验证</V3Badge>}
              </div>
            </div>
          ))}
        </div>
      )}
    </V3Card>
  );
}

export default ApiKeyManager;
