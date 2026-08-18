import { NextRequest, NextResponse } from "next/server";

// 注意：next-auth/jwt 的 getToken 在 Next.js 15.5 + next-auth 5.0-beta 环境下会导致
// 客户端 chunk 加载失败（"Cannot find the middleware module"），从而出现浏览器白屏。
// 因此 middleware 不再引入 next-auth，鉴权改由页面/接口层自行处理。

function isLocalPreviewHost(host: string | null) {
  if (!host) {
    return false;
  }

  const normalizedHost = host.toLowerCase();
  return (
    normalizedHost.startsWith("localhost:") ||
    normalizedHost === "localhost" ||
    normalizedHost.startsWith("127.0.0.1:") ||
    normalizedHost === "127.0.0.1"
  );
}

export function shouldBypassPreviewAuth(pathname: string, isDev: boolean, isLocalhost: boolean) {
  const previewPrefixes = ["/dashboard", "/recharge", "/api/user", "/api/config", "/api/market"];
  return (isDev || isLocalhost) && previewPrefixes.some((p) => pathname.startsWith(p));
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isDev = process.env.NODE_ENV !== "production";
  const isLocalhost = isLocalPreviewHost(request.headers.get("host"));

  // 公开路由: 无需登录
  const publicPrefixes = ["/login", "/register", "/api/auth"];
  if (pathname === "/" || publicPrefixes.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // 静态资源 - 直接放行
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // 本地开发预览模式：允许 dashboard 与其依赖接口直接走 DEMO_UID/Mock 回退
  if (shouldBypassPreviewAuth(pathname, isDev, isLocalhost)) {
    return NextResponse.next();
  }

  // 受保护路由: 需要登录
  // 由于 next-auth 5.0-beta 与 Next.js 15.5 不兼容，middleware 不再进行 JWT 校验。
  // 鉴权改由页面/接口层自行处理（参考 providers.tsx 的注释）。
  // 本地开发环境：shouldBypassPreviewAuth 已经放行 dashboard 相关路由；
  // 生产环境：未携带登录态时由页面层自行重定向到 /login。
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
