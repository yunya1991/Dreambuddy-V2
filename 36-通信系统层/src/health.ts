/**
 * 36-通信系统层 - Hermes 健康检查
 * 职责：探测模型端点连通性，维护降级标记
 * 依据 SPEC.md v1.0 第 5.2 节
 */

/** 模型端点（与 Hermes config.yaml 的 base_url 一致） */
const MODEL_HEALTH_URL =
  process.env.MODEL_HEALTH_URL ||
  'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/models';

/** 探测间隔（ms） */
const PROBE_INTERVAL_MS = 60 * 1000;
/** 请求超时（ms） */
const PROBE_TIMEOUT_MS = 5 * 1000;
/** 连续失败次数阈值 → 标记降级 */
const FAIL_THRESHOLD = 2;

interface HealthState {
  healthy: boolean;
  consecutiveFails: number;
  lastProbeAt: number;
  lastError?: string;
  degradedAt?: number;
  recoveredAt?: number;
  /** 降级/恢复时的回调（用于发送 system_notice） */
  onStateChange?: (healthy: boolean) => void;
}

const state: HealthState = {
  healthy: true,
  consecutiveFails: 0,
  lastProbeAt: 0,
};

/** 单次探测：HEAD 请求模型端点 */
async function probeOnce(): Promise<{ ok: boolean; error?: string }> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
    const res = await fetch(MODEL_HEALTH_URL, {
      method: 'HEAD',
      signal: controller.signal,
    });
    clearTimeout(timer);
    // 任何 HTTP 响应（含 401/403）都说明网络可达；仅连接层失败视为不健康
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'probe failed' };
  }
}

/** 执行一次探测并更新状态（供定时器与手动触发） */
export async function runProbe(): Promise<HealthState> {
  const result = await probeOnce();
  state.lastProbeAt = Date.now();

  if (result.ok) {
    state.consecutiveFails = 0;
    state.lastError = undefined;
    if (!state.healthy) {
      state.healthy = true;
      state.recoveredAt = Date.now();
      state.onStateChange?.(true);
    }
  } else {
    state.consecutiveFails++;
    state.lastError = result.error;
    if (state.healthy && state.consecutiveFails >= FAIL_THRESHOLD) {
      state.healthy = false;
      state.degradedAt = Date.now();
      state.onStateChange?.(false);
    }
  }
  return { ...state };
}

/** 查询当前健康状态 */
export function getHealthState(): HealthState {
  return { ...state };
}

/** 注册状态变更回调（降级/恢复时触发） */
export function onHealthStateChange(cb: (healthy: boolean) => void): void {
  state.onStateChange = cb;
}

/** 启动周期探测（幂等：重复调用不产生多个定时器） */
let timer: ReturnType<typeof setInterval> | null = null;
export function startHealthMonitor(): void {
  if (timer) return;
  timer = setInterval(() => {
    runProbe().catch(() => {
      // 探测本身异常不中断监控
    });
  }, PROBE_INTERVAL_MS);
  // 启动时立即探测一次
  runProbe().catch(() => {});
}

/** 停止周期探测（测试用） */
export function stopHealthMonitor(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}
