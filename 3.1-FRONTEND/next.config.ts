import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
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
    ];
  },
};

export default nextConfig;
