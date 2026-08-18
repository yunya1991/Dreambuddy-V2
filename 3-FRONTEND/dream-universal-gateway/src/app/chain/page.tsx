"use client";

import { useEffect, useState, useCallback } from "react";
import { WorkflowCard } from "@/components/workflow";
import type { WorkflowCardStep } from "@/components/workflow";

interface ChainArtifact {
  artifact_id: string;
  title: string;
  department: string;
  chain_phase: string;
  status: string;
  workflow_type: "legacy_chain" | "trading_v2";
  created_at: string;
}

interface ChainData {
  legacy_chain: ChainArtifact[];
  trading_v2: ChainArtifact[];
  total: number;
}

function artifactsToSteps(artifacts: ChainArtifact[]): WorkflowCardStep[] {
  return artifacts.map(a => ({
    id: a.artifact_id,
    label: `[${a.chain_phase}] ${a.title}`,
    status: a.status === "completed" ? "success"
          : a.status === "processing" ? "running"
          : a.status === "failed" ? "error"
          : "pending",
    description: a.department,
  }));
}

export default function ChainPage() {
  const [data, setData] = useState<ChainData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/chain/artifacts");
      const json = await res.json();
      if (!json.success) throw new Error(json.error ?? "fetch_failed");
      setData(json.data as ChainData);
    } catch (e) {
      setError(e instanceof Error ? e.message : "unknown_error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">/chain 工作流可视化</h1>
            <p className="text-gray-400 text-sm mt-1">
              双工作流并排视图 — Legacy Chain vs Trading V2
            </p>
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 text-sm font-medium disabled:opacity-50 transition-colors"
          >
            {loading ? "加载中..." : "刷新"}
          </button>
        </div>

        {/* Error state */}
        {error && (
          <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">
            连接 Hub 失败: {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !data && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {[0, 1].map(i => (
              <div key={i} className="rounded-lg border border-gray-800 bg-gray-900 p-4 animate-pulse h-48" />
            ))}
          </div>
        )}

        {/* Dual workflow side-by-side layout */}
        {data && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <WorkflowCard
              workflowId="legacy_chain"
              workflowType="legacy_chain"
              title={`Legacy Chain (${data.legacy_chain.length} artifacts)`}
              steps={artifactsToSteps(data.legacy_chain)}
            />
            <WorkflowCard
              workflowId="trading_v2"
              workflowType="trading_v2"
              title={`Trading V2 (${data.trading_v2.length} artifacts)`}
              steps={artifactsToSteps(data.trading_v2)}
            />
          </div>
        )}

        {/* Empty state */}
        {data && data.total === 0 && (
          <p className="text-center text-gray-500 py-16">暂无工作流数据</p>
        )}
      </div>
    </div>
  );
}