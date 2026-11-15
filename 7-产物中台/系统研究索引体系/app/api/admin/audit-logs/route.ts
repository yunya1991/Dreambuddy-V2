// ============================================================================
// GET /api/admin/audit-logs —— 操作审计检索（SPEC-7 §8.3 / §11-4）
// ----------------------------------------------------------------------------
// 只读。支持按 actor/action/target/status/时间范围过滤 + 分页。
// before/after 已在写入时用白名单投影，此处不再二次加工（无密文）。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk, newRequestId } from "@/lib/admin/errors";
import { prisma } from "@/lib/prisma";
import { requireAdmin } from "@/lib/admin/auth";

export const dynamic = "force-dynamic";

const querySchema = z.object({
  actorUid: z.string().optional(),
  action: z.string().optional(),
  targetType: z.string().optional(),
  targetId: z.string().optional(),
  status: z.string().optional(),
  from: z.string().optional(),
  to: z.string().optional(),
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(100).default(20),
});

export async function GET(request: Request) {
  const requestId = newRequestId();
  try {
    await requireAdmin();
    const url = new URL(request.url);
    const parsed = querySchema.safeParse({
      actorUid: url.searchParams.get("actorUid") ?? undefined,
      action: url.searchParams.get("action") ?? undefined,
      targetType: url.searchParams.get("targetType") ?? undefined,
      targetId: url.searchParams.get("targetId") ?? undefined,
      status: url.searchParams.get("status") ?? undefined,
      from: url.searchParams.get("from") ?? undefined,
      to: url.searchParams.get("to") ?? undefined,
      page: url.searchParams.get("page") ?? undefined,
      pageSize: url.searchParams.get("pageSize") ?? undefined,
    });
    if (!parsed.success) {
      throw new AdminError("VALIDATION_FAILED", "查询参数不合法", {
        issues: parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
      });
    }

    const { page, pageSize, from, to, ...filters } = parsed.data;
    const where: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(filters)) {
      if (value) where[key] = value;
    }
    if (from || to) {
      const createdAt: Record<string, Date> = {};
      if (from) createdAt.gte = new Date(from);
      if (to) createdAt.lte = new Date(to);
      where.createdAt = createdAt;
    }

    const [items, total] = await Promise.all([
      prisma.adminOperationLog.findMany({
        where,
        orderBy: { createdAt: "desc" },
        skip: (page - 1) * pageSize,
        take: pageSize,
      }),
      prisma.adminOperationLog.count({ where }),
    ]);

    return apiOk(
      {
        items,
        total,
        page,
        pageSize,
        totalPages: Math.max(1, Math.ceil(total / pageSize)),
      },
      { requestId, message: "ok" },
    );
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
