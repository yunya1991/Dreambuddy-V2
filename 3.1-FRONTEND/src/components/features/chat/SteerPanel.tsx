'use client';

import React, { useState } from 'react';
import { useSessionStore } from '@/stores/session-store';
import { V3Button, V3Badge } from '@/components';

/**
 * 实时干预面板 (F7.4)
 * 在 C-Drive-Agent 四步循环执行中，允许用户介入:
 * - 跳过指定步骤 (recall/debate/jeval/supplement)
 * - 强制方向 (LONG/SHORT/NEUTRAL)
 * - 覆盖置信度阈值
 */
export function SteerPanel() {
  const { currentTaskId, isStreaming } = useSessionStore();
  const [skipSteps, setSkipSteps] = useState<string[]>([]);
  const [forceDirection, setForceDirection] = useState<string>('');
  const [overrideConf, setOverrideConf] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const toggleStep = (step: string) => {
    setSkipSteps(prev => prev.includes(step) ? prev.filter(s => s !== step) : [...prev, step]);
  };

  const handleSubmit = async () => {
    if (!currentTaskId) {
      setResult('⚠️ 无活动 task_id，等待任务开始');
      return;
    }
    const steer: Record<string, unknown> = {};
    if (skipSteps.length > 0) steer.skip_steps = skipSteps;
    if (forceDirection) steer.force_direction = forceDirection;
    if (overrideConf !== null) steer.override_confidence = overrideConf;

    if (Object.keys(steer).length === 0) {
      setResult('⚠️ 请至少选择一项干预操作');
      return;
    }

    setSubmitting(true);
    setResult(null);
    try {
      // TODO: migrate to domain client — non-standard response (uses data.queued, not data.data)
      const res = await fetch('/api/intent/steer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: currentTaskId, steer }),
      });
      const data = await res.json();
      if (data.success) {
        setResult(`✅ 干预指令已提交 (队列: ${data.queued})`);
        setSkipSteps([]);
        setForceDirection('');
        setOverrideConf(null);
      } else {
        setResult(`❌ ${data.error}`);
      }
    } catch (e) {
      setResult(`❌ ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (!isStreaming && !currentTaskId) return null;

  return (
    <div className="rounded-lg border border-v3-border bg-v3-bg-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-medium text-v3-text-primary">实时干预</span>
        <V3Badge variant={isStreaming ? 'success' : 'default'}>
          {isStreaming ? '执行中' : '空闲'}
        </V3Badge>
        {currentTaskId && (
          <span className="text-xs text-v3-text-tertiary truncate" title={currentTaskId}>
            {currentTaskId.slice(0, 8)}…
          </span>
        )}
      </div>

      {/* 跳过步骤 */}
      <div className="mb-3">
        <div className="text-xs text-v3-text-secondary mb-1.5">跳过步骤</div>
        <div className="flex flex-wrap gap-1.5">
          {['recall', 'debate', 'jeval', 'supplement'].map(step => (
            <button
              key={step}
              onClick={() => toggleStep(step)}
              className={`px-2.5 py-1 rounded text-xs transition-colors ${
                skipSteps.includes(step)
                  ? 'bg-v3-accent-blue text-white'
                  : 'bg-v3-bg-subtle text-v3-text-secondary hover:bg-v3-bg-hover'
              }`}
            >
              {step}
            </button>
          ))}
        </div>
      </div>

      {/* 强制方向 */}
      <div className="mb-3">
        <div className="text-xs text-v3-text-secondary mb-1.5">强制方向</div>
        <div className="flex gap-1.5">
          {[
            { v: 'LONG', label: '多', tone: 'bg-v3-accent-green' },
            { v: 'SHORT', label: '空', tone: 'bg-v3-accent-red' },
            { v: 'NEUTRAL', label: '中性', tone: 'bg-v3-accent-blue' },
          ].map(d => (
            <button
              key={d.v}
              onClick={() => setForceDirection(forceDirection === d.v ? '' : d.v)}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                forceDirection === d.v ? `${d.tone} text-white` : 'bg-v3-bg-subtle text-v3-text-secondary hover:bg-v3-bg-hover'
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {/* 覆盖置信度 */}
      <div className="mb-3">
        <div className="text-xs text-v3-text-secondary mb-1.5">
          覆盖置信度: {overrideConf !== null ? overrideConf.toFixed(2) : '—'}
        </div>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={overrideConf ?? 0.5}
          onChange={e => setOverrideConf(Number(e.target.value))}
          className="w-full accent-v3-accent-blue"
        />
      </div>

      {/* 提交 */}
      <V3Button onClick={handleSubmit} disabled={submitting || !isStreaming} size="sm">
        {submitting ? '提交中...' : '提交干预'}
      </V3Button>

      {result && (
        <div className="mt-2 text-xs text-v3-text-secondary">{result}</div>
      )}
    </div>
  );
}
