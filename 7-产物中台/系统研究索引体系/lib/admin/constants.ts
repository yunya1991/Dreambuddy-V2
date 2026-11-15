// ============================================================================
// 管理台写能力 · 全局常量（SPEC-7 §5/§6/§8）
// 单一真源：阈值、cookie、门禁、外部服务地址都放这里，禁止散落硬编码
// ============================================================================

/** 管理台独立会话 cookie（与 3.1-FRONTEND 的 authjs 会话完全隔离） */
export const ADMIN_COOKIE_NAME = "dream-admin-session";

/** JWT 会话有效期：8 小时 */
export const ADMIN_SESSION_MAX_AGE_SEC = 8 * 60 * 60;

/** 登录失败锁定沿用 3.1 语义：5 次失败锁定 30 分钟 */
export const ADMIN_LOGIN_MAX_ATTEMPTS = 5;
export const ADMIN_LOGIN_LOCK_MINUTES = 30;

/** 积分调账分档（D3 定稿，不可回退） */
export const CREDITS_ADJUST_L0_MAX = 500;
export const CREDITS_ADJUST_L1_MAX = 5000;
export const CREDITS_ADJUST_DAILY_MAX = 20000;
export const CREDITS_ADJUST_APPROVAL_MAX = 20000;
export const CREDITS_ADJUST_CATEGORY = "BONUS";

/** 积分调账动作标识（opLog.action / confirmToken.action） */
export const CREDITS_ADJUST_ACTION = "credits.adjust";

/**
 * 管理台调账流水描述前缀。
 * 日累计额度依赖它区分「管理台调账」与其他 BONUS 入账，
 * 因为 credits_transactions 没有 writer 字段（不新增表/列）。
 */
export const CREDITS_ADJUST_DESCRIPTION_PREFIX = "管理台调账：";

/** 解锁用户动作标识 */
export const USER_UNLOCK_ACTION = "users.unlock";

/** M1b 动作标识（opLog.action / confirmToken.action / 回滚路由分派） */
export const USER_ROLE_ACTION = "users.role";
export const TRADING_PARAMS_ACTION = "trading-params.update";
export const TRADING_RESET_DAILY_ACTION = "trading-params.reset-daily";
export const STRATEGY_STATUS_ACTION = "strategies.status";
export const TASK_STATUS_ACTION = "tasks.status";
export const CHANNEL_UPDATE_ACTION = "channels.update";
export const API_CONFIG_UPDATE_ACTION = "api-configs.update";
export const ORDER_UPDATE_ACTION = "orders.update";
export const SYSTEM_CONFIG_ACTION = "system-config.update";

/** 文件型配置快照目录（相对仓库根） */
export const ADMIN_BACKUP_DIR = ".admin-backups";

/** monitor 白名单可写叶字段与取值范围 */
export const MONITOR_WRITABLE_LEAVES = ["enabled", "max_idle_minutes"] as const;
export const MONITOR_MAX_IDLE_MINUTES_MIN = 1;
export const MONITOR_MAX_IDLE_MINUTES_MAX = 1440;

/** trailing_stop 白名单可写 key 与取值范围（SPEC-7 §10） */
export const TRAILING_STOP_SECONDS_MIN = 0;
export const TRAILING_STOP_SECONDS_MAX = 86400;
export const TRAILING_STOP_OUTPUT_DIR_MAX_LEN = 200;

/** 回滚动作标识 */
export const ROLLBACK_ACTION = "rollback";

/** 写接口限流：20 次/分钟/actor（进程内，强制 PM2 instances=1） */
export const ADMIN_WRITE_RATE_LIMIT = 20;
export const ADMIN_WRITE_RATE_WINDOW_MS = 60 * 1000;

/** 确认令牌有效期 60 秒 */
export const ADMIN_CONFIRM_TOKEN_TTL_SEC = 60;

/** 外部依赖超时 */
export const ADMIN_BRIDGE_TIMEOUT_MS = 2000;
export const ADMIN_GOVERNANCE_TIMEOUT_MS = 2000;

/** 27 策略治理审批系统 */
export const GOVERNANCE_BASE_URL =
  process.env.GOVERNANCE_BASE_URL || "http://127.0.0.1:8094";

/**
 * 27 审计事件 API 的写权限令牌（对应 27 侧 GOVERNANCE_ADMIN_TOKEN）。
 * 缺失则审计推送必然 403，按失败处理（保留待补偿），不静默降级。
 */
export const ENV_GOVERNANCE_ADMIN_TOKEN = "GOVERNANCE_ADMIN_TOKEN";
export const GOVERNANCE_ADMIN_TOKEN_HEADER = "X-Admin-Token";

/** 审计事件在 27 审计链中的 stage 标识 */
export const GOVERNANCE_AUDIT_STAGE = "admin-write";

/** 内部任务令牌（audit-flush 等内部端点），缺失则内部端点整体拒绝 */
export const ADMIN_INTERNAL_TOKEN_HEADER = "x-internal-token";
export const ENV_ADMIN_INTERNAL_TOKEN = "ADMIN_INTERNAL_TOKEN";

/** 审计补偿单批上限 */
export const ADMIN_AUDIT_FLUSH_BATCH = 50;

/** 文件型配置白名单（SUPERSET，仅 monitor 允许非 L2 写；M2 落地写入器） */
export const ADMIN_FILE_KEYS = {
  monitor: "15-监控告警系统/config/monitor_config.json",
  trailing_stop: "16-调控系统/config/trailing_stop.json",
  capital_control: "16-调控系统/config/capital_control.json",
  capital_allocator: "16-调控系统/config/capital_allocator.json",
} as const;

export type AdminFileKey = keyof typeof ADMIN_FILE_KEYS;

/** 写操作级别 */
export const ADMIN_LEVELS = ["L0", "L1", "L2"] as const;
export type AdminLevel = (typeof ADMIN_LEVELS)[number];

/** 写操作日志状态机 */
export const ADMIN_OP_STATUS = [
  "PENDING_AUDIT",
  "APPLIED",
  "APPLIED_WITH_WARNINGS",
  "FAILED",
  "ROLLED_BACK",
  "PENDING_APPROVAL",
  "REJECTED",
] as const;
export type AdminOpStatus = (typeof ADMIN_OP_STATUS)[number];

/** 实例门禁环境变量名（instrumentation.ts 校验） */
export const ENV_INSTANCE_ROLE = "INSTANCE_ROLE";
export const ENV_ADMIN_WRITE_ENABLED = "ADMIN_WRITE_ENABLED";
export const ENV_ADMIN_ALLOWED_DB_HOSTS = "ADMIN_ALLOWED_DB_HOSTS";
export const ENV_ADMIN_AUTH_SECRET = "ADMIN_AUTH_SECRET";
export const ENV_ADMIN_CONFIRM_SECRET = "ADMIN_CONFIRM_SECRET";
