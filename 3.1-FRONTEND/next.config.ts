import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  experimental: {
    serverActions: {
      bodySizeLimit: "2mb",
    },
  },
  async rewrites() {
    return [
      // 交易榜单 API 代理到 7-产物中台 (3456)
      {
        source: "/api/trading-ranking/:path*",
        destination: "http://localhost:3456/api/trading-ranking/:path*",
      },
      // 经典系统模块化服务代理 (M25-M28)
      // 前端浏览器端通过相对路径 /api/m2X/* 访问，由 Next.js 服务端代理到本机端口
      { source: "/api/m25/:path*", destination: "http://127.0.0.1:8095/:path*" },
      { source: "/api/m26/:path*", destination: "http://127.0.0.1:8093/:path*" },
      { source: "/api/m27/:path*", destination: "http://127.0.0.1:8094/:path*" },
      { source: "/api/m28/:path*", destination: "http://127.0.0.1:8096/:path*" },
    ];
  },
};

export default nextConfig;
