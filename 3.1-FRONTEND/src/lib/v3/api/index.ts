// ============================================
// v3 API 域客户端 — 渐进式拆分入口
// ============================================
// 按业务域拆分 API 调用，逐步替代散乱的 fetch() 调用。
// 每个域客户端基于 api-client.ts 的基础 request 方法封装。

// === 基类 ===
export { ApiClient } from './client';
export { ApiException } from './client';
export type { ApiError } from './client';

// === 已有域客户端 ===
export { taskApi } from './task';
export { chatApi } from './chat';
export { marketApi } from './market';

// === 交易域 ===
export { tradeApi } from './trade';

// === 配置管理域 ===
export { configApi } from './config';

// === 用户域 ===
export { userApi } from './user';

// === 研报域 ===
export { reportsApi } from './reports';

// === 监控域 ===
export { monitorApi } from './monitor';

// === 意图识别域 ===
export { intentApi } from './intent';

// === 笔记本域 ===
export { notebookApi } from './notebook';

// === 运维域 ===
export { opsApi } from './ops';

// === 编排域 ===
export { orchestrateApi } from './orchestrate';

// === 链路产物域 ===
export { chainApi } from './chain';

// === 治理域 ===
export { boardApi } from './board';

// === 基本面域 ===
export { fundamentalApi } from './fundamental';

// === 消息流域 ===
export { feedApi } from './feed';

// === 认证域 ===
export { authApi } from './auth';
export { AUTH_PROVIDERS } from './auth';
export { AUTH_BASE_PATH } from './auth';

// === 产物文件域 ===
export { artifactApi } from './artifact';

// === 注册域 ===
export { registerApi } from './register';
