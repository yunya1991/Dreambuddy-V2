"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { boardApi } from "@/lib/v3/api";

interface ProposalTask {
  id: string;
  name: string;
  status: string;
  totalTrades: number | null;
}

interface ProposalDetail {
  id: string;
  title: string;
  status: string;
  type: string;
  direction: string;
  symbol: string;
  confidence: number | null;
  edgeScore: number | null;
  description: string | null;
  rawInput: string | null;
  source: string | null;
  regime: string | null;
  stopLoss: number | null;
  takeProfit: number | null;
  leverage: number;
  positionSize: number;
  createdAt: string;
  tasks: ProposalTask[];
}

const STATUS_COLOR: Record<string, string> = {
  DRAFT: "#9ca3af",
  APPROVED: "#4ade80",
  EXECUTING: "#60a5fa",
  PAUSED: "#f59e0b",
  EXPIRED: "#6b7280",
  REJECTED: "#f87171",
};

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "草稿",
  APPROVED: "已批准",
  EXECUTING: "执行中",
  PAUSED: "已暂停",
  EXPIRED: "已过期",
  REJECTED: "已拒绝",
};

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  if (!value && value !== 0) return null;
  return (
    <div>
      <p className="text-xs text-slate-500 mb-0.5">{label}</p>
      <p className="text-sm text-slate-200">{value}</p>
    </div>
  );
}

export default function ProposalDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [proposal, setProposal] = useState<ProposalDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    boardApi.getProposal(id)
      .then(data => { if (data) setProposal(data as unknown as ProposalDetail); })
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [id]);

  const statusColor = proposal ? STATUS_COLOR[proposal.status] || "#9ca3af" : "#9ca3af";
  const statusLabel = proposal ? STATUS_LABEL[proposal.status] || proposal.status : "";

  return (
    <div className="min-h-screen bg-[var(--color-bg-primary)] text-slate-200">
      <div className="max-w-3xl mx-auto px-4 py-8">
        <button
          onClick={() => router.back()}
          className="text-xs text-slate-400 hover:text-slate-200 mb-6 flex items-center gap-1"
        >
          ← 返回提案列表
        </button>

        {error && (
          <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading && (
          <div className="space-y-4">
            <div className="h-10 w-64 rounded bg-slate-800 animate-pulse" />
            <div className="h-48 rounded-xl bg-slate-800 animate-pulse" />
          </div>
        )}

        {proposal && (
          <div className="space-y-6">
            {/* 标题区 */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span
                  className="text-xs font-bold px-2 py-0.5 rounded"
                  style={{ backgroundColor: statusColor + "22", color: statusColor }}
                >
                  {statusLabel}
                </span>
                <span className="text-xs text-slate-500">{proposal.type}</span>
              </div>
              <h1 className="text-2xl font-bold text-slate-100">{proposal.title}</h1>
              <p className="text-slate-400 text-sm mt-1">
                {proposal.symbol} · {proposal.direction} · {proposal.type}
              </p>
            </div>

            {/* 核心字段 */}
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 grid grid-cols-2 sm:grid-cols-3 gap-4">
              <Field label="交易方向" value={proposal.direction} />
              <Field label="标的" value={proposal.symbol} />
              <Field label="置信度" value={proposal.confidence != null ? `${(proposal.confidence * 100).toFixed(1)}%` : null} />
              <Field label="边际评分" value={proposal.edgeScore?.toFixed(2)} />
              <Field label="市场状态" value={proposal.regime} />
              <Field label="止损" value={proposal.stopLoss?.toFixed(4)} />
              <Field label="止盈" value={proposal.takeProfit?.toFixed(4)} />
              <Field label="杠杆" value={proposal.leverage ? `${proposal.leverage}x` : null} />
              <Field label="仓位大小" value={proposal.positionSize} />
              <Field label="来源" value={proposal.source} />
              <Field label="创建时间" value={new Date(proposal.createdAt).toLocaleString("zh-CN")} />
            </div>

            {/* 描述 */}
            {proposal.description && (
              <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
                <p className="text-xs text-slate-500 mb-2">描述</p>
                <p className="text-sm text-slate-300 whitespace-pre-wrap">{proposal.description}</p>
              </div>
            )}

            {/* 原始输入证据 */}
            {proposal.rawInput && (
              <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
                <p className="text-xs text-slate-500 mb-2">原始输入 (证据)</p>
                <pre className="text-xs text-slate-400 whitespace-pre-wrap overflow-auto max-h-48">{proposal.rawInput}</pre>
              </div>
            )}

            {/* 关联任务 */}
            {proposal.tasks && proposal.tasks.length > 0 && (
              <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
                <p className="text-xs text-slate-500 mb-3">关联执行任务</p>
                <div className="space-y-2">
                  {proposal.tasks.map((task) => (
                    <div key={task.id} className="flex items-center justify-between text-sm">
                      <span className="text-slate-300">{task.name}</span>
                      <div className="flex items-center gap-3 text-xs text-slate-500">
                        <span>{task.status}</span>
                        {task.totalTrades != null && <span>{task.totalTrades} 笔</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
