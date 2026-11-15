// ============================================================================
// 积分调账抽屉（SPEC-7 §6.3 分档 / §11-2 抽屉 + dryRun diff）
// ----------------------------------------------------------------------------
// L0（|delta| ≤ 500）：一次确认；
// L1（501 ~ 5000）：必填原因（≥10 字）+ 二次确认令牌；
// > 5000：按钮前置提示，服务端仍会以 RULE_BLOCKED 兜底。
// ============================================================================

"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { describeWarnings, fetchConfirmToken, postWrite } from "./write-client";

const L0_MAX = 500;
const L1_MAX = 5000;

interface AdjustData {
  opId: string | null;
  status: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  warnings: unknown;
  simulated?: boolean;
}

export function CreditsAdjustButton({
  uid,
  balance,
  expectedUpdatedAt,
  writeEnabled,
}: {
  uid: string;
  balance: number;
  expectedUpdatedAt: string;
  writeEnabled: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [deltaText, setDeltaText] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<AdjustData | null>(null);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const delta = Number(deltaText);
  const magnitude = Number.isFinite(delta) ? Math.abs(delta) : 0;
  const level = magnitude === 0 ? null : magnitude <= L0_MAX ? "L0" : "L1";
  const blocked = magnitude > L1_MAX;

  const payload = useMemo(
    () => ({ delta, reason: reason.trim() || undefined, expectedUpdatedAt }),
    [delta, reason, expectedUpdatedAt],
  );

  const url = `/api/admin/credits/${encodeURIComponent(uid)}/adjust`;

  function close() {
    setOpen(false);
    setDeltaText("");
    setReason("");
    setPreview(null);
    setFeedback(null);
  }

  async function handleDryRun() {
    if (!level || blocked) return;
    setBusy(true);
    setFeedback(null);
    const result = await postWrite<AdjustData>(`${url}?dryRun=1`, payload);
    setBusy(false);
    if (!result.ok || !result.data) {
      setPreview(null);
      setFeedback({ ok: false, text: result.message || "预演失败" });
      return;
    }
    setPreview(result.data);
  }

  async function handleSubmit() {
    if (!level || blocked) return;
    if (level === "L1" && reason.trim().length < 10) {
      setFeedback({ ok: false, text: "501~5000 额度需填写不少于 10 个字的原因" });
      return;
    }
    setBusy(true);
    setFeedback(null);

    let body: Record<string, unknown> = { ...payload };
    if (level === "L1") {
      const token = await fetchConfirmToken("credits.adjust", uid, payload);
      if (!token.ok || !token.token) {
        setBusy(false);
        setFeedback({ ok: false, text: token.message || "二次确认失败" });
        return;
      }
      body = { ...body, confirmToken: token.token };
    }

    const result = await postWrite<AdjustData>(url, body);
    setBusy(false);
    if (!result.ok) {
      setFeedback({ ok: false, text: result.message || "调账失败" });
      return;
    }
    const warning = describeWarnings(result.data?.warnings);
    setFeedback({
      ok: true,
      text: warning ? `已生效，下游同步待补偿（${warning}）` : `调账成功（${level}）`,
    });
    setPreview(null);
    router.refresh();
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={!writeEnabled}
        title={writeEnabled ? "积分调账" : "当前实例只读"}
        className="px-2.5 py-1 text-xs rounded-md border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        调账
      </button>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
              <h3 className="text-sm font-semibold text-gray-900">积分调账 · {uid}</h3>
              <button type="button" onClick={close} className="text-gray-400 hover:text-gray-600">
                ✕
              </button>
            </div>

            <div className="space-y-3 px-5 py-4 text-sm">
              <div className="flex items-center justify-between text-xs text-gray-600">
                <span>当前余额：{balance.toLocaleString()}</span>
                <span className={blocked ? "text-red-600" : "text-gray-500"}>
                  {level
                    ? blocked
                      ? "超过 5000，需走 27 审批"
                      : `级别 ${level}${level === "L1" ? "（需二次确认 + 原因 ≥10 字）" : ""}`
                    : "请输入调整数量"}
                </span>
              </div>

              <label className="block">
                <span className="text-xs text-gray-600">调整数量（正数发放，负数扣减）</span>
                <input
                  type="number"
                  value={deltaText}
                  onChange={(e) => setDeltaText(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none"
                  placeholder="例如 500 或 -300"
                />
              </label>

              <label className="block">
                <span className="text-xs text-gray-600">
                  原因{level === "L1" ? "（必填，≥10 字）" : "（可选）"}
                </span>
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={2}
                  className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none"
                  placeholder="例如：用户反馈任务失败，人工核对后补偿"
                />
              </label>

              {preview ? (
                <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">
                  <div className="font-semibold">预演结果（未落库）</div>
                  <div className="mt-1">
                    余额：{String(preview.before?.balance ?? "-")} → {String(preview.after?.balance ?? "-")}
                  </div>
                </div>
              ) : null}

              {feedback ? (
                <div
                  className={`rounded-lg px-3 py-2 text-xs ${
                    feedback.ok
                      ? "border border-green-200 bg-green-50 text-green-800"
                      : "border border-red-200 bg-red-50 text-red-700"
                  }`}
                >
                  {feedback.text}
                </div>
              ) : null}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-gray-200 px-5 py-3">
              <button
                type="button"
                onClick={handleDryRun}
                disabled={busy || !level || blocked}
                className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-40"
              >
                预演
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={busy || !level || blocked}
                className="px-3 py-1.5 text-xs rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40"
              >
                {busy ? "处理中…" : "提交"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
