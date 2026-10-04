'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { V3Card, V3Badge, V3StatusDot } from '@/components';
import type { CompletenessStep, TradingParamsView, StrategyView } from '@/types';

// 内部使用的轻量接口
interface ApiKeyEntryLite {
  id: string;
  category: string;
  isVerified?: boolean;
}
interface ChannelEntryLite {
  id: string;
  isOnline?: boolean;
}

export function CompletenessWizard() {
  const [steps, setSteps] = useState<CompletenessStep[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    compute();
  }, []);

  const compute = async () => {
    setLoading(true);
    try {
      // 并行拉取所需数据
      const [apiKeys, paramsView, strategiesRes, channels] = await Promise.all([
        api.get<ApiKeyEntryLite[]>('/api/config/api-keys').catch(() => [] as ApiKeyEntryLite[]),
        api.get<TradingParamsView>('/api/config/trading-params').catch(() => null),
        api.get<{ strategies: StrategyView[] } | StrategyView[]>('/api/config/strategies').catch(() => null),
        api.get<ChannelEntryLite[]>('/api/config/channels').catch(() => [] as ChannelEntryLite[]),
      ]);

      const exchangeKey = apiKeys.find((k) => k.category === 'EXCHANGE');
      const llmKey = apiKeys.find((k) => k.category === 'LLM');
      const params = paramsView?.params;
      const live = paramsView?.liveStatus;
      const strategyList = Array.isArray(strategiesRes)
        ? strategiesRes
        : (strategiesRes?.strategies || []);
      const hasAppliedStrategy = strategyList.some((s) => s.status === 'APPLIED');
      const hasOnlineChannel = channels.some((c) => c.isOnline);

      const computed: CompletenessStep[] = [
        {
          key: 'exchange_api',
          label: '交易所 API',
          required: true,
          completed: !!exchangeKey && exchangeKey.isVerified === true,
        },
        {
          key: 'llm_api',
          label: '大模型 API',
          required: true,
          completed: !!llmKey,
        },
        {
          key: 'trading_params',
          label: '交易参数配置',
          required: true,
          completed: !!params && params.leverageMax > 0 && params.capitalPercentage > 0,
        },
        {
          key: 'trading_enabled',
          label: '交易已启用',
          required: false,
          completed: !!params?.isTradingEnabled && live?.status === 'ACTIVE',
        },
        {
          key: 'strategy_applied',
          label: '已应用策略',
          required: false,
          completed: hasAppliedStrategy,
        },
        {
          key: 'channel_configured',
          label: '通信渠道在线',
          required: false,
          completed: hasOnlineChannel,
        },
      ];

      setSteps(computed);
    } finally {
      setLoading(false);
    }
  };

  const completedRequired = steps.filter((s) => s.required && s.completed).length;
  const totalRequired = steps.filter((s) => s.required).length;
  const completedAll = steps.filter((s) => s.completed).length;
  const overall = steps.length > 0
    ? Math.round((steps.filter((s) => s.completed).length / steps.length) * 100)
    : 0;

  const allRequiredDone = totalRequired > 0 && completedRequired === totalRequired;

  return (
    <V3Card
      title="配置完成度"
      subtitle={loading ? '计算中...' : `${completedAll}/${steps.length} 已完成 · 必填 ${completedRequired}/${totalRequired}`}
      actions={
        !loading && (
          <V3Badge variant={overall === 100 ? 'success' : allRequiredDone ? 'success' : 'default'}>
            {overall}%
          </V3Badge>
        )
      }
      padding="sm"
    >
      {/* 进度条 */}
      <div className="mb-3">
        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${
              overall === 100
                ? 'bg-emerald-500'
                : allRequiredDone
                ? 'bg-blue-500'
                : 'bg-amber-500'
            }`}
            style={{ width: `${overall}%` }}
          />
        </div>
        {allRequiredDone && overall < 100 && (
          <p className="text-[10px] text-emerald-400 mt-1.5">
            ✓ 必填项已全部完成，可选项目可进一步完善
          </p>
        )}
        {overall === 100 && (
          <p className="text-[10px] text-emerald-400 mt-1.5">
            ✓ 配置已全部完成
          </p>
        )}
      </div>

      {/* 步骤列表 */}
      <div className="space-y-1.5">
        {steps.map((step) => (
          <div
            key={step.key}
            className="flex items-center justify-between px-3 py-1.5 rounded-md bg-gray-800/20"
          >
            <div className="flex items-center gap-2">
              <V3StatusDot status={step.completed ? 'success' : step.required ? 'warning' : 'idle'} size="sm" />
              <span className="text-xs text-gray-300">{step.label}</span>
            </div>
            <div className="flex items-center gap-1.5">
              {step.required && (
                <span className="text-[10px] text-gray-600">必填</span>
              )}
              <span className={`text-[10px] ${step.completed ? 'text-emerald-400' : step.required ? 'text-amber-400' : 'text-gray-500'}`}>
                {step.completed ? '已完成' : step.required ? '待完成' : '可选'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </V3Card>
  );
}

export default CompletenessWizard;
