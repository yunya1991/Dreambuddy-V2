// ============================================================================
// PM2 进程配置（SPEC-7 §12.3）
// 硬约束：
//   - instances 必须为 1：限流、Idempotency-Key 去重都依赖单进程内存
//   - max_memory_restart 600M：Next.js 生产模式常驻内存上限
//   - 不再使用 next dev（dev 模式常驻 300-800MB，云端不可接受）
// ============================================================================

module.exports = {
  apps: [
    {
      name: process.env.PM2_APP_NAME || "product-hub",
      cwd: __dirname,
      script: "node_modules/next/dist/bin/next",
      args: `start -p ${process.env.PORT || 3456}`,
      instances: 1,
      exec_mode: "fork",
      max_memory_restart: "600M",
      autorestart: true,
      env: {
        NODE_ENV: "production",
        // 写门禁三要素（云端部署时通过 shell 环境变量覆盖）
        INSTANCE_ROLE: process.env.INSTANCE_ROLE || "local",
        ADMIN_WRITE_ENABLED: process.env.ADMIN_WRITE_ENABLED || "0",
      },
    },
  ],
};
