import Link from "next/link";
import { AdminTopBar } from "@/components/admin/AdminTopBar";
import {
  MonitorConfigEditor,
  type MonitorSystemRow,
} from "@/components/admin/write/MonitorConfigEditor";
import {
  TrailingStopConfigEditor,
  type TrailingStopValues,
} from "@/components/admin/write/TrailingStopConfigEditor";
import { evaluateWriteGate } from "@/lib/admin/gate";
import { readConfigFile } from "@/lib/admin/write/file-config";

export const dynamic = "force-dynamic";

type ActiveFile = "monitor" | "trailing_stop";

const TABS: Array<{ key: ActiveFile; label: string; href: string; hint: string }> = [
  {
    key: "monitor",
    label: "监控开关",
    href: "/admin/system-config",
    hint: "在线生效（下一轮 ≤60 分钟，无需重启）",
  },
  {
    key: "trailing_stop",
    label: "移动止损",
    href: "/admin/system-config?file=trailing_stop",
    hint: "写入后需重启下游执行侧服务",
  },
];

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

export default async function AdminSystemConfigPage({
  searchParams,
}: {
  searchParams?: { file?: string };
}) {
  const writeEnabled = evaluateWriteGate().enabled;
  const active: ActiveFile = searchParams?.file === "trailing_stop" ? "trailing_stop" : "monitor";
  const activeTab = TABS.find((tab) => tab.key === active) ?? TABS[0];

  let systems: MonitorSystemRow[] = [];
  let monitorMtimeMs = 0;
  let monitorError = "";

  let trailing: TrailingStopValues | null = null;
  let trailingMtimeMs = 0;
  let trailingError = "";

  if (active === "monitor") {
    try {
      const snapshot = await readConfigFile("monitor");
      monitorMtimeMs = snapshot.mtimeMs;
      const raw = (snapshot.data.systems || {}) as Record<string, unknown>;
      systems = Object.entries(raw).map(([name, value]) => {
        const config = (value || {}) as Record<string, unknown>;
        return {
          name,
          enabled: Boolean(config.enabled),
          maxIdleMinutes: numberOrNull(config.max_idle_minutes),
        };
      });
    } catch (error) {
      monitorError = error instanceof Error ? error.message : String(error);
    }
  } else {
    try {
      const snapshot = await readConfigFile("trailing_stop");
      trailingMtimeMs = snapshot.mtimeMs;
      const report = (snapshot.data.report || {}) as Record<string, unknown>;
      trailing = {
        triggerCooldownSec: numberOrNull(snapshot.data.trigger_cooldown_sec),
        autoCloseAfterSec: numberOrNull(snapshot.data.auto_close_after_sec),
        reportEnabled: Boolean(report.enabled),
        reportOutputDir: typeof report.output_dir === "string" ? report.output_dir : "",
      };
    } catch (error) {
      trailingError = error instanceof Error ? error.message : String(error);
    }
  }

  return (
    <>
      <AdminTopBar title="系统配置" subtitle={`文件型配置 · ${activeTab.hint}`} />
      <main className="p-6 flex-1 space-y-4">
        <nav className="flex gap-2">
          {TABS.map((tab) => (
            <Link
              key={tab.key}
              href={tab.href}
              className={`px-3 py-1.5 text-sm rounded-md border ${
                tab.key === active
                  ? "border-blue-200 bg-blue-50 text-blue-700"
                  : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              {tab.label}
            </Link>
          ))}
        </nav>

        {active === "monitor" ? (
          monitorError ? (
            <div className="px-4 py-3 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg">
              读取 monitor_config.json 失败：{monitorError}
            </div>
          ) : (
            <>
              <div className="text-xs text-gray-500">
                配置来源：<span className="font-mono">15-监控告警系统/config/monitor_config.json</span>
                <span className="ml-3">
                  mtime：{monitorMtimeMs ? new Date(monitorMtimeMs).toLocaleString() : "—"}
                </span>
                <span className="ml-3">写入前自动快照到 .admin-backups/</span>
              </div>
              <MonitorConfigEditor
                systems={systems}
                mtimeMs={monitorMtimeMs}
                writeEnabled={writeEnabled}
              />
            </>
          )
        ) : trailingError || !trailing ? (
          <div className="px-4 py-3 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg">
            读取 trailing_stop.json 失败：{trailingError}
          </div>
        ) : (
          <>
            <div className="text-xs text-gray-500">
              配置来源：<span className="font-mono">16-调控系统/config/trailing_stop.json</span>
              <span className="ml-3">
                mtime：{trailingMtimeMs ? new Date(trailingMtimeMs).toLocaleString() : "—"}
              </span>
              <span className="ml-3">写入前自动快照到 .admin-backups/</span>
            </div>
            <TrailingStopConfigEditor
              values={trailing}
              mtimeMs={trailingMtimeMs}
              writeEnabled={writeEnabled}
            />
          </>
        )}
      </main>
    </>
  );
}
