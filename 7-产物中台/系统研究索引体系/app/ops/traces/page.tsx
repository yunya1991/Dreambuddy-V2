"use client";

import { useState, useEffect, useCallback } from "react";

interface TraceEvent {
  v: number;
  id: string;
  trace_id: string;
  span_id?: string;
  ts: string;
  system: string;
  layer: string;
  node?: string;
  event_type: string;
  status: string;
  duration_ms?: number | null;
  error?: string | null;
  meta?: Record<string, unknown>;
}

interface TraceResponse {
  success: boolean;
  data?: {
    events: TraceEvent[];
    total: number;
    trace_id?: string;
    date: string;
    source: string;
    summary: {
      systems: string[];
      layers: string[];
      error_count: number;
      total_duration_ms: number;
      first_event_ts: string | null;
      last_event_ts: string | null;
    };
  };
  error?: string;
}

const SYSTEM_COLORS: Record<string, string> = {
  frontend: "#3b82f6",
  dreamos: "#8b5cf6",
  dsh: "#f59e0b",
  hub: "#10b981",
};

const STATUS_COLORS: Record<string, string> = {
  ok: "#10b981",
  fail: "#ef4444",
  skip: "#6b7280",
  received: "#3b82f6",
  processing: "#f59e0b",
  completed: "#10b981",
  failed: "#ef4444",
};

export default function TracesPage() {
  const [traceId, setTraceId] = useState("");
  const [date, setDate] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  });
  const [system, setSystem] = useState("");
  const [data, setData] = useState<TraceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  const fetchTraces = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (traceId) params.set("trace_id", traceId);
      if (date) params.set("date", date);
      if (system) params.set("system", system);
      params.set("source", "jsonl");
      params.set("limit", "500");

      const res = await fetch(`/api/ops/traces?${params}`);
      const json: TraceResponse = await res.json();
      setData(json);
    } catch (e) {
      setData({ success: false, error: String(e) });
    } finally {
      setLoading(false);
    }
  }, [traceId, date, system]);

  useEffect(() => {
    fetchTraces();
  }, [fetchTraces]);

  const events = data?.data?.events || [];
  const summary = data?.data?.summary;

  return (
    <div style={{ fontFamily: "monospace", padding: "24px", maxWidth: "1200px", margin: "0 auto" }}>
      <h1 style={{ fontSize: "24px", fontWeight: "bold", marginBottom: "8px" }}>Trace Inspector</h1>
      <p style={{ color: "#6b7280", fontSize: "14px", marginBottom: "24px" }}>
        L1 可观测性试点 — trace_id 全链路 + JSONL 事件流
      </p>

      {/* 搜索栏 */}
      <div style={{ display: "flex", gap: "12px", marginBottom: "24px", flexWrap: "wrap" }}>
        <input
          type="text"
          placeholder="trace_id (如 20260929-143022-FE-a3f9k2m1)"
          value={traceId}
          onChange={(e) => setTraceId(e.target.value)}
          style={{
            flex: "1", minWidth: "300px", padding: "8px 12px",
            border: "1px solid #d1d5db", borderRadius: "6px",
            fontSize: "14px", fontFamily: "monospace",
          }}
        />
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          style={{
            padding: "8px 12px", border: "1px solid #d1d5db",
            borderRadius: "6px", fontSize: "14px",
          }}
        />
        <select
          value={system}
          onChange={(e) => setSystem(e.target.value)}
          style={{
            padding: "8px 12px", border: "1px solid #d1d5db",
            borderRadius: "6px", fontSize: "14px",
          }}
        >
          <option value="">所有系统</option>
          <option value="frontend">frontend</option>
          <option value="dreamos">dreamos</option>
          <option value="dsh">dsh</option>
          <option value="hub">hub</option>
        </select>
        <button
          onClick={fetchTraces}
          disabled={loading}
          style={{
            padding: "8px 20px", background: "#3b82f6", color: "white",
            border: "none", borderRadius: "6px", fontSize: "14px",
            cursor: loading ? "wait" : "pointer",
          }}
        >
          {loading ? "查询中..." : "查询"}
        </button>
      </div>

      {/* 摘要 */}
      {summary && (
        <div style={{
          display: "flex", gap: "24px", marginBottom: "24px",
          padding: "12px 16px", background: "#f9fafb",
          borderRadius: "8px", fontSize: "13px",
        }}>
          <span>事件: <b>{data?.data?.total || 0}</b></span>
          <span>系统: <b>{summary.systems.join(", ") || "无"}</b></span>
          <span>错误: <b style={{ color: summary.error_count > 0 ? "#ef4444" : "#10b981" }}>{summary.error_count}</b></span>
          <span>总耗时: <b>{summary.total_duration_ms}ms</b></span>
          <span>数据源: <b>{data?.data?.source}</b></span>
        </div>
      )}

      {/* Timeline */}
      {events.length === 0 ? (
        <div style={{ padding: "48px", textAlign: "center", color: "#9ca3af" }}>
          {loading ? "加载中..." : "无事件数据。在前端发起请求后，事件将出现在这里。"}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          {events.map((evt, i) => {
            const sysColor = SYSTEM_COLORS[evt.system] || "#6b7280";
            const statusColor = STATUS_COLORS[evt.status] || "#6b7280";
            const ts = new Date(evt.ts);
            const tsStr = ts.toLocaleTimeString("zh-CN", { hour12: false }) + "." + String(ts.getMilliseconds()).padStart(3, "0");

            return (
              <div
                key={evt.id || i}
                style={{
                  display: "flex", alignItems: "center", gap: "8px",
                  padding: "6px 12px", borderRadius: "4px",
                  background: i % 2 === 0 ? "#f9fafb" : "white",
                  fontSize: "13px", borderLeft: `3px solid ${sysColor}`,
                }}
              >
                <span style={{ color: "#9ca3af", minWidth: "100px" }}>{tsStr}</span>
                <span style={{
                  color: "white", background: sysColor,
                  padding: "1px 6px", borderRadius: "3px", fontSize: "11px",
                  minWidth: "70px", textAlign: "center",
                }}>{evt.system}</span>
                <span style={{ color: "#6b7280", minWidth: "80px" }}>{evt.layer}</span>
                <span style={{ minWidth: "120px" }}>{evt.node || evt.event_type}</span>
                <span style={{
                  color: "white", background: statusColor,
                  padding: "1px 6px", borderRadius: "3px", fontSize: "11px",
                  minWidth: "60px", textAlign: "center",
                }}>{evt.status}</span>
                {evt.duration_ms != null && (
                  <span style={{ color: "#6b7280" }}>{evt.duration_ms}ms</span>
                )}
                {evt.error && (
                  <span style={{ color: "#ef4444", fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {evt.error}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Raw JSON */}
      {events.length > 0 && (
        <div style={{ marginTop: "24px" }}>
          <button
            onClick={() => setShowRaw(!showRaw)}
            style={{
              padding: "6px 12px", background: "#e5e7eb", border: "none",
              borderRadius: "6px", fontSize: "13px", cursor: "pointer",
            }}
          >
            {showRaw ? "隐藏" : "显示"} Raw JSON
          </button>
          {showRaw && (
            <pre style={{
              marginTop: "8px", padding: "12px", background: "#1f2937",
              color: "#e5e7eb", borderRadius: "6px", fontSize: "12px",
              overflow: "auto", maxHeight: "400px",
            }}>
              {JSON.stringify(events, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
