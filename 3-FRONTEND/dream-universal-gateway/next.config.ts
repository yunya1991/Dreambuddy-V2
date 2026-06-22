import path from "path";
import type { NextConfig } from "next";

const graphCompressorRoot = path.join(__dirname, "../../../6-图结构上下文压缩");

const nextConfig: NextConfig = {
  outputFileTracingRoot: path.join(__dirname),
  serverExternalPackages: ["bcryptjs"],
  eslint: {
    ignoreDuringBuilds: true,
  },
  experimental: {
    serverActions: {
      bodySizeLimit: "2mb",
    },
  },
  webpack(config) {
    config.resolve.alias = {
      ...config.resolve.alias,
      "@yunya/graph-context-compressor": path.join(graphCompressorRoot, "index.ts"),
    };
    return config;
  },
};

export default nextConfig;
