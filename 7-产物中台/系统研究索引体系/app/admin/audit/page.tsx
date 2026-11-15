// ============================================================================
// 操作审计页（SPEC-7 §11-4 / M1a）
// 数据检索 + 回滚 + 待补偿计数；27 审计链校验在 M4 接入。
// ============================================================================

import { prisma } from "@/lib/prisma";
import { evaluateWriteGate } from "@/lib/admin/gate";
import { AuditLogsBoard } from "@/components/admin/write/AuditLogsBoard";

export const dynamic = "force-dynamic";

async function readPendingAuditCount(): Promise<number | null> {
  try {
    return await prisma.adminOperationLog.count({
      where: { auditFlushedAt: null, status: { notIn: ["REJECTED", "FAILED"] } },
    });
  } catch {
    // 表不存在（DDL 未执行）时不阻塞页面
    return null;
  }
}

export default async function AdminAuditPage() {
  const gate = evaluateWriteGate();
  const pendingAudit = await readPendingAuditCount();

  return (
    <div className="p-6">
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-gray-900">操作审计</h1>
        <p className="text-sm text-gray-500 mt-1">
          管理台所有写操作的留痕、回滚与下游同步状态（SPEC-7 §9）
        </p>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-3">
          <div className="text-xs text-gray-500">待补偿审计（未推送 27）</div>
          <div className="mt-1 text-xl font-semibold text-gray-900">
            {pendingAudit === null ? "—" : pendingAudit}
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-3">
          <div className="text-xs text-gray-500">写能力</div>
          <div
            className={`mt-1 text-xl font-semibold ${
              gate.enabled ? "text-green-700" : "text-amber-700"
            }`}
          >
            {gate.enabled ? "已启用" : "只读"}
          </div>
          {!gate.enabled ? (
            <div className="mt-1 text-[11px] text-amber-700">{gate.reasons.join("；")}</div>
          ) : null}
        </div>
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-3">
          <div className="text-xs text-gray-500">补偿任务</div>
          <div className="mt-1 text-xs text-gray-700">
            POST /api/admin/jobs/audit-flush（每分钟）
          </div>
        </div>
      </div>

      <AuditLogsBoard writeEnabled={gate.enabled} />
    </div>
  );
}
