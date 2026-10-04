"use client";

import { useState, useEffect, useCallback } from "react";
import { AdminTopBar } from "@/components/admin/AdminTopBar";

interface TraceEvent {
  v: number;
  id: string;
  trace_id: string;
  span_id?: string;
  parent_span_id?: string | null;
  ts: string;
  system: string;
  layer: string;
  node?: string;
  event_type: string;
  status: string;
  duration_ms?: number | null;
  payload_ref?: string | null;
  error?: string | null;
  meta?: Record<string, unknown>;
}

interface TraceSummary {
  systems: string[];
  layers: string[];
  error_count: number;
  total_duration_ms: number;
  first_event_ts: string | null;
  last_event_ts: string | null;
}

interface TraceResponse {
  events: TraceEvent[];
  total: number;
  trace_id?: string;
  date: string;
  source?: string;  // pg | jsonl
  summary: TraceSummary;
}

const SYSTEM_COLORS: Record<string, string> = {
  frontend: "bg-blue-100 text-blue-700 border-blue-200",
  dreamos: "bg-purple-100 text-purple-700 border-purple-200",
  dsh: "bg-green-100 text-green-700 border-green-200",
  hub: "bg-orange-100 text-orange-700 border-orange-200",
};

const STATUS_COLORS: Record<string, string> = {
  ok: "text-green-600",
  fail: "text-red-600",
  skip: "text-gray-400",
};

export default function TracesPage() {
  const [traceId, setTraceId] = useState("");
  const [date, setDate] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  });
  const [system, setSystem] = useState("");
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [summary, setSummary] = useState<TraceSummary | null>(null);
  const [dataSource, setDataSource] = useState<string>("pg");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchTraces = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (traceId) params.set("trace_id", traceId);
      if (date) params.set("date", date);
      if (system) params.set("system", system);
      const res = await fetch(`/api/ops/traces?${params.toString()}`);
      const json = await res.json();
      if (json.success) {
        setEvents(json.data.events);
        setSummary(json.data.summary);
        setDataSource(json.data.source || "jsonl");
      } else {
        setError(json.error || "查询失败");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [traceId, date, system]);

  // 初始加载
  useEffect(() => {
    fetchTraces();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const formatTs = (ts: string) => {
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString("zh-CN", { hour12: false }) +
        "." + String(d.getMilliseconds()).padStart(3, "0");
    } catch {
      return ts;
    }
  };

  return (
    <>
      <AdminTopBar
        title="链路追踪"
        subtitle={summary
          ? `${summary.systems.length} 系统 · ${events.length} 事件 · ${summary.error_count} 错误 · ${(summary.total_duration_ms / 1000).toFixed(1)}s 总耗时`
          : "L1 可观测性试点 · 跨系统 trace 查询"
        }
      />
      <main className="p-6 flex-1">
        {/* 数据源指示 */}
        <div className="mb-3 flex items-center gap-2 text-xs">
          <span className="text-gray-500">数据源:</span>
          <span className={`px-2 py-0.5 rounded-full font-medium ${dataSource === "pg" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
            {dataSource === "pg" ? "PostgreSQL" : "JSONL (fallback)"}
          </span>
        </div>

        {/* 搜索栏 */}
        <div className="mb-4 flex items-center gap-3 flex-wrap">
          <input
            type="text"
            value={traceId}
            onChange={(e) => setTraceId(e.target.value)}
            placeholder="输入 trace_id 查询 (如 20260929-143022-FE-a3f9k2m1)"
            className="flex-1 min-w-[300px] px-4 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400 font-mono"
          />
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400"
          />
          <select
            value={system}
            onChange={(e) => setSystem(e.target.value)}
            className="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400"
          >
            <option value="">全部系统</option>
            <option value="frontend">前端</option>
            <option value="dreamos">DreamOS</option>
            <option value="dsh">DSH</option>
            <option value="hub">中台</option>
          </select>
          <button
            onClick={fetchTraces}
            disabled={loading}
            className="px-4 py-2 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "查询中..." : "查询"}
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
            {error}
          </div>
        )}

        {/* 事件列表 */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          {events.length === 0 ? (
            <div className="px-4 py-12 text-center text-gray-400 text-sm">
              {loading ? "加载中..." : "暂无事件数据。请先在 3.1 前端发起一次任务。"}
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {events.map((evt) => (
                <div key={evt.id}>
                  <button
                    onClick={() => setExpandedId(expandedId === evt.id ? null : evt.id)}
                    className="w-full px-4 py-3 flex items-center gap-3 hover:bg-gray-50 transition-colors text-left"
                  >
                    {/* 系统标签 */}
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium border ${SYSTEM_COLORS[evt.system] || "bg-gray-100 text-gray-700 border-gray-200"}`}>
                      {evt.system}
                    </span>
                    {/* 事件类型 */}
                    <span className="text-sm font-mono text-gray-700 min-w-[180px]">
                      {evt.event_type}
                    </span>
                    {/* 节点 */}
                    <span className="text-xs text-gray-500 min-w-[100px]">
                      {evt.node || "-"}
                    </span>
                    {/* 状态 */}
                    <span className={`text-xs font-medium ${STATUS_COLORS[evt.status] || "text-gray-600"}`}>
                      {evt.status === "ok" ? "✓" : evt.status === "fail" ? "✗" : "○"}
                    </span>
                    {/* 耗时 */}
                    <span className="text-xs text-gray-500 min-w-[60px] text-right">
                      {evt.duration_ms != null ? `${evt.duration_ms.toFixed(0)}ms` : "-"}
                    </span>
                    {/* 时间 */}
                    <span className="text-xs text-gray-400 ml-auto">
                      {formatTs(evt.ts)}
                    </span>
                  </button>

                  {/* 展开详情 */}
                  {expandedId === evt.id && (
                    <div className="px-4 pb-3 pl-[calc(1rem+80px)]">
                      <div className="bg-gray-50 rounded-lg p-3 text-xs font-mono space-y-1">
                        <div><span className="text-gray-500">trace_id:</span> {evt.trace_id}</div>
                        <div><span className="text-gray-500">span_id:</span> {evt.span_id || "-"}</div>
                        <div><span className="text-gray-500">layer:</span> {evt.layer}</div>
                        {evt.error && (
                          <div className="text-red-600"><span className="text-gray-500">error:</span> {evt.error}</div>
                        )}
                        {evt.meta && Object.keys(evt.meta).length > 0 && (
                          <details className="mt-2">
                            <summary className="text-gray-500 cursor-pointer hover:text-gray-700">
                              meta ({Object.keys(evt.meta).length} keys)
                            </summary>
                            <pre className="mt-1 p-2 bg-white rounded border text-[10px] overflow-x-auto">
                              {JSON.stringify(evt.meta, null, 2)}
                            </pre>
                          </details>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
