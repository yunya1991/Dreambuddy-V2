// ============================================================================
// 操作审计面板（SPEC-7 §11-4 / M1a）
// ----------------------------------------------------------------------------
// 检索 admin_operation_logs、查看 before/after/diff、执行 L0/L1 回滚。
// 回滚请求携带详情接口返回的 targetUpdatedAt 作为 CAS 基准。
// ============================================================================

"use client";

import { useCallback, useEffect, useState } from "react";
import { describeWarnings, fetchConfirmToken, postWrite } from "./write-client";

interface OpRow {
  id: string;
  createdAt: string;
  actorUid: string;
  actorRole: string;
  level: string;
  action: string;
  targetType: string;
  targetId: string;
  status: string;
  reason: string | null;
  warnings: unknown;
}

interface OpDetail {
  op: OpRow;
  canRollback: boolean;
  targetUpdatedAt: string | null;
  /** 交易开关跨两表：{ params, profile } 各自的 updatedAt */
  targetUpdatedAtMap?: Record<string, string> | null;
  /** 文件型配置：当前文件 mtimeMs */
  targetMtimeMs?: number | null;
  rollbacks: OpRow[];
}

const STATUS_STYLE: Record<string, string> = {
  APPLIED: "bg-green-100 text-green-800",
  PENDING_AUDIT: "bg-amber-100 text-amber-800",
  APPLIED_WITH_WARNINGS: "bg-amber-100 text-amber-800",
  FAILED: "bg-red-100 text-red-700",
  ROLLED_BACK: "bg-gray-200 text-gray-700",
};

const EMPTY_FILTERS = {
  actorUid: "",
  action: "",
  targetType: "",
  targetId: "",
  status: "",
};

export function AuditLogsBoard({ writeEnabled }: { writeEnabled: boolean }) {
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<OpRow[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [detail, setDetail] = useState<OpDetail | null>(null);
  const [rollbackReason, setRollbackReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ page: String(page), pageSize: "20" });
    for (const [key, value] of Object.entries(applied)) {
      if (value) params.set(key, value);
    }
    try {
      const res = await fetch(`/api/admin/audit-logs?${params.toString()}`, { cache: "no-store" });
      const json = await res.json().catch(() => null);
      if (!res.ok || !json?.success) {
        setError(json?.message || `HTTP ${res.status}`);
        setRows([]);
        return;
      }
      setRows(json.data.items || []);
      setTotal(json.data.total || 0);
      setTotalPages(json.data.totalPages || 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [applied, page]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openDetail(opId: string) {
    setNotice(null);
    setRollbackReason("");
    const res = await fetch(`/api/admin/audit-logs/${encodeURIComponent(opId)}`, {
      cache: "no-store",
    });
    const json = await res.json().catch(() => null);
    if (!res.ok || !json?.success) {
      setNotice({ ok: false, text: json?.message || "详情加载失败" });
      return;
    }
    setDetail(json.data as OpDetail);
  }

  async function handleRollback() {
    if (!detail) return;
    const isFileConfig = detail.op.targetType === "system-config";
    const isTradingParams = detail.op.targetType === "tradingParams";
    if (isFileConfig && detail.targetMtimeMs == null) {
      setNotice({ ok: false, text: "无法读取配置文件当前版本，可能已被删除" });
      return;
    }
    if (!isFileConfig && !detail.targetUpdatedAt) {
      setNotice({ ok: false, text: "无法读取目标对象当前版本，可能已被删除" });
      return;
    }
    if (detail.op.level === "L1" && rollbackReason.trim().length < 10) {
      setNotice({ ok: false, text: "L1 回滚需填写不少于 10 个字的原因" });
      return;
    }
    if (!window.confirm(`确认回滚操作 ${detail.op.id}？`)) return;

    setBusy(true);
    setNotice(null);
    const reason = rollbackReason.trim() || undefined;
    const payload: Record<string, unknown> = isFileConfig
      ? { expectedMtimeMs: detail.targetMtimeMs, reason }
      : isTradingParams
        ? {
            expectedUpdatedAt: detail.targetUpdatedAt,
            expectedProfileUpdatedAt: detail.targetUpdatedAtMap?.profile || undefined,
            expectedParamsUpdatedAt: detail.targetUpdatedAtMap?.params || undefined,
            reason,
          }
        : { expectedUpdatedAt: detail.targetUpdatedAt, reason };
    let body: Record<string, unknown> = { ...payload };
    if (detail.op.level === "L1") {
      const token = await fetchConfirmToken("rollback", detail.op.id, payload);
      if (!token.ok || !token.token) {
        setBusy(false);
        setNotice({ ok: false, text: token.message || "二次确认失败" });
        return;
      }
      body = { ...body, confirmToken: token.token };
    }

    const result = await postWrite(
      `/api/admin/audit-logs/${encodeURIComponent(detail.op.id)}/rollback`,
      body,
    );
    setBusy(false);
    if (!result.ok) {
      setNotice({ ok: false, text: result.message || "回滚失败" });
      return;
    }
    const warning = describeWarnings((result.data as { warnings?: unknown })?.warnings);
    setNotice({ ok: true, text: warning ? `已回滚，审计待补偿（${warning}）` : "已回滚" });
    setDetail(null);
    void load();
  }

  return (
    <div className="space-y-4">
      <form
        className="grid grid-cols-1 gap-2 rounded-xl border border-gray-200 bg-white p-4 sm:grid-cols-6"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setApplied(draft);
        }}
      >
        {(
          [
            ["actorUid", "操作者 UID"],
            ["action", "动作（如 credits.adjust）"],
            ["targetType", "目标类型"],
            ["targetId", "目标 ID"],
            ["status", "状态"],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="flex flex-col gap-1">
            <span className="text-[11px] text-gray-500">{label}</span>
            <input
              value={draft[key]}
              onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
              className="rounded-lg border border-gray-200 px-2 py-1.5 text-xs focus:border-blue-400 focus:outline-none"
            />
          </label>
        ))}
        <div className="flex items-end gap-2">
          <button
            type="submit"
            className="px-3 py-1.5 text-xs rounded-lg bg-blue-600 text-white hover:bg-blue-700"
          >
            检索
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(EMPTY_FILTERS);
              setApplied(EMPTY_FILTERS);
              setPage(1);
            }}
            className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
          >
            重置
          </button>
        </div>
      </form>

      {notice ? (
        <div
          className={`rounded-lg px-3 py-2 text-xs ${
            notice.ok
              ? "border border-green-200 bg-green-50 text-green-800"
              : "border border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {notice.text}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {["时间", "操作者", "级别", "动作", "目标", "状态", ""].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-gray-600">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-sm text-gray-400">
                    加载中…
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-sm text-red-600">
                    {error}
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-10 text-center text-sm text-gray-400">
                    暂无操作记录
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {new Date(row.createdAt).toLocaleString("zh-CN")}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-700">{row.actorUid}</td>
                    <td className="px-3 py-2 text-xs text-gray-700">{row.level}</td>
                    <td className="px-3 py-2 text-xs text-gray-800">{row.action}</td>
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {row.targetType}/{row.targetId}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-[11px] ${
                          STATUS_STYLE[row.status] || "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => void openDetail(row.id)}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        详情
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between border-t border-gray-200 bg-gray-50 px-4 py-2 text-xs text-gray-500">
          <span>
            共 {total} 条 · 第 {page}/{totalPages} 页
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded-lg border border-gray-200 bg-white px-2 py-1 disabled:opacity-40"
            >
              上一页
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="rounded-lg border border-gray-200 bg-white px-2 py-1 disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        </div>
      </div>

      {detail ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
              <h3 className="text-sm font-semibold text-gray-900">操作详情 · {detail.op.id}</h3>
              <button
                type="button"
                onClick={() => setDetail(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>
            <div className="space-y-3 px-5 py-4 text-xs">
              <div className="grid grid-cols-2 gap-2 text-gray-700">
                <div>动作：{detail.op.action}</div>
                <div>级别：{detail.op.level}</div>
                <div>状态：{detail.op.status}</div>
                <div>
                  目标：{detail.op.targetType}/{detail.op.targetId}
                </div>
                <div className="col-span-2">原因：{detail.op.reason || "—"}</div>
              </div>

              <div>
                <div className="mb-1 font-semibold text-gray-800">变更前</div>
                <pre className="max-h-40 overflow-auto rounded-lg bg-gray-50 p-2 text-[11px] text-gray-700">
                  {JSON.stringify(detail.op, null, 2)}
                </pre>
              </div>

              {detail.rollbacks.length > 0 ? (
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-gray-600">
                  已回滚：{detail.rollbacks.map((r) => r.id).join(", ")}
                </div>
              ) : null}

              {detail.canRollback && writeEnabled ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                  <div className="mb-2 text-amber-900">回滚将基于变更前值恢复，并重新走并发校验。</div>
                  <textarea
                    value={rollbackReason}
                    onChange={(e) => setRollbackReason(e.target.value)}
                    rows={2}
                    placeholder={
                      detail.op.level === "L1" ? "L1 回滚原因（≥10 字）" : "回滚原因（可选）"
                    }
                    className="w-full rounded-lg border border-amber-200 px-2 py-1.5 text-xs focus:outline-none"
                  />
                  <div className="mt-2 flex justify-end">
                    <button
                      type="button"
                      onClick={() => void handleRollback()}
                      disabled={busy}
                      className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs text-white hover:bg-amber-700 disabled:opacity-40"
                    >
                      {busy ? "处理中…" : "回滚该操作"}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
