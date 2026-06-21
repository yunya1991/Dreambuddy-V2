/**
 * Classic System 监控面板
 * 
 * 展示 Dreambuddy-v2 与 Classic System 集成的监控数据
 * 包括：审批状态、回滚点、系统健康、策略推送历史
 */

import { useEffect, useState } from "react";

const CLASSIC_BASE = "http://127.0.0.1:8092";

interface Approval {
  id: string;
  strategy_name: string;
  changeset_id: string;
  status: "pending" | "approved" | "rejected";
  request_type: string;
  reason: string;
  priority: "low" | "normal" | "high";
  risks: string[];
  created_at: string;
}

interface RollbackPoint {
  id: string;
  strategy_name: string;
  changeset_id: string;
  snapshot_id: string;
  reason: string;
  created_at: string;
}

interface PipelineHistory {
  strategy_name: string;
  trace_id: string;
  status: string;
  timestamp: number;
  phases: string[];
}

export default function ClassicMonitorPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [rollbackPoints, setRollbackPoints] = useState<RollbackPoint[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"approvals" | "rollback" | "history">("approvals");

  useEffect(() => {
    fetchMonitorData();
  }, []);

  const fetchMonitorData = async () => {
    setLoading(true);
    setError(null);

    try {
      const [approvalsRes, rollbackRes, healthRes] = await Promise.all([
        fetch(`${CLASSIC_BASE}/agent/approvals/list`),
        fetch(`${CLASSIC_BASE}/evaluation/rollback/list`),
        fetch(`${CLASSIC_BASE}/agent/api/health`),
      ]);

      const approvalsData = await approvalsRes.json();
      const rollbackData = await rollbackRes.json();
      const healthData = await healthRes.json();

      setApprovals(approvalsData?.approvals || []);
      setRollbackPoints(rollbackData?.points || []);
      setHealth(healthData);
    } catch (err: any) {
      setError(`连接 Classic System 失败: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleApprovalAction = async (id: string, action: "approve" | "reject") => {
    try {
      const res = await fetch(`${CLASSIC_BASE}/agent/approvals/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, action, comment: "" }),
      });
      const result = await res.json();
      if (result.ok) {
        fetchMonitorData(); // 刷新数据
      }
    } catch (err) {
      console.error("审批操作失败:", err);
    }
  };

  const handleRollback = async (id: string) => {
    if (!confirm("确定要回滚吗？")) return;
    try {
      const res = await fetch(`${CLASSIC_BASE}/evaluation/rollback/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, reason: "用户主动回滚" }),
      });
      const result = await res.json();
      if (result.ok) {
        alert("回滚成功");
        fetchMonitorData();
      }
    } catch (err) {
      console.error("回滚失败:", err);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950">
        <div className="text-white text-lg">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950">
        <div className="text-red-400 bg-red-900/30 border border-red-700 px-6 py-4 rounded-lg">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <div className="bg-gray-900 border-b border-gray-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold">🎛️ Classic System 监控面板</h1>
            <p className="text-gray-400 text-sm mt-1">Dreambuddy-v2 策略治理监控</p>
          </div>
          <div className="flex items-center gap-4">
            <div className={`px-4 py-2 rounded-full ${health?.ok ? "bg-green-900 text-green-300" : "bg-red-900 text-red-300"}`}>
              {health?.ok ? "● 系统正常" : "● 系统异常"}
            </div>
            <button
              onClick={fetchMonitorData}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-md text-sm font-medium"
            >
              刷新
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-800">
        <div className="flex gap-1 px-6">
          {[
            { id: "approvals", label: "待审批", count: approvals.filter(a => a.status === "pending").length },
            { id: "rollback", label: "回滚点", count: rollbackPoints.length },
            { id: "history", label: "推送历史", count: 0 },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-indigo-500 text-indigo-400"
                  : "border-transparent text-gray-400 hover:text-white"
              }`}
            >
              {tab.label} {tab.count > 0 && <span className="ml-2 px-2 py-0.5 bg-gray-700 rounded-full text-xs">{tab.count}</span>}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="p-6">
        {/* 待审批 Tab */}
        {activeTab === "approvals" && (
          <div>
            {approvals.length === 0 ? (
              <div className="text-center py-12 text-gray-500">暂无待审批项</div>
            ) : (
              <div className="space-y-4">
                {approvals.map((approval) => (
                  <div key={approval.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="font-semibold text-lg">{approval.strategy_name}</span>
                          <span className={`px-2 py-0.5 rounded text-xs ${
                            approval.status === "pending" ? "bg-yellow-900 text-yellow-300" :
                            approval.status === "approved" ? "bg-green-900 text-green-300" :
                            "bg-red-900 text-red-300"
                          }`}>
                            {approval.status === "pending" ? "待审批" : approval.status === "approved" ? "已通过" : "已拒绝"}
                          </span>
                          <span className={`px-2 py-0.5 rounded text-xs ${
                            approval.priority === "high" ? "bg-red-900 text-red-300" :
                            approval.priority === "normal" ? "bg-blue-900 text-blue-300" :
                            "bg-gray-700 text-gray-300"
                          }`}>
                            {approval.priority === "high" ? "高优先级" : approval.priority === "normal" ? "普通" : "低"}
                          </span>
                        </div>
                        <div className="text-sm text-gray-400 mb-2">
                          变更ID: {approval.changeset_id}
                        </div>
                        <div className="text-sm text-gray-300 mb-2">
                          原因: {approval.reason}
                        </div>
                        {approval.risks.length > 0 && (
                          <div className="flex flex-wrap gap-2 mt-2">
                            {approval.risks.map((risk, i) => (
                              <span key={i} className="px-2 py-1 bg-orange-900/50 text-orange-300 rounded text-xs">
                                ⚠️ {risk}
                              </span>
                            ))}
                          </div>
                        )}
                        <div className="text-xs text-gray-500 mt-2">
                          创建时间: {new Date(approval.created_at).toLocaleString()}
                        </div>
                      </div>
                      {approval.status === "pending" && (
                        <div className="flex gap-2 ml-4">
                          <button
                            onClick={() => handleApprovalAction(approval.id, "approve")}
                            className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-md text-sm font-medium"
                          >
                            通过
                          </button>
                          <button
                            onClick={() => handleApprovalAction(approval.id, "reject")}
                            className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-md text-sm font-medium"
                          >
                            拒绝
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 回滚点 Tab */}
        {activeTab === "rollback" && (
          <div>
            {rollbackPoints.length === 0 ? (
              <div className="text-center py-12 text-gray-500">暂无回滚点</div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {rollbackPoints.map((point) => (
                  <div key={point.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                    <div className="font-semibold mb-2">{point.strategy_name}</div>
                    <div className="text-sm text-gray-400 mb-2">
                      快照: {point.snapshot_id.slice(0, 8)}...
                    </div>
                    <div className="text-sm text-gray-300 mb-3">
                      {point.reason}
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500">
                        {new Date(point.created_at).toLocaleString()}
                      </span>
                      <button
                        onClick={() => handleRollback(point.id)}
                        className="px-3 py-1.5 bg-orange-600 hover:bg-orange-500 rounded text-sm font-medium"
                      >
                        回滚
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 推送历史 Tab */}
        {activeTab === "history" && (
          <div className="text-center py-12 text-gray-500">
            <p>推送历史功能开发中...</p>
            <p className="text-sm mt-2">可通过 /agent/audit/list 端点查询</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-800 px-6 py-3">
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>Classic System Monitor v1.0</span>
          <span>连接: {CLASSIC_BASE}</span>
        </div>
      </div>
    </div>
  );
}
