"use client";

// 临时禁用 next-auth SessionProvider —— Next.js 15.5 与 next-auth 5.0-beta 存在 webpack 兼容性问题
// TODO: 升级到 @auth/nextjs 或 auth.js 正式版后恢复 SessionProvider
export function Providers({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
