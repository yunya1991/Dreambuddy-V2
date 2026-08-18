import test from "node:test";
import assert from "node:assert/strict";

import {
  DEMO_DISPLAY_NAME,
  DEMO_EMAIL,
  DEMO_UID,
  ensureDemoUser,
  getDevelopmentUid,
} from "../src/lib/dev-user";
import * as apiKeysRouteModule from "../src/app/api/config/api-keys/route";
import {
  resolveApiKeysRouteUid,
  resolveApiKeysTestRouteUid,
  resolveChannelsRouteUid,
  resolveChannelTestRouteUid,
  resolveStrategiesRouteUid,
  resolveStrategyApplyRouteUid,
  resolveStrategyPauseRouteUid,
  resolveTradeBalanceRouteUid,
  resolveTradingParamsPauseRouteUid,
  resolveTradingParamsResetDailyRouteUid,
  resolveTradingParamsResumeRouteUid,
  resolveTradingParamsRouteUid,
  resolveUserCheckinRouteUid,
} from "../src/lib/development-route-uids";

test("route modules keep only Next.js route exports", () => {
  assert.equal("resolveApiKeysRouteUid" in apiKeysRouteModule, false);
});

test("ensureDemoUser creates the demo user when it does not exist", async () => {
  const calls: unknown[] = [];
  const prisma = {
    user: {
      findUnique: async ({ where }: { where: { uid: string } }) => {
        calls.push(["findUnique", where.uid]);
        return null;
      },
      create: async ({ data }: { data: Record<string, unknown> }) => {
        calls.push(["create", data]);
        return data;
      },
    },
  };

  const user = await ensureDemoUser(prisma as never);

  assert.equal(user.uid, DEMO_UID);
  assert.equal(user.email, DEMO_EMAIL);
  assert.equal(user.displayName, DEMO_DISPLAY_NAME);
  assert.deepEqual(calls, [
    ["findUnique", DEMO_UID],
    [
      "create",
      {
        uid: DEMO_UID,
        email: DEMO_EMAIL,
        passwordHash: "dev-local-password-hash",
        displayName: DEMO_DISPLAY_NAME,
      },
    ],
  ]);
});

test("ensureDemoUser reuses the existing demo user without creating again", async () => {
  const existing = {
    uid: DEMO_UID,
    email: DEMO_EMAIL,
    displayName: DEMO_DISPLAY_NAME,
  };

  let createCalled = false;
  const prisma = {
    user: {
      findUnique: async () => existing,
      create: async () => {
        createCalled = true;
        return existing;
      },
    },
  };

  const user = await ensureDemoUser(prisma as never);

  assert.deepEqual(user, existing);
  assert.equal(createCalled, false);
});

test("getDevelopmentUid prefers explicit header uid and skips demo fallback", async () => {
  let ensureCalled = false;
  const uid = await getDevelopmentUid({
    request: {
      headers: {
        get(name: string) {
          return name === "x-uid" ? "U_real_user_001" : null;
        },
      },
    } as never,
    prisma: {} as never,
    ensureDemoUser: async () => {
      ensureCalled = true;
      throw new Error("should not run");
    },
  });

  assert.equal(uid, "U_real_user_001");
  assert.equal(ensureCalled, false);
});

test("getDevelopmentUid falls back to ensured demo uid when no explicit uid exists", async () => {
  let ensureCalled = false;
  const uid = await getDevelopmentUid({
    request: {
      headers: {
        get() {
          return null;
        },
      },
    } as never,
    prisma: {} as never,
    ensureDemoUser: async () => {
      ensureCalled = true;
      return { uid: DEMO_UID };
    },
  });

  assert.equal(uid, DEMO_UID);
  assert.equal(ensureCalled, true);
});

test("getDevelopmentUid prefers injected explicit uid before demo fallback", async () => {
  let ensureCalled = false;
  const uid = await getDevelopmentUid({
    request: {
      headers: {
        get() {
          return null;
        },
      },
    } as never,
    prisma: {} as never,
    explicitUid: "U_session_user_001",
    ensureDemoUser: async () => {
      ensureCalled = true;
      return { uid: DEMO_UID };
    },
  });

  assert.equal(uid, "U_session_user_001");
  assert.equal(ensureCalled, false);
});

test("strategies route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveStrategiesRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_strategy_001";
    },
  });

  assert.equal(uid, "U_route_strategy_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("strategy apply route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveStrategyApplyRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_apply_001";
    },
  });

  assert.equal(uid, "U_route_apply_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("strategy pause route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveStrategyPauseRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_pause_001";
    },
  });

  assert.equal(uid, "U_route_pause_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("trading params route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveTradingParamsRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_trading_params_001";
    },
  });

  assert.equal(uid, "U_route_trading_params_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("trading params pause route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveTradingParamsPauseRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_trading_params_pause_001";
    },
  });

  assert.equal(uid, "U_route_trading_params_pause_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("trading params resume route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveTradingParamsResumeRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_trading_params_resume_001";
    },
  });

  assert.equal(uid, "U_route_trading_params_resume_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("trading params reset daily route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveTradingParamsResetDailyRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_trading_params_reset_001";
    },
  });

  assert.equal(uid, "U_route_trading_params_reset_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("channels route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveChannelsRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_channels_001";
    },
  });

  assert.equal(uid, "U_route_channels_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("channel test route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveChannelTestRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_channel_test_001";
    },
  });

  assert.equal(uid, "U_route_channel_test_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("api keys route resolves uid through getDevelopmentUid and keeps explicit uid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveApiKeysRouteUid(request, {
    prisma,
    auth: async () => ({ user: { id: "U_session_api_001" } }),
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_api_keys_001";
    },
  });

  assert.equal(uid, "U_route_api_keys_001");
  assert.deepEqual(calls, [
    {
      request,
      prisma,
      explicitUid: "U_session_api_001",
    },
  ]);
});

test("api keys test route resolves uid through getDevelopmentUid and keeps explicit uid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveApiKeysTestRouteUid(request, {
    prisma,
    auth: async () => ({ user: { id: "U_session_api_test_001" } }),
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_api_keys_test_001";
    },
  });

  assert.equal(uid, "U_route_api_keys_test_001");
  assert.deepEqual(calls, [
    {
      request,
      prisma,
      explicitUid: "U_session_api_test_001",
    },
  ]);
});

test("user checkin route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveUserCheckinRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_checkin_001";
    },
  });

  assert.equal(uid, "U_route_checkin_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});

test("trade balance route resolves uid through getDevelopmentUid", async () => {
  const request = { headers: { get: () => null } } as never;
  const prisma = { user: {} } as never;
  const calls: unknown[] = [];

  const uid = await resolveTradeBalanceRouteUid(request, {
    prisma,
    getDevelopmentUid: async (input) => {
      calls.push(input);
      return "U_route_trade_balance_001";
    },
  });

  assert.equal(uid, "U_route_trade_balance_001");
  assert.deepEqual(calls, [{ request, prisma }]);
});
