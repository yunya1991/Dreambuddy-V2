import { AdminTopBar } from "@/components/admin/AdminTopBar";
import {
  MonitorConfigEditor,
  type MonitorSystemRow,
} from "@/components/admin/write/MonitorConfigEditor";
import { evaluateWriteGate } from "@/lib/admin/gate";
import { readConfigFile } from "@/lib/admin/write/file-config";

export const dynamic = "force-dynamic";

export default async function AdminSystemConfigPage() {
  const writeEnabled = evaluateWriteGate().enabled;

  let systems: MonitorSystemRow[] = [];
  let mtimeMs = 0;
  let loadError = "";

  try {
    const snapshot = await readConfigFile("monitor");
    mtimeMs = snapshot.mtimeMs;
    const raw = (snapshot.data.systems || {}) as Record<string, unknown>;
    systems = Object.entries(raw).map(([name, value]) => {
      const config = (value || {}) as Record<string, unknown>;
      return {
        name,
        enabled: Boolean(config.enabled),
        maxIdleMinutes:
          typeof config.max_idle_minutes === "number" ? config.max_idle_minutes : null,
      };
    });
  } catch (error) {
    loadError = error instanceof Error ? error.message : String(error);
  }

  return (
    <>
      <AdminTopBar
        title="系统配置"
        subtitle="监控开关与空闲阈值 · 在线生效（下一轮 ≤60 分钟，无需重启）"
      />
      <main className="p-6 flex-1 space-y-4">
        {loadError ? (
          <div className="px-4 py-3 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg">
            读取 monitor_config.json 失败：{loadError}
          </div>
        ) : (
          <>
            <div className="text-xs text-gray-500">
              配置来源：<span className="font-mono">15-监控告警系统/config/monitor_config.json</span>
              <span className="ml-3">mtime：{mtimeMs ? new Date(mtimeMs).toLocaleString() : "—"}</span>
              <span className="ml-3">写入前自动快照到 .admin-backups/</span>
            </div>
            <MonitorConfigEditor systems={systems} mtimeMs={mtimeMs} writeEnabled={writeEnabled} />
          </>
        )}
      </main>
    </>
  );
}
