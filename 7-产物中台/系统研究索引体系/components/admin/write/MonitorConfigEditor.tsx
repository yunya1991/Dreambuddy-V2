// ============================================================================
// 监控开关 / 空闲阈值在线编辑器（SPEC-7 §10 / D4）
// ----------------------------------------------------------------------------
// 只写白名单 key：systems.<name>.enabled、systems.<name>.max_idle_minutes。
// L1：原因 ≥10 字 + confirmToken；expectedMtimeMs 做文件级乐观并发。
// 写入后下一轮监控（≤60 分钟）自动重读，无需重启。
// ============================================================================

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { fetchConfirmToken, sendWrite } from "./write-client";
import { SYSTEM_CONFIG_ACTION } from "@/lib/admin/constants";

export interface MonitorSystemRow {
  name: string;
  enabled: boolean;
  maxIdleMinutes: number | null;
}

interface Props {
  systems: MonitorSystemRow[];
  mtimeMs: number;
  writeEnabled: boolean;
}

export function MonitorConfigEditor({ systems, mtimeMs, writeEnabled }: Props) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);
  const [idleValues, setIdleValues] = useState<Record<string, string>>(
    Object.fromEntries(
      systems.map((s) => [s.name, s.maxIdleMinutes === null ? "" : String(s.maxIdleMinutes)]),
    ),
  );

  async function submit(patch: Record<string, unknown>, label: string) {
    if (!window.confirm(`确认${label}？配置将在下一轮监控（≤60 分钟）生效，无需重启。`)) return;
    const reason = window.prompt("请填写变更原因（不少于 10 字）")?.trim() || "";
    if (reason.length < 10) {
      setFeedback({ ok: false, text: "原因不少于 10 字，已取消" });
      return;
    }

    setPending(label);
    setFeedback(null);
    const body: Record<string, unknown> = { patch, expectedMtimeMs: mtimeMs, reason };
    const token = await fetchConfirmToken(SYSTEM_CONFIG_ACTION, "monitor", body);
    if (!token.ok || !token.token) {
      setPending(null);
      setFeedback({ ok: false, text: token.message || "确认令牌获取失败" });
      return;
    }
    const result = await sendWrite("PATCH", "/api/admin/system-config?file=monitor", {
      ...body,
      confirmToken: token.token,
    });
    setPending(null);
    setFeedback({
      ok: result.ok,
      text: result.ok ? result.message || "已写入" : result.message || "写入失败",
    });
    if (result.ok) router.refresh();
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">监控系统</th>
              <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-center">启用</th>
              <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">空闲阈值（分钟）</th>
              <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {systems.map((s) => (
              <tr key={s.name} className="hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 text-sm font-medium text-gray-800">{s.name}</td>
                <td className="px-4 py-3 text-center">
                  <span
                    className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                      s.enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {s.enabled ? "已启用" : "已停用"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min={1}
                      max={1440}
                      value={idleValues[s.name]}
                      onChange={(event) =>
                        setIdleValues((prev) => ({ ...prev, [s.name]: event.target.value }))
                      }
                      disabled={!writeEnabled || pending !== null}
                      className="w-24 px-2 py-1 text-sm border border-gray-200 rounded-md focus:outline-none focus:border-blue-400 disabled:bg-gray-50"
                    />
                    <button
                      type="button"
                      disabled={!writeEnabled || pending !== null}
                      onClick={() => {
                        const raw = idleValues[s.name];
                        const value = Number(raw);
                        if (!Number.isInteger(value) || value < 1 || value > 1440) {
                          setFeedback({ ok: false, text: "空闲阈值需为 1~1440 的整数" });
                          return;
                        }
                        submit(
                          { [`systems.${s.name}.max_idle_minutes`]: value },
                          `将 ${s.name} 空闲阈值改为 ${value} 分钟`,
                        );
                      }}
                      className="px-2.5 py-1 text-xs rounded-md border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40"
                    >
                      保存
                    </button>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    disabled={!writeEnabled || pending !== null}
                    onClick={() =>
                      submit(
                        { [`systems.${s.name}.enabled`]: !s.enabled },
                        `${s.enabled ? "停用" : "启用"}监控 ${s.name}`,
                      )
                    }
                    className={`px-2.5 py-1 text-xs rounded-md border bg-white disabled:opacity-40 disabled:cursor-not-allowed ${
                      s.enabled
                        ? "border-red-200 text-red-600 hover:bg-red-50"
                        : "border-gray-200 text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {pending === `${s.enabled ? "停用" : "启用"}监控 ${s.name}`
                      ? "处理中…"
                      : s.enabled
                        ? "停用"
                        : "启用"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
