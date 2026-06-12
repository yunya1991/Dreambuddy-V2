import { getPrisma } from "./prisma-data-hub";

// ============================================================================
// 工具函数
// ============================================================================

function safeDate(v: any): string {
  if (!v) return "";
  try {
    return new Date(v).toISOString();
  } catch {
    return "";
  }
}

function getFieldOrDefault(obj: any, field: string, def: any = null): any {
  if (!obj) return def;
  if (obj[field] !== undefined && obj[field] !== null) return obj[field];
  return def;
}

// ============================================================================
// 用户列表
// ============================================================================

export interface AdminUserListItem {
  uid: string;
  email: string;
  displayName: string;
  emailVerified: boolean;
  createdAt: string;
  lastLoginAt: string | null;
  strategyCount: number;
  apiConfigCount: number;
}

export async function getAdminUserList(
  page: number,
  pageSize: number,
  search?: string,
): Promise<{ items: AdminUserListItem[]; total: number }> {
  const db = getPrisma();

  const where: any = {};
  if (search) {
    where.OR = [
      { email: { contains: search, mode: "insensitive" as const } },
      { displayName: { contains: search, mode: "insensitive" as const } },
    ];
  }

  const [users, total] = await Promise.all([
    (db.user as any).findMany({
      where: Object.keys(where).length > 0 ? where : undefined,
      skip: (page - 1) * pageSize,
      take: pageSize,
      orderBy: { createdAt: "desc" as const },
    }),
    (db.user as any).count({ where: Object.keys(where).length > 0 ? where : undefined }),
  ]);

  const uids = users.map((u: any) => u.uid);
  const [strategyCounts, apiConfigCounts] = await Promise.all([
    safeGroupCount(db, "strategy", "uid", uids),
    safeGroupCount(db, "apiConfig", "uid", uids),
  ]);

  const items: AdminUserListItem[] = users.map((u: any) => ({
    uid: u.uid,
    email: u.email || "—",
    displayName: u.displayName || u.email?.split("@")[0] || "未设置",
    emailVerified: u.emailVerified || false,
    createdAt: safeDate(u.createdAt),
    lastLoginAt: u.lastLoginAt ? safeDate(u.lastLoginAt) : null,
    strategyCount: strategyCounts[u.uid] || 0,
    apiConfigCount: apiConfigCounts[u.uid] || 0,
  }));

  return { items, total };
}

// ============================================================================
// 用户详情
// ============================================================================

export interface AdminUserDetail {
  uid: string;
  email: string;
  displayName: string;
  emailVerified: boolean;
  createdAt: string;
  lastLoginAt: string | null;
  strategies: { id: string; name: string; status: string; type: string }[];
  strategyCount: number;
  apiConfigCount: number;
  totalExecutions: number;
}

export async function getAdminUserDetail(
  uid: string,
): Promise<AdminUserDetail | null> {
  const db = getPrisma();

  const user = await safeFind(db, "user", { where: { uid } });
  if (!user) return null;

  const strategies = await safeFindMany(db, "strategy", {
    where: { uid },
    orderBy: { createdAt: "desc" as const },
  });

  const strategyIds = strategies.map((s: any) => s.id);
  const [apiConfigCount, executionCount] = await Promise.all([
    safeCount(db, "apiConfig", { where: { uid } }),
    strategyIds.length > 0
      ? safeCount(db, "strategyExecutionRun", { where: { strategyId: { in: strategyIds } } })
      : 0,
  ]);

  return {
    uid: user.uid,
    email: user.email || "—",
    displayName: user.displayName || user.email?.split("@")[0] || "未设置",
    emailVerified: user.emailVerified || false,
    createdAt: safeDate(user.createdAt),
    lastLoginAt: user.lastLoginAt ? safeDate(user.lastLoginAt) : null,
    strategies: strategies.map((s: any) => ({
      id: s.id,
      name: s.name || "未命名策略",
      status: s.status || "unknown",
      type: s.type || "unknown",
    })),
    strategyCount: strategies.length,
    apiConfigCount,
    totalExecutions: executionCount,
  };
}

// ============================================================================
// 策略列表
// ============================================================================

export interface AdminStrategyListItem {
  id: string;
  uid: string;
  userEmail: string;
  userDisplayName: string;
  name: string;
  type: string;
  status: string;
  description: string | null;
  createdAt: string;
  updatedAt: string;
  taskCount: number;
  executionCount: number;
}

export async function getAdminStrategyList(
  page: number,
  pageSize: number,
  search?: string,
  status?: string,
  type?: string,
  uid?: string,
): Promise<{ items: AdminStrategyListItem[]; total: number }> {
  const db = getPrisma();

  const where: any = {};
  if (status) where.status = status;
  if (type) where.type = type;
  if (uid) where.uid = uid;
  if (search) where.name = { contains: search, mode: "insensitive" as const };

  const [strategies, total] = await Promise.all([
    safeFindMany(db, "strategy", {
      where: Object.keys(where).length > 0 ? where : undefined,
      skip: (page - 1) * pageSize,
      take: pageSize,
      orderBy: { createdAt: "desc" as const },
    }),
    safeCount(db, "strategy", { where: Object.keys(where).length > 0 ? where : undefined }),
  ]);

  // 获取用户信息
  const allUids: string[] = (strategies as any[]).map((s: any) => s.uid).filter(Boolean) as string[];
  const userUids: string[] = [];
  for (const u of allUids) {
    if (userUids.indexOf(u) === -1) userUids.push(u);
  }
  const users = userUids.length > 0
    ? await safeFindMany(db, "user", {
        where: { uid: { in: userUids } },
        select: { uid: true, email: true, displayName: true },
      })
    : [];

  const userMap: Record<string, any> = {};
  for (const u of users) userMap[u.uid] = u;

  const strategyIds = (strategies as any[]).map((s: any) => s.id);
  const [taskCounts, executionCounts] = await Promise.all([
    safeGroupCount(db, "strategyTask", "strategyId", strategyIds),
    safeGroupCount(db, "strategyExecutionRun", "strategyId", strategyIds),
  ]);

  const items: AdminStrategyListItem[] = (strategies as any[]).map((s: any) => ({
    id: s.id,
    uid: s.uid || "",
    userEmail: userMap[s.uid]?.email || "—",
    userDisplayName: userMap[s.uid]?.displayName || userMap[s.uid]?.email || "",
    name: s.name || "未命名策略",
    type: s.type || "unknown",
    status: s.status || "unknown",
    description: s.description || null,
    createdAt: safeDate(s.createdAt),
    updatedAt: safeDate(s.updatedAt || s.createdAt),
    taskCount: taskCounts[s.id] || 0,
    executionCount: executionCounts[s.id] || 0,
  }));

  return { items, total };
}

// ============================================================================
// 策略详情
// ============================================================================

export interface AdminStrategyDetail {
  id: string;
  name: string;
  type: string;
  status: string;
  description: string | null;
  createdAt: string;
  updatedAt: string;
  uid: string;
  userEmail: string;
  userDisplayName: string;
  tasks: { id: string; name: string; status: string; createdAt: string }[];
  taskCount: number;
  executionCount: number;
  metadata: any;
}

export async function getAdminStrategyDetail(
  id: string,
): Promise<AdminStrategyDetail | null> {
  const db = getPrisma();

  const strategy = await safeFind(db, "strategy", { where: { id } });
  if (!strategy) return null;

  const user = strategy.uid ? await safeFind(db, "user", { where: { uid: strategy.uid } }) : null;

  const tasks = await safeFindMany(db, "strategyTask", {
    where: { strategyId: id },
    orderBy: { createdAt: "desc" as const },
  });

  const executionCount = await safeCount(db, "strategyExecutionRun", { where: { strategyId: id } });

  // 抽取可能存在的配置字段
  const metadataFields = ["symbol", "direction", "leverage", "entryPrice", "takeProfit", "stopLoss"];
  const metadata: any = {};
  for (const f of metadataFields) {
    if (strategy[f] !== undefined && strategy[f] !== null) metadata[f] = strategy[f];
  }

  return {
    id: strategy.id,
    name: strategy.name || "未命名策略",
    type: strategy.type || "unknown",
    status: strategy.status || "unknown",
    description: strategy.description || null,
    createdAt: safeDate(strategy.createdAt),
    updatedAt: safeDate(strategy.updatedAt || strategy.createdAt),
    uid: strategy.uid || "",
    userEmail: user?.email || "—",
    userDisplayName: user?.displayName || user?.email || "",
    tasks: (tasks as any[]).map((t: any) => ({
      id: t.id,
      name: t.name || t.description || "未命名任务",
      status: t.status || "unknown",
      createdAt: safeDate(t.createdAt),
    })),
    taskCount: (tasks as any[]).length,
    executionCount,
    metadata: Object.keys(metadata).length > 0 ? metadata : null,
  };
}

// ============================================================================
// 任务列表
// ============================================================================

export interface AdminTaskListItem {
  id: string;
  strategyId: string;
  strategyName: string;
  uid: string;
  userEmail: string;
  userDisplayName: string;
  name: string;
  status: string;
  createdAt: string;
}

export async function getAdminTaskList(
  page: number,
  pageSize: number,
  search?: string,
  status?: string,
): Promise<{ items: AdminTaskListItem[]; total: number }> {
  const db = getPrisma();

  const where: any = {};
  if (status) where.status = status;

  const [tasks, total] = await Promise.all([
    safeFindMany(db, "strategyTask", {
      where: Object.keys(where).length > 0 ? where : undefined,
      skip: (page - 1) * pageSize,
      take: pageSize,
      orderBy: { createdAt: "desc" as const },
    }),
    safeCount(db, "strategyTask", { where: Object.keys(where).length > 0 ? where : undefined }),
  ]);

  const allStrategyIdsFromTasks: string[] = (tasks as any[]).map((t: any) => t.strategyId).filter(Boolean) as string[];
  const strategyIds: string[] = [];
  for (const s of allStrategyIdsFromTasks) {
    if (strategyIds.indexOf(s) === -1) strategyIds.push(s);
  }
  const strategies = strategyIds.length > 0
    ? await safeFindMany(db, "strategy", {
        where: { id: { in: strategyIds } },
        select: { id: true, name: true, uid: true, user: { select: { email: true, displayName: true } } },
      })
    : [];

  const strategyMap: Record<string, any> = {};
  for (const s of strategies) strategyMap[s.id] = s;

  const items: AdminTaskListItem[] = (tasks as any[]).map((t: any) => {
    const strategy = strategyMap[t.strategyId];
    return {
      id: t.id,
      strategyId: t.strategyId,
      strategyName: strategy?.name || "未命名策略",
      uid: strategy?.uid || t.uid || "",
      userEmail: strategy?.user?.email || "—",
      userDisplayName: strategy?.user?.displayName || strategy?.user?.email || "",
      name: t.name || t.description || "未命名任务",
      status: t.status || "unknown",
      createdAt: safeDate(t.createdAt),
    };
  });

  // 如果有搜索，在内存中过滤任务名称
  if (search) {
    const low = search.toLowerCase();
    const filtered = items.filter((i) => i.name.toLowerCase().includes(low));
    return { items: filtered, total: filtered.length };
  }

  return { items, total };
}

// ============================================================================
// 执行记录列表
// ============================================================================

export interface AdminExecutionListItem {
  id: string;
  strategyId: string;
  strategyName: string;
  taskId: string | null;
  status: string;
  createdAt: string;
  executedAt: string | null;
  uid: string;
  userEmail: string;
  userDisplayName: string;
}

export async function getAdminExecutionList(
  page: number,
  pageSize: number,
  search?: string,
  status?: string,
  strategyId?: string,
): Promise<{ items: AdminExecutionListItem[]; total: number }> {
  const db = getPrisma();

  const where: any = {};
  if (status) where.status = status;
  if (strategyId) where.strategyId = strategyId;

  const [runs, total] = await Promise.all([
    safeFindMany(db, "strategyExecutionRun", {
      where: Object.keys(where).length > 0 ? where : undefined,
      skip: (page - 1) * pageSize,
      take: pageSize,
      orderBy: { createdAt: "desc" as const },
    }),
    safeCount(db, "strategyExecutionRun", {
      where: Object.keys(where).length > 0 ? where : undefined,
    }),
  ]);

  const allStrategyIdsFromRuns: string[] = (runs as any[]).map((r: any) => r.strategyId).filter(Boolean) as string[];
  const strategyIds: string[] = [];
  for (const s of allStrategyIdsFromRuns) {
    if (strategyIds.indexOf(s) === -1) strategyIds.push(s);
  }
  const strategies = strategyIds.length > 0
    ? await safeFindMany(db, "strategy", {
        where: { id: { in: strategyIds } },
        select: { id: true, name: true, uid: true, user: { select: { email: true, displayName: true } } },
      })
    : [];

  const strategyMap: Record<string, any> = {};
  for (const s of strategies) strategyMap[s.id] = s;

  const items: AdminExecutionListItem[] = (runs as any[]).map((r: any) => {
    const strategy = strategyMap[r.strategyId];
    return {
      id: r.id,
      strategyId: r.strategyId,
      strategyName: strategy?.name || "未命名策略",
      taskId: r.taskId || null,
      status: r.status || "unknown",
      createdAt: safeDate(r.createdAt),
      executedAt: r.startedAt ? safeDate(r.startedAt) : safeDate(r.createdAt),
      uid: strategy?.uid || r.uid || "",
      userEmail: strategy?.user?.email || "—",
      userDisplayName: strategy?.user?.displayName || strategy?.user?.email || "",
    };
  });

  if (search) {
    const low = search.toLowerCase();
    const filtered = items.filter((i) =>
      (i.strategyName || "").toLowerCase().includes(low) ||
      String(i.id).toLowerCase().includes(low),
    );
    return { items: filtered, total: filtered.length };
  }

  return { items, total };
}

// ============================================================================
// API 配置列表
// ============================================================================

export interface AdminApiConfigListItem {
  id: string;
  uid: string;
  userEmail: string;
  userDisplayName: string;
  category: string;
  provider: string;
  type: string;
  createdAt: string;
}

export async function getAdminApiConfigList(
  page: number,
  pageSize: number,
  search?: string,
): Promise<{ items: AdminApiConfigListItem[]; total: number }> {
  const db = getPrisma();

  const where: any = {};
  if (search) {
    where.OR = [
      { provider: { contains: search, mode: "insensitive" as const } },
      { category: { contains: search, mode: "insensitive" as const } },
    ];
  }

  const [items_raw, total] = await Promise.all([
    safeFindMany(db, "apiConfig", {
      where: Object.keys(where).length > 0 ? where : undefined,
      skip: (page - 1) * pageSize,
      take: pageSize,
      orderBy: { createdAt: "desc" as const },
      include: { user: { select: { email: true, displayName: true } } },
    }),
    safeCount(db, "apiConfig", { where: Object.keys(where).length > 0 ? where : undefined }),
  ]);

  const items: AdminApiConfigListItem[] = (items_raw as any[]).map((c: any) => ({
    id: c.id,
    uid: c.uid,
    userEmail: c.user?.email || "—",
    userDisplayName: c.user?.displayName || c.user?.email || "",
    category: c.category || c.type || "general",
    provider: c.provider || c.exchange || "unknown",
    type: c.type || c.category || "unknown",
    createdAt: safeDate(c.createdAt),
  }));

  return { items, total };
}

// ============================================================================
// 通用聚合查询 - 其他数据汇总（交易参数、渠道、积分、订单等）
// ============================================================================

export interface AdminGenericItem {
  type: string;
  id: string;
  title: string;
  createdAt: string;
}

export async function getAdminGenericList(
  page: number,
  pageSize: number,
  search?: string,
): Promise<{ items: AdminGenericItem[]; total: number }> {
  const db = getPrisma();

  const candidateModels = [
    { name: "tradingParams", display: "交易参数", titleFields: ["symbol", "id"] },
    { name: "channelConfig", display: "渠道配置", titleFields: ["name", "channel", "id"] },
    { name: "creditsAccount", display: "积分账户", titleFields: ["balance", "id"] },
    { name: "creditsTransaction", display: "积分流水", titleFields: ["amount", "id"] },
    { name: "order", display: "充值订单", titleFields: ["amount", "status", "id"] },
  ];

  const allItems: AdminGenericItem[] = [];

  for (const { name, display, titleFields } of candidateModels) {
    try {
      const raw = await safeFindMany(db, name, {
        take: 100,
        orderBy: { createdAt: "desc" as const },
      });
      if (Array.isArray(raw) && raw.length > 0) {
        for (const item of raw) {
          let title = "";
          for (const f of titleFields) {
            if (item[f] !== undefined && item[f] !== null) {
              title += ` ${item[f]}`;
            }
          }
          allItems.push({
            type: display,
            id: item.id,
            title: title.trim().slice(0, 60) || `#${String(item.id).slice(0, 8)}`,
            createdAt: safeDate(item.createdAt),
          });
        }
      }
    } catch {
      // 表不存在，跳过
    }
  }

  allItems.sort((a, b) => (b.createdAt || "").localeCompare(a.createdAt || ""));

  let filtered = allItems;
  if (search) {
    const low = search.toLowerCase();
    filtered = allItems.filter((i) =>
      i.type.toLowerCase().includes(low) ||
      i.title.toLowerCase().includes(low) ||
      String(i.id).toLowerCase().includes(low),
    );
  }

  const start = (page - 1) * pageSize;
  return {
    items: filtered.slice(start, start + pageSize),
    total: filtered.length,
  };
}

// ============================================================================
// 安全辅助函数（防止表不存在报错）
// ============================================================================

async function safeFindMany(db: any, modelName: string, args: any): Promise<any[]> {
  try {
    const model = (db as any)[modelName];
    if (!model || !model.findMany) return [];
    return await model.findMany(args);
  } catch {
    return [];
  }
}

async function safeFind(db: any, modelName: string, args: any): Promise<any | null> {
  try {
    const model = (db as any)[modelName];
    if (!model || !model.findUnique) return null;
    return await model.findUnique(args);
  } catch {
    return null;
  }
}

async function safeCount(db: any, modelName: string, args: any): Promise<number> {
  try {
    const model = (db as any)[modelName];
    if (!model || !model.count) return 0;
    return Number(await model.count(args)) || 0;
  } catch {
    return 0;
  }
}

async function safeGroupCount(
  db: any,
  modelName: string,
  groupField: string,
  ids: string[],
): Promise<Record<string, number>> {
  if (!ids || ids.length === 0) return {};
  try {
    const model = (db as any)[modelName];
    if (!model || !model.groupBy) return {};
    const groups = await model.groupBy({
      by: [groupField],
      where: { [groupField]: { in: ids } },
      _count: { [groupField]: true },
    });
    const result: Record<string, number> = {};
    for (const g of groups) {
      result[g[groupField]] = Number((g._count as any)?.[groupField] || 0);
    }
    return result;
  } catch {
    return {};
  }
}

// ============================================================================
// 渠道配置（旧模型兼容，表不存在则返回空）
// ============================================================================

export interface AdminChannelItem {
  id: string;
  uid?: string;
  userEmail?: string;
  userDisplayName?: string;
  name?: string;
  type?: string;
  provider?: string;
  status?: string;
  createdAt: string;
}

export async function getAdminChannelList(
  page: number,
  pageSize: number,
  search?: string,
): Promise<{ items: AdminChannelItem[]; total: number }> {
  const db = getPrisma();
  const candidateModels = ["channelConfig", "channel"];
  let items: any[] = [];
  let total = 0;
  for (const name of candidateModels) {
    try {
      const model = (db as any)[name];
      if (!model || !model.findMany) continue;
      items = await model.findMany({
        skip: (page - 1) * pageSize,
        take: pageSize,
        orderBy: { createdAt: "desc" as const },
        include: { user: { select: { email: true, displayName: true, uid: true } } },
      });
      total = Number(await model.count()) || 0;
      if (items.length > 0 || total > 0) break;
    } catch {
      // 尝试下一个模型名
    }
  }
  const result: AdminChannelItem[] = items.map((c) => ({
    id: c.id,
    uid: c.uid || c.user?.uid || "",
    userEmail: c.user?.email || "",
    userDisplayName: c.user?.displayName || c.user?.email || "",
    name: c.name || c.channelName || c.channel || "未命名渠道",
    type: c.type || c.category || "",
    provider: c.provider || "",
    status: c.status || "unknown",
    createdAt: safeDate(c.createdAt),
  }));
  if (search) {
    const low = search.toLowerCase();
    const filtered = result.filter(
      (i) =>
        (i.name || "").toLowerCase().includes(low) ||
        (i.userEmail || "").toLowerCase().includes(low) ||
        (i.userDisplayName || "").toLowerCase().includes(low),
    );
    return { items: filtered, total: filtered.length };
  }
  return { items: result, total };
}

// ============================================================================
// 积分账户
// ============================================================================

export interface AdminCreditsItem {
  id: string;
  uid?: string;
  userEmail?: string;
  userDisplayName?: string;
  balance: number;
  createdAt: string;
}

export async function getAdminCreditsList(
  page: number,
  pageSize: number,
  search?: string,
): Promise<{ items: AdminCreditsItem[]; total: number }> {
  const db = getPrisma();
  const candidateModels = ["creditsAccount", "credits"];
  let items: any[] = [];
  let total = 0;
  for (const name of candidateModels) {
    try {
      const model = (db as any)[name];
      if (!model || !model.findMany) continue;
      items = await model.findMany({
        skip: (page - 1) * pageSize,
        take: pageSize,
        orderBy: { createdAt: "desc" as const },
        include: { user: { select: { email: true, displayName: true, uid: true } } },
      });
      total = Number(await model.count()) || 0;
      if (items.length > 0 || total > 0) break;
    } catch {
      // 继续尝试
    }
  }
  const result: AdminCreditsItem[] = items.map((c) => ({
    id: c.id,
    uid: c.uid || c.user?.uid || "",
    userEmail: c.user?.email || "",
    userDisplayName: c.user?.displayName || c.user?.email || "",
    balance: Number(c.balance || c.amount || 0),
    createdAt: safeDate(c.createdAt),
  }));
  if (search) {
    const low = search.toLowerCase();
    const filtered = result.filter(
      (i) =>
        (i.userEmail || "").toLowerCase().includes(low) ||
        (i.userDisplayName || "").toLowerCase().includes(low),
    );
    return { items: filtered, total: filtered.length };
  }
  return { items: result, total };
}

// ============================================================================
// 充值订单
// ============================================================================

export interface AdminOrderItem {
  id: string;
  uid?: string;
  userEmail?: string;
  userDisplayName?: string;
  amount: number;
  status: string;
  createdAt: string;
}

export async function getAdminOrderList(
  page: number,
  pageSize: number,
  search?: string,
): Promise<{ items: AdminOrderItem[]; total: number }> {
  const db = getPrisma();
  const candidateModels = ["order", "creditsOrder", "paymentOrder"];
  let items: any[] = [];
  let total = 0;
  for (const name of candidateModels) {
    try {
      const model = (db as any)[name];
      if (!model || !model.findMany) continue;
      items = await model.findMany({
        skip: (page - 1) * pageSize,
        take: pageSize,
        orderBy: { createdAt: "desc" as const },
        include: { user: { select: { email: true, displayName: true, uid: true } } },
      });
      total = Number(await model.count()) || 0;
      if (items.length > 0 || total > 0) break;
    } catch {
      // 继续尝试
    }
  }
  const result: AdminOrderItem[] = items.map((o) => ({
    id: o.id,
    uid: o.uid || o.user?.uid || "",
    userEmail: o.user?.email || "",
    userDisplayName: o.user?.displayName || o.user?.email || "",
    amount: Number(o.amount || o.price || 0),
    status: o.status || o.paymentStatus || "unknown",
    createdAt: safeDate(o.createdAt),
  }));
  if (search) {
    const low = search.toLowerCase();
    const filtered = result.filter(
      (i) =>
        (i.userEmail || "").toLowerCase().includes(low) ||
        (i.userDisplayName || "").toLowerCase().includes(low) ||
        String(i.id).toLowerCase().includes(low),
    );
    return { items: filtered, total: filtered.length };
  }
  return { items: result, total };
}

// ============================================================================
// 交易参数
// ============================================================================

export interface AdminTradingParamsItem {
  id: string;
  uid?: string;
  userEmail?: string;
  userDisplayName?: string;
  status: string;
  todayTradeCount: number;
  totalTradeCount: number;
  createdAt: string;
}

export async function getAdminTradingParamsList(
  page: number,
  pageSize: number,
  search?: string,
): Promise<{ items: AdminTradingParamsItem[]; total: number }> {
  const db = getPrisma();
  const candidateModels = ["tradingParams", "tradingConfig"];
  let items: any[] = [];
  let total = 0;
  for (const name of candidateModels) {
    try {
      const model = (db as any)[name];
      if (!model || !model.findMany) continue;
      items = await model.findMany({
        skip: (page - 1) * pageSize,
        take: pageSize,
        orderBy: { createdAt: "desc" as const },
        include: { user: { select: { email: true, displayName: true, uid: true } } },
      });
      total = Number(await model.count()) || 0;
      if (items.length > 0 || total > 0) break;
    } catch {
      // 继续尝试
    }
  }
  const result: AdminTradingParamsItem[] = items.map((tp) => ({
    id: tp.id,
    uid: tp.uid || tp.user?.uid || "",
    userEmail: tp.user?.email || "",
    userDisplayName: tp.user?.displayName || tp.user?.email || "",
    status: tp.status || "unknown",
    todayTradeCount: Number(tp.todayTradeCount || tp.dailyTradeCount || 0),
    totalTradeCount: Number(tp.totalTradeCount || tp.tradeCount || 0),
    createdAt: safeDate(tp.createdAt),
  }));
  if (search) {
    const low = search.toLowerCase();
    const filtered = result.filter(
      (i) =>
        (i.userEmail || "").toLowerCase().includes(low) ||
        (i.userDisplayName || "").toLowerCase().includes(low),
    );
    return { items: filtered, total: filtered.length };
  }
  return { items: result, total };
}
