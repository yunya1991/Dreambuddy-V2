import type { PrismaClient } from "@prisma/client";
import type { NextRequest } from "next/server";

export const DEMO_UID = "Ur6GZTRLpum";
export const DEMO_EMAIL = "demo.strategy.local@example.com";
export const DEMO_DISPLAY_NAME = "测试用户";

type UserRecord = {
  uid: string;
  email: string;
  displayName?: string | null;
};

type MinimalPrisma = Pick<PrismaClient, "user">;

type EnsureDemoUserFn = (prisma: MinimalPrisma) => Promise<Pick<UserRecord, "uid">>;

type GetDevelopmentUidInput = {
  request?: Pick<NextRequest, "headers"> | { headers?: { get(name: string): string | null } };
  prisma: MinimalPrisma;
  explicitUid?: string | null;
  ensureDemoUser?: EnsureDemoUserFn;
};

export async function ensureDemoUser(prisma: MinimalPrisma): Promise<UserRecord> {
  const existing = await prisma.user.findUnique({
    where: { uid: DEMO_UID },
    select: {
      uid: true,
      email: true,
      displayName: true,
    },
  });

  if (existing) {
    return existing;
  }

  return prisma.user.create({
    data: {
      uid: DEMO_UID,
      email: DEMO_EMAIL,
      passwordHash: "dev-local-password-hash",
      displayName: DEMO_DISPLAY_NAME,
    },
    select: {
      uid: true,
      email: true,
      displayName: true,
    },
  });
}

export async function getDevelopmentUid({
  request,
  prisma,
  explicitUid,
  ensureDemoUser: ensureDemoUserOverride = ensureDemoUser,
}: GetDevelopmentUidInput): Promise<string> {
  const normalizedExplicitUid = explicitUid?.trim() || request?.headers?.get("x-uid")?.trim();
  if (normalizedExplicitUid) {
    return normalizedExplicitUid;
  }

  const demoUser = await ensureDemoUserOverride(prisma);
  return demoUser.uid;
}
