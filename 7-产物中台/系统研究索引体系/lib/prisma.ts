// ============================================================================
// Prisma 单例（管理台写路径唯一入口）
// ----------------------------------------------------------------------------
// 约束（SPEC-7 §12.3）：
//   1. 全进程单例，避免 Next 热更新 / 多模块重复 new PrismaClient 造成连接泄漏
//   2. 连接池上限 5（管理台与 3.1 共用业务库，必须压低占用）
//   3. 禁止 prisma migrate / db push（库存在 drift），仅 npx prisma generate
// ============================================================================

import { PrismaClient } from "@prisma/client";

const CONNECTION_LIMIT = 5;

function buildDatasourceUrl(): string | undefined {
  const raw = process.env.DATABASE_URL;
  if (!raw) return undefined;
  if (/[?&]connection_limit=/.test(raw)) return raw;
  return `${raw}${raw.includes("?") ? "&" : "?"}connection_limit=${CONNECTION_LIMIT}`;
}

const globalForPrisma = globalThis as unknown as {
  __adminPrisma?: PrismaClient;
};

export const prisma: PrismaClient =
  globalForPrisma.__adminPrisma ??
  new PrismaClient({
    log: [],
    datasourceUrl: buildDatasourceUrl(),
  });

// 开发模式保留全局缓存，避免 HMR 反复创建连接池
if (process.env.NODE_ENV !== "production") {
  globalForPrisma.__adminPrisma = prisma;
}
