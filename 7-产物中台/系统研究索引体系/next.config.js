/** @type {import('next').NextConfig} */

// 判断是否为静态导出模式 (用于Pagefind集成)
const isStaticExport = process.env.NEXT_PUBLIC_STATIC_EXPORT === 'true';

const nextConfig = {
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
