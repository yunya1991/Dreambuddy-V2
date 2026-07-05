"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

interface StepResult {
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
    data?: any;
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
  steps: StepResult[];
  createdAt: string;
  deepeningOptions: Array<{
    key: string;
    label: string;
    description: string;
  }>;
}

export default function ReportPage() {
  const params = useParams();
  const reportId = params.id as string;
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchReport = async () => {
      try {
        const res = await fetch(`/api/task/result/${reportId}`);
        if (!res.ok) {
          throw new Error(`加载失败: ${res.status}`);
        }
        const data = await res.json();
        if (data.success) {
          setReport(data.data);
        } else {
          throw new Error(data.error || "加载失败");
        }
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    if (reportId) {
      fetchReport();
    }
  }, [reportId]);

  const formatDuration = (ms: number) => {
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return `${seconds}秒`;
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}分${secs}秒`;
  };

  const getDecisionBadge = (decision: string) => {
    const styles: Record<string, string> = {
      proceed: "bg-green-100 text-green-800 border-green-200",
      warn: "bg-yellow-100 text-yellow-800 border-yellow-200",
      iterate: "bg-blue-100 text-blue-800 border-blue-200",
      insert: "bg-purple-100 text-purple-800 border-purple-200",
      skip: "bg-gray-100 text-gray-500 border-gray-200",
    };
    return styles[decision] || styles.skip;
  };

  const decisionLabel: Record<string, string> = {
    proceed: "执行",
    warn: "通过(警告)",
    iterate: "迭代",
    insert: "插入",
    skip: "跳过",
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-white flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-400">正在加载报告...</p>
        </div>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-white flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <div className="w-16 h-16 bg-red-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold mb-2">报告加载失败</h1>
          <p className="text-slate-400 mb-6">{error || "报告不存在"}</p>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            返回对话
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-white">
      {/* Header */}
      <header className="sticky top-0 z-50 backdrop-blur-xl bg-slate-950/70 border-b border-white/5">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            返回对话
          </Link>
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-500">
              {new Date(report.createdAt).toLocaleString("zh-CN")}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* Title Section */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-3">
            <span className="px-3 py-1 bg-blue-500/20 text-blue-400 text-sm rounded-full border border-blue-500/30">
              {report.intent}
            </span>
            <span className="px-3 py-1 bg-emerald-500/20 text-emerald-400 text-sm rounded-full border border-emerald-500/30">
              置信度 {report.overallConfidence.toFixed(0)}%
            </span>
          </div>
          <h1 className="text-3xl font-bold mb-3 bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">
            {report.input}
          </h1>
          <div className="flex flex-wrap gap-4 text-sm text-slate-400">
            <span className="flex items-center gap-1.5">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              耗时 {formatDuration(report.durationMs)}
            </span>
            <span className="flex items-center gap-1.5">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {report.steps.length} 个分析节点
            </span>
            <span className="flex items-center gap-1.5">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Token {report.totalTokens.toLocaleString()}
            </span>
          </div>
        </div>

        {/* Summary Card */}
        <div className="bg-white/5 backdrop-blur-sm rounded-2xl border border-white/10 p-8 mb-8">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <span className="text-xl">📋</span>
            分析结论
          </h2>
          <div className="prose prose-invert prose-slate max-w-none">
            <div className="text-slate-200 leading-relaxed whitespace-pre-wrap">
              {report.summary}
            </div>
          </div>
        </div>

        {/* Deepening Options */}
        {report.deepeningOptions && report.deepeningOptions.length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <span className="text-xl">🔍</span>
              深入分析
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {report.deepeningOptions.map((opt, idx) => (
                <Link
                  key={opt.key}
                  href={`/dashboard?deepen=${encodeURIComponent(opt.label)}`}
                  className="bg-white/5 hover:bg-white/10 border border-white/10 hover:border-blue-500/50 rounded-xl p-5 transition-all group"
                >
                  <div className="text-2xl mb-2">{idx + 1}</div>
                  <h3 className="font-medium text-white group-hover:text-blue-400 transition-colors mb-1">
                    {opt.label}
                  </h3>
                  <p className="text-sm text-slate-400">{opt.description}</p>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* Steps Detail */}
        <div>
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <span className="text-xl">🧠</span>
            编排详情
          </h2>
          <div className="space-y-4">
            {report.steps.map((step, index) => (
              <div
                key={step.stepId}
                className="bg-white/5 backdrop-blur-sm rounded-xl border border-white/10 overflow-hidden"
              >
                <div className="p-5 flex items-start justify-between">
                  <div className="flex items-start gap-4">
                    <div className="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center text-blue-400 text-sm font-medium flex-shrink-0">
                      {index + 1}
                    </div>
                    <div>
                      <h3 className="font-medium text-white mb-1">{step.stepName}</h3>
                      <p className="text-sm text-slate-400">{step.stage} 阶段</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-slate-400">
                      置信度 {step.confidence.toFixed(0)}%
                    </span>
                    <span className={`px-2.5 py-1 text-xs font-medium rounded-full border ${getDecisionBadge(step.decision)}`}>
                      {decisionLabel[step.decision] || step.decision}
                    </span>
                  </div>
                </div>

                {/* Skill Results */}
                {step.skillResults && step.skillResults.length > 0 && (
                  <div className="border-t border-white/5 px-5 py-4 bg-black/20">
                    <div className="text-xs text-slate-500 mb-3">调用的技能</div>
                    <div className="flex flex-wrap gap-2">
                      {step.skillResults.map((skill) => (
                        <div
                          key={skill.skillId}
                          className="flex items-center gap-2 px-3 py-1.5 bg-white/5 rounded-lg text-sm"
                        >
                          <span className="text-slate-300">{skill.skillName}</span>
                          <span className="text-xs text-slate-500">
                            {skill.confidence.toFixed(0)}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Step Answer */}
                {step.answer && step.decision !== "skip" && (
                  <div className="border-t border-white/5 px-5 py-4">
                    <div className="text-sm text-slate-300 whitespace-pre-wrap">
                      {step.answer.length > 500 ? step.answer.slice(0, 500) + "..." : step.answer}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <footer className="mt-12 pt-8 border-t border-white/5 text-center text-sm text-slate-500">
          <p>由 Dream Gateway 智能交易助手生成</p>
          <p className="mt-1">报告ID: {report.taskId}</p>
        </footer>
      </main>
    </div>
  );
}
