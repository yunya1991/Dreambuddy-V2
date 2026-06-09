"use client";

import { useEffect, useState } from "react";

interface PushRecord {
  id: string;
  channelType: string;
  messageType: string;
  status: "sent" | "failed" | "pending";
  sentAt?: string;
  recipient?: string;
}

const STATUS_COLOR = { sent: "#4ade80", failed: "#f87171", pending: "#f59e0b" };
const STATUS_LABEL = { sent: "已发送", failed: "失败", pending: "待发送" };

export default function DistributionPage() {
  const [records, setRecords] = useState<PushRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/market/distribution")
      .then(r => r.json())
      .then(json => { if (json.success) setRecords(json.data ?? []); else setError(json.error); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const byChannel = records.reduce<Record<string, number>>((acc, r) => {
    acc[r.channelType] = (acc[r.channelType] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">推送分发</h1>
        <p className="text-gray-400 text-sm mb-6">消息推送分发记录与渠道统计</p>

        {error && <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">{error}</div>}

        {/* Channel summary */}
        {Object.keys(byChannel).length > 0 && (
          <div className="flex flex-wrap gap-3 mb-6">
            {Object.entries(byChannel).map(([ch, cnt]) => (
              <div key={ch} className="rounded-lg bg-gray-900 border border-gray-800 px-4 py-3 text-sm">
                <span className="text-gray-400">{ch}</span>
                <span className="ml-2 font-bold text-white">{cnt}</span>
              </div>
            ))}
          </div>
        )}

        {loading && <div className="space-y-3">{[0,1,2].map(i=><div key={i} className="h-16 rounded-lg bg-gray-900 animate-pulse"/>)}</div>}
        {!loading && records.length === 0 && <p className="text-center text-gray-500 py-16">暂无分发记录</p>}

        <div className="space-y-2">
          {records.map(rec => (
            <div key={rec.id} className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">{rec.channelType}</span>
                <span className="text-sm text-gray-300">{rec.messageType}</span>
                {rec.recipient && <span className="text-xs text-gray-600">→ {rec.recipient}</span>}
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs" style={{ color: STATUS_COLOR[rec.status] }}>{STATUS_LABEL[rec.status]}</span>
                {rec.sentAt && <span className="text-xs text-gray-600">{new Date(rec.sentAt).toLocaleString("zh-CN")}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}