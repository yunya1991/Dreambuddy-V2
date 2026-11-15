// ============================================================================
// 解锁用户按钮（L0，SPEC-7 §6.1 / §11-1）
// 写接口关闭或用户未锁定时禁用；成功后刷新服务端数据。
// ============================================================================

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { describeWarnings, postWrite } from "./write-client";

export function UnlockUserButton({
  uid,
  expectedUpdatedAt,
  locked,
  writeEnabled,
}: {
  uid: string;
  expectedUpdatedAt: string;
  locked: boolean;
  writeEnabled: boolean;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);

  const disabled = !writeEnabled || !locked || pending;

  async function handleClick() {
    if (!window.confirm(`确认解锁用户 ${uid}？该操作会清零登录失败次数并记录审计。`)) return;
    setPending(true);
    setFeedback(null);
    const result = await postWrite<{ status: string; warnings: unknown }>(
      `/api/admin/users/${encodeURIComponent(uid)}/unlock`,
      { expectedUpdatedAt },
    );
    setPending(false);
    if (!result.ok) {
      setFeedback({ ok: false, text: result.message || "解锁失败" });
      return;
    }
    const warning = describeWarnings(result.data?.warnings);
    setFeedback({
      ok: true,
      text: warning ? `已生效，下游同步待补偿（${warning}）` : "已解锁",
    });
    router.refresh();
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        title={!writeEnabled ? "当前实例只读" : !locked ? "该用户未锁定" : "解锁用户"}
        className="px-2.5 py-1 text-xs rounded-md border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {pending ? "处理中…" : "解锁"}
      </button>
      {feedback ? (
        <span className={`text-[11px] ${feedback.ok ? "text-green-700" : "text-red-600"}`}>
          {feedback.text}
        </span>
      ) : null}
    </div>
  );
}
