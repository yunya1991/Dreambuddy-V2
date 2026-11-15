// ============================================================================
// 移动止损参数编辑器（SPEC-7 §10 / M2）
// ----------------------------------------------------------------------------
// 只写白名单 key：trigger_cooldown_sec、auto_close_after_sec、report.enabled、
// report.output_dir。L1：原因 ≥10 字 + confirmToken；expectedMtimeMs 做文件级并发。
// 与 monitor 不同：写入后需重启下游执行侧服务才生效（requiresRestart=true）。
// ============================================================================

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { fetchConfirmToken, sendWrite } from "./write-client";
import { SYSTEM_CONFIG_ACTION } from "@/lib/admin/constants";

export interface TrailingStopValues {
  triggerCooldownSec: number | null;
  autoCloseAfterSec: number | null;
  reportEnabled: boolean;
  reportOutputDir: string;
}

interface Props {
  values: TrailingStopValues;
  mtimeMs: number;
  writeEnabled: boolean;
}

const SECONDS_MIN = 0;
const SECONDS_MAX = 86400;

export function TrailingStopConfigEditor({ values, mtimeMs, writeEnabled }: Props) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);
  const [cooldown, setCooldown] = useState(
    values.triggerCooldownSec === null ? "" : String(values.triggerCooldownSec),
  );
  const [autoClose, setAutoClose] = useState(
    values.autoCloseAfterSec === null ? "" : String(values.autoCloseAfterSec),
  );
  const [reportEnabled, setReportEnabled] = useState(values.reportEnabled);
  const [outputDir, setOutputDir] = useState(values.reportOutputDir);

  function buildPatch(): Record<string, unknown> | string {
    const patch: Record<string, unknown> = {};

    if (cooldown !== String(values.triggerCooldownSec ?? "")) {
      const value = Number(cooldown);
      if (!Number.isInteger(value) || value < SECONDS_MIN || value > SECONDS_MAX) {
        return `触发冷却需为 ${SECONDS_MIN}~${SECONDS_MAX} 的整数秒`;
      }
      patch.trigger_cooldown_sec = value;
    }
    if (autoClose !== String(values.autoCloseAfterSec ?? "")) {
      const value = Number(autoClose);
      if (!Number.isInteger(value) || value < SECONDS_MIN || value > SECONDS_MAX) {
        return `自动平仓时限需为 ${SECONDS_MIN}~${SECONDS_MAX} 的整数秒`;
      }
      patch.auto_close_after_sec = value;
    }
    if (reportEnabled !== values.reportEnabled) {
      patch["report.enabled"] = reportEnabled;
    }
    if (outputDir !== values.reportOutputDir) {
      const trimmed = outputDir.trim();
      if (!trimmed) return "报告输出目录不能为空";
      if (trimmed.startsWith("/") || trimmed.includes("..")) {
        return "报告输出目录必须是仓库内相对路径（不含 ..）";
      }
      patch["report.output_dir"] = trimmed;
    }

    if (Object.keys(patch).length === 0) return "没有改动";
    return patch;
  }

  async function submit() {
    const patch = buildPatch();
    if (typeof patch === "string") {
      setFeedback({ ok: false, text: patch });
      return;
    }
    if (
      !window.confirm(
        "确认保存移动止损配置？写入后需重启下游执行侧服务才会生效（不是立即生效）。",
      )
    ) {
      return;
    }
    const reason = window.prompt("请填写变更原因（不少于 10 字）")?.trim() || "";
    if (reason.length < 10) {
      setFeedback({ ok: false, text: "原因不少于 10 字，已取消" });
      return;
    }

    setPending(true);
    setFeedback(null);
    const body: Record<string, unknown> = { patch, expectedMtimeMs: mtimeMs, reason };
    const token = await fetchConfirmToken(SYSTEM_CONFIG_ACTION, "trailing_stop", body);
    if (!token.ok || !token.token) {
      setPending(false);
      setFeedback({ ok: false, text: token.message || "确认令牌获取失败" });
      return;
    }
    const result = await sendWrite("PATCH", "/api/admin/system-config?file=trailing_stop", {
      ...body,
      confirmToken: token.token,
    });
    setPending(false);
    setFeedback({
      ok: result.ok,
      text: result.ok ? result.message || "已写入" : result.message || "写入失败",
    });
    if (result.ok) router.refresh();
  }

  const fieldClass =
    "w-32 px-2 py-1 text-sm border border-gray-200 rounded-md focus:outline-none focus:border-blue-400 disabled:bg-gray-50";

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-4 py-2 text-xs border-b border-amber-100 bg-amber-50 text-amber-700">
        移动止损参数由执行侧启动时加载：写入成功后需重启对应服务才生效。
      </div>
      <div className="p-4 space-y-4">
        <div className="flex items-center gap-3">
          <span className="w-48 text-sm text-gray-700">trigger_cooldown_sec</span>
          <input
            type="number"
            min={SECONDS_MIN}
            max={SECONDS_MAX}
            value={cooldown}
            onChange={(event) => setCooldown(event.target.value)}
            disabled={!writeEnabled || pending}
            className={fieldClass}
          />
          <span className="text-xs text-gray-500">触发冷却（秒）</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="w-48 text-sm text-gray-700">auto_close_after_sec</span>
          <input
            type="number"
            min={SECONDS_MIN}
            max={SECONDS_MAX}
            value={autoClose}
            onChange={(event) => setAutoClose(event.target.value)}
            disabled={!writeEnabled || pending}
            className={fieldClass}
          />
          <span className="text-xs text-gray-500">自动平仓时限（秒）</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="w-48 text-sm text-gray-700">report.enabled</span>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={reportEnabled}
              onChange={(event) => setReportEnabled(event.target.checked)}
              disabled={!writeEnabled || pending}
            />
            {reportEnabled ? "启用报告" : "关闭报告"}
          </label>
        </div>
        <div className="flex items-center gap-3">
          <span className="w-48 text-sm text-gray-700">report.output_dir</span>
          <input
            type="text"
            value={outputDir}
            onChange={(event) => setOutputDir(event.target.value)}
            disabled={!writeEnabled || pending}
            className="w-96 px-2 py-1 text-sm font-mono border border-gray-200 rounded-md focus:outline-none focus:border-blue-400 disabled:bg-gray-50"
          />
          <span className="text-xs text-gray-500">仓库内相对路径</span>
        </div>
        <div>
          <button
            type="button"
            disabled={!writeEnabled || pending}
            onClick={submit}
            className="px-3 py-1.5 text-sm rounded-md border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {pending ? "处理中…" : "保存（需二次确认）"}
          </button>
        </div>
      </div>
      {feedback ? (
        <div
          className={`px-4 py-2 text-xs border-t ${
            feedback.ok
              ? "border-green-100 bg-green-50 text-green-700"
              : "border-red-100 bg-red-50 text-red-600"
          }`}
        >
          {feedback.text}
        </div>
      ) : null}
      {!writeEnabled ? (
        <div className="px-4 py-2 text-xs border-t border-gray-100 bg-gray-50 text-gray-500">
          当前实例为只读模式（ADMIN_WRITE_ENABLED 未开启）
        </div>
      ) : null}
    </div>
  );
}
