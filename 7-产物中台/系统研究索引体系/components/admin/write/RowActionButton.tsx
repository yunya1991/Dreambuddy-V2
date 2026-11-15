// ============================================================================
// 行内写操作按钮（L0/L1 通用，SPEC-7 §11）
// ----------------------------------------------------------------------------
// · L0：一次确认，reason 可选
// · L1：二次确认 + 原因 ≥10 字，自动换取一次性 confirmToken
// · 统一处理 dryRun 关闭、写开关关闭、幂等键、warnings 提示与页面刷新
// ============================================================================

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { describeWarnings, fetchConfirmToken, sendWrite } from "./write-client";

export interface RowActionButtonProps {
  label: string;
  endpoint: string;
  payload: Record<string, unknown>;
  confirmText: string;
  level: "L0" | "L1";
  /** L1 必填：confirmToken 绑定的动作标识 */
  action?: string;
  /** L1 必填：confirmToken 绑定的目标 ID */
  targetId?: string;
  writeEnabled: boolean;
  disabled?: boolean;
  disabledHint?: string;
  danger?: boolean;
  method?: "POST" | "PATCH";
}

export function RowActionButton({
  label,
  endpoint,
  payload,
  confirmText,
  level,
  action,
  targetId,
  writeEnabled,
  disabled = false,
  disabledHint,
  danger = false,
  method = "PATCH",
}: RowActionButtonProps) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);

  const isDisabled = !writeEnabled || disabled || pending;

  async function handleClick() {
    if (!window.confirm(confirmText)) return;

    const body: Record<string, unknown> = { ...payload };
    if (level === "L1") {
      const reason = window.prompt("请填写操作原因（不少于 10 字）")?.trim() || "";
      if (reason.length < 10) {
        setFeedback({ ok: false, text: "原因不少于 10 字，已取消" });
        return;
      }
      body.reason = reason;
      if (!action || !targetId) {
        setFeedback({ ok: false, text: "内部错误：缺少确认令牌绑定参数" });
        return;
      }
      const token = await fetchConfirmToken(action, targetId, body);
      if (!token.ok || !token.token) {
        setFeedback({ ok: false, text: token.message || "确认令牌获取失败" });
        return;
      }
      body.confirmToken = token.token;
    }

    setPending(true);
    setFeedback(null);
    const result = await sendWrite<{ status: string; warnings: unknown }>(method, endpoint, body);
    setPending(false);
    if (!result.ok) {
      setFeedback({ ok: false, text: result.message || `${label}失败` });
      return;
    }
    const warning = describeWarnings(result.data?.warnings);
    setFeedback({
      ok: true,
      text: warning ? `已生效，下游同步待补偿（${warning}）` : result.message || "已生效",
    });
    router.refresh();
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={isDisabled}
        title={!writeEnabled ? "当前实例只读" : disabledHint || label}
        className={`px-2.5 py-1 text-xs rounded-md border bg-white disabled:opacity-40 disabled:cursor-not-allowed ${
          danger
            ? "border-red-200 text-red-600 hover:bg-red-50"
            : "border-gray-200 text-gray-700 hover:bg-gray-50"
        }`}
      >
        {pending ? "处理中…" : label}
      </button>
      {feedback ? (
        <span className={`text-[11px] ${feedback.ok ? "text-green-700" : "text-red-600"}`}>
          {feedback.text}
        </span>
      ) : null}
    </div>
  );
}
