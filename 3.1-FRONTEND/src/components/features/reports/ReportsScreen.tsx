'use client';

import { useState, useEffect, useCallback } from 'react';
import { V3Card, V3Badge, V3Empty, V3Spinner, IconSearch } from '@/components';
import { useSessionStore } from '@/stores';
import api from '@/lib/api-client';

// === 报告数据结构 (来自 /api/task/result/[id]) ===
interface ReportStep {
  stepId: string;
  stepName: string;
  stage: string;
  decision: string;
  confidence: number;
  answer: string;
  skillResults: Array<{
    skillId: string;
    skillName: string;
    status: string;
    confidence: number;
    data: unknown;
  }>;
}

interface ReportData {
  taskId: string;
  taskType: string;
  intent: string;
  input: string;
  summary: string;
  overallConfidence: number;
  totalTokens: number;
  durationMs: number;
  steps: ReportStep[];
  createdAt: string;
  deepeningOptions: Array<{ key: string; label: string; description: string }>;
}

export function ReportsScreen() {
  const { lastReportId } = useSessionStore();
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTaskId, setSearchTaskId] = useState('');
  const [expandedStep, setExpandedStep] = useState<string | null>(null);

  // 加载报告
  const loadReport = useCallback(async (taskId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<ReportData>(`/api/task/result/${taskId}`);
      setReport(data);
    } catch (err: any) {
      setError(err.message || '加载报告失败');
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // 当 lastReportId 变化时自动加载
  useEffect(() => {
    if (lastReportId) {
      setSearchTaskId(lastReportId);
      loadReport(lastReportId);
    }
  }, [lastReportId, loadReport]);

  const handleSearch = () => {
    const tid = searchTaskId.trim();
    if (tid) loadReport(tid);
  };

  return (
    <div className="space-y-4">
      {/* 搜索栏 */}
      <div className="flex items-center gap-2">
        <div className="flex-1 relative">
          <IconSearch className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-600" />
          <input
            type="text"
            value={searchTaskId}
            onChange={e => setSearchTaskId(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="输入任务 ID 查看报告..."
            className="w-full bg-slate-900/50 border border-slate-700/50 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50"
          />
        </div>
        <button
          onClick={handleSearch}
          className="px-3 py-1.5 rounded-lg bg-indigo-600/20 text-indigo-400 text-xs hover:bg-indigo-600/30 transition-colors"
        >
          加载
        </button>
      </div>

      {/* 加载中 */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <V3Spinner size="md" />
          <span className="ml-3 text-sm text-slate-400">加载报告中...</span>
        </div>
      )}

      {/* 错误 */}
      {error && !loading && (
        <V3Card>
          <div className="text-center py-8">
            <p className="text-sm text-red-400 mb-2">⚠ {error}</p>
            <p className="text-xs text-slate-500">请确认任务 ID 是否正确</p>
          </div>
        </V3Card>
      )}

      {/* 空状态 */}
      {!report && !loading && !error && (
        <V3Card>
          <V3Empty title="暂无报告" description="完成对话任务后可在此查看完整报告，或在上方输入任务 ID 加载历史报告" />
        </V3Card>
      )}

      {/* 报告内容 */}
      {report && !loading && (
        <div className="space-y-4">
          {/* 报告头部 */}
          <V3Card title="任务概览" padding="md">
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <p className="text-[10px] text-slate-500">任务 ID</p>
                <p className="text-xs text-slate-300 font-mono">{report.taskId}</p>
              </div>
              <div>
                <p className="text-[10px] text-slate-500">意图类型</p>
                <p className="text-xs text-slate-300">{report.intent}</p>
              </div>
              <div>
                <p className="text-[10px] text-slate-500">创建时间</p>
                <p className="text-xs text-slate-300">{new Date(report.createdAt).toLocaleString('zh-CN')}</p>
              </div>
              <div>
                <p className="text-[10px] text-slate-500">执行耗时</p>
                <p className="text-xs text-slate-300">{(report.durationMs / 1000).toFixed(1)}s</p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-slate-800/30 rounded-lg p-2 text-center">
                <p className="text-[10px] text-slate-500">综合置信度</p>
                <p className={`text-sm font-bold ${report.overallConfidence >= 70 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {report.overallConfidence.toFixed(0)}%
                </p>
              </div>
              <div className="bg-slate-800/30 rounded-lg p-2 text-center">
                <p className="text-[10px] text-slate-500">Token 用量</p>
                <p className="text-sm font-bold text-blue-400">{report.totalTokens}</p>
              </div>
              <div className="bg-slate-800/30 rounded-lg p-2 text-center">
                <p className="text-[10px] text-slate-500">执行步骤</p>
                <p className="text-sm font-bold text-slate-300">{report.steps.length}</p>
              </div>
            </div>
          </V3Card>

          {/* 原始输入 */}
          <V3Card title="原始输入" padding="sm">
            <p className="text-xs text-slate-400">{report.input}</p>
          </V3Card>

          {/* 核心摘要 */}
          <V3Card title="核心摘要" padding="md">
            <div className="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">
              {report.summary}
            </div>
          </V3Card>

          {/* 执行步骤详情 */}
          <V3Card title={`执行步骤 (${report.steps.length})`} padding="md">
            <div className="space-y-2">
              {report.steps.map((step, i) => (
                <div key={step.stepId} className="border border-slate-700/30 rounded-lg overflow-hidden">
                  <button
                    onClick={() => setExpandedStep(expandedStep === step.stepId ? null : step.stepId)}
                    className="w-full flex items-center gap-3 px-3 py-2 hover:bg-slate-800/30 transition-colors text-left"
                  >
                    <span className="text-[10px] text-slate-600 w-4">{i + 1}</span>
                    <span className="text-xs font-medium text-slate-200 flex-1 truncate">{step.stepName}</span>
                    <V3Badge variant="default" className="text-[9px]">{step.stage}</V3Badge>
                    {step.confidence > 0 && (
                      <span className={`text-[10px] ${step.confidence >= 70 ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {step.confidence.toFixed(0)}%
                      </span>
                    )}
                    <span className="text-[10px] text-slate-500">
                      {step.skillResults.length} skill
                    </span>
                    <span className="text-slate-500 text-xs">
                      {expandedStep === step.stepId ? '−' : '+'}
                    </span>
                  </button>
                  {expandedStep === step.stepId && (
                    <div className="px-3 py-2 border-t border-slate-700/30 bg-slate-900/30 space-y-2">
                      {step.answer && (
                        <div>
                          <p className="text-[10px] text-slate-500 mb-1">步骤输出</p>
                          <p className="text-xs text-slate-300 whitespace-pre-wrap">{step.answer}</p>
                        </div>
                      )}
                      {step.skillResults.length > 0 && (
                        <div>
                          <p className="text-[10px] text-slate-500 mb-1">Skill 调用</p>
                          <div className="space-y-1">
                            {step.skillResults.map((sk, j) => (
                              <div key={j} className="flex items-center gap-2 text-[10px] px-2 py-1 rounded bg-slate-800/30">
                                <V3Badge variant={sk.status === 'completed' ? 'success' : 'danger'} className="text-[9px]">
                                  {sk.status}
                                </V3Badge>
                                <span className="text-slate-300">{sk.skillName}</span>
                                {sk.confidence > 0 && (
                                  <span className="text-slate-500">({sk.confidence.toFixed(0)}%)</span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </V3Card>

          {/* 深入选项 */}
          {report.deepeningOptions.length > 0 && (
            <V3Card title="深入分析" padding="sm">
              <div className="grid grid-cols-1 gap-2">
                {report.deepeningOptions.map((opt) => (
                  <div key={opt.key} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-800/30 hover:bg-slate-800/50 transition-colors cursor-pointer">
                    <span className="text-xs text-slate-200">{opt.label}</span>
                    <span className="text-[10px] text-slate-500 flex-1">{opt.description}</span>
                  </div>
                ))}
              </div>
            </V3Card>
          )}
        </div>
      )}
    </div>
  );
}
