import { NextRequest, NextResponse } from "next/server";
import { getToken } from "next-auth/jwt";

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

  // 检查 JWT token
  try {
    const token = await getToken({
      req: request,
      secret: process.env.AUTH_SECRET,
    });

    // 受保护路由: 需要登录
    const protectedPaths = [
      "/credits",
      "/settings",
      "/recharge",
      "/dashboard",  // 添加 /dashboard 到受保护路由
      "/market",
      "/api/config",
      "/api/user",
      "/api/market",
    ];
    
    const isProtectedPath = protectedPaths.some((p) => pathname.startsWith(p));
    
    // 如果是受保护路由但没有 token，重定向到登录页
    if (isProtectedPath && !token) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("callbackUrl", pathname);
      return NextResponse.redirect(loginUrl);
    }

    // 需要邮箱验证的路由
    const verifiedPaths = ["/recharge", "/api/config/strategies"];
    if (verifiedPaths.some((p) => pathname.startsWith(p))) {
      if (token && !token.emailVerified) {
        return NextResponse.redirect(new URL("/verify-email", request.url));
      }
    }

    // 已登录用户访问登录/注册页，重定向到 dashboard
    if (token && (pathname === "/login" || pathname === "/register")) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }

    return NextResponse.next();
  } catch (error) {
    // 如果 token 验证失败，允许请求继续（不阻塞）
    console.error("Middleware token verification error:", error);
    return NextResponse.next();
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
