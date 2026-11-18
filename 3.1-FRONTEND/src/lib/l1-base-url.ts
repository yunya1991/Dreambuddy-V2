/**
 * L1 同实例接口基址。
 *
 * 优先显式配置 L1_INTERNAL_BASE_URL；未配置时用当前进程实际监听端口
 * （Next 启动时会把 `-p` 端口写入 process.env.PORT），避免本地用 3100
 * 等非 3001 端口运行时自调用打到空端口导致 "fetch failed"。
 */
export function l1BaseUrl(): string {
  const explicit = process.env.L1_INTERNAL_BASE_URL?.trim();
  if (explicit) return explicit;
  const port = process.env.PORT?.trim() || "3001";
  return `http://127.0.0.1:${port}`;
}
