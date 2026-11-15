// ============================================================================
// 管理台路由守卫（SPEC-7 §5.1）
// ----------------------------------------------------------------------------
// Edge 环境不查库、不解 JWT，只做「cookie 是否存在」的粗筛：
//   - 无 cookie：页面 302 /admin/login，API 401
//   - 有 cookie：放行，真正的角色校验由 requireAdmin() 在 Node 运行时完成
// 好处：降权/禁用能被 requireAdmin 立即拦截；中间件保持零依赖、零 IO。
// ============================================================================

import { NextResponse, type NextRequest } from "next/server";
import { ADMIN_COOKIE_NAME } from "@/lib/admin/constants";

const PUBLIC_PATHS = new Set(["/admin/login", "/api/admin/login"]);

/** 内部任务端点：不走管理员会话，由 X-Internal-Token 在处理器内校验 */
const INTERNAL_API_PREFIX = "/api/admin/jobs/";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.has(pathname) || pathname.startsWith(INTERNAL_API_PREFIX)) {
    return NextResponse.next();
  }

  const hasSessionCookie = Boolean(request.cookies.get(ADMIN_COOKIE_NAME)?.value);
  if (hasSessionCookie) {
    return NextResponse.next();
  }

  if (pathname.startsWith("/api/admin")) {
    return NextResponse.json(
      {
        success: false,
        data: null,
        error: "UNAUTHENTICATED",
        message: "未登录或会话已过期",
        requestId: `req_mw_${Date.now().toString(36)}`,
      },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  // 云端经 nginx 反代时，Node 运行时无法从 Host 头还原外部 origin（next start 绑定
  // 127.0.0.1 会把 origin 归一成 localhost:3456），因此用构建期公开 origin 兜底。
  const origin = process.env.NEXT_PUBLIC_ADMIN_ORIGIN || request.nextUrl.origin;
  const loginUrl = new URL("/admin/login", origin);
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/admin/:path*", "/api/admin/:path*"],
};
