import type { NextRequest } from "next/server";

import { auth } from "@/lib/auth";
import { getDevelopmentUid } from "@/lib/dev-user";
import { prisma } from "@/lib/prisma";

type DevelopmentUidDeps = {
  prisma: typeof prisma;
  getDevelopmentUid: typeof getDevelopmentUid;
};

type AuthDevelopmentUidDeps = DevelopmentUidDeps & {
  auth: typeof auth;
};

async function resolveDevelopmentUid(
  request: Pick<NextRequest, "headers"> | undefined,
  deps: DevelopmentUidDeps,
): Promise<string> {
  return deps.getDevelopmentUid({ request, prisma: deps.prisma });
}

async function resolveAuthenticatedDevelopmentUid(
  request: NextRequest,
  deps: AuthDevelopmentUidDeps,
): Promise<string> {
  let explicitUid: string | null = null;

  try {
    const session = await deps.auth();
    explicitUid = session?.user?.id?.trim() || null;
  } catch {}

  return deps.getDevelopmentUid({
    request,
    prisma: deps.prisma,
    explicitUid,
  });
}

export async function resolveStrategiesRouteUid(
  request?: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveStrategyApplyRouteUid(
  request: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveStrategyPauseRouteUid(
  request: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveTradingParamsRouteUid(
  request?: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveTradingParamsPauseRouteUid(
  request: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveTradingParamsResumeRouteUid(
  request: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveTradingParamsResetDailyRouteUid(
  request: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveChannelsRouteUid(
  request?: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveChannelTestRouteUid(
  request: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveApiKeysRouteUid(
  request: NextRequest,
  deps: AuthDevelopmentUidDeps = { prisma, auth, getDevelopmentUid },
): Promise<string> {
  return resolveAuthenticatedDevelopmentUid(request, deps);
}

export async function resolveApiKeysTestRouteUid(
  request: NextRequest,
  deps: AuthDevelopmentUidDeps = { prisma, auth, getDevelopmentUid },
): Promise<string> {
  return resolveAuthenticatedDevelopmentUid(request, deps);
}

export async function resolveUserCheckinRouteUid(
  request?: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}

export async function resolveTradeBalanceRouteUid(
  request?: NextRequest,
  deps: DevelopmentUidDeps = { prisma, getDevelopmentUid },
): Promise<string> {
  return resolveDevelopmentUid(request, deps);
}
