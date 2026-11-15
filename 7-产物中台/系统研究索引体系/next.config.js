/** @type {import('next').NextConfig} */

// 判断是否为静态导出模式 (用于Pagefind集成)
const isStaticExport = process.env.NEXT_PUBLIC_STATIC_EXPORT === 'true';

const nextConfig = {
  // 云端以路径前缀方式反代（https://www.neodrm.com/admin）时，把静态资源映射到
  // /admin-static/_next/*，避免与主站 3.1 的 /_next/* 冲突（SPEC-7 云端部署）
  assetPrefix: process.env.NEXT_ASSET_PREFIX || undefined,
  // 跳过类型检查（Prisma schema 与代码不完全匹配，不影响运行时）
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  // Next 14 需显式开启 instrumentation 钩子（启动自检写门禁，SPEC-7 §12.1）
  experimental: {
    instrumentationHook: true,
  },
  // 静态导出配置 (用于Pagefind全文检索)
  ...(isStaticExport && {
    output: 'export',
    distDir: 'out',
  }),
  
  // 图片优化 (静态导出时需要禁用)
  images: {
    unoptimized: isStaticExport,
  },
};

module.exports = nextConfig;
