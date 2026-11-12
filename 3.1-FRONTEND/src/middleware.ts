/**
 * NextAuth v5 鉴权中间件
 * - dev 默认放开（AUTH_REQUIRED=false 或未设）
 * - production 默认开启（AUTH_REQUIRED 未设时 === true）
 * - 未登录访问 /dashboard/:path* → 重定向 /login?next=<原路径>
 * - 不改任何 API 内部鉴权；仅页面级门禁
 */
import { auth } from '@/lib/auth';
import { NextResponse } from 'next/server';

function isAuthRequired(): boolean {
  const env = process.env.AUTH_REQUIRED;
  if (env === 'true') return true;
  if (env === 'false') return false;
  // 未显式设置：production 默认开，dev 默认关
  return process.env.NODE_ENV === 'production';
}

export default auth((req) => {
  // 关闭鉴权时直接放行 —— dev 默认行为
  if (!isAuthRequired()) {
    return NextResponse.next();
  }

  // 已登录 → 放行
  if (req.auth) {
    return NextResponse.next();
  }

  // 未登录 → 重定向到 /login?next=<原路径>
  const url = req.nextUrl.clone();
  url.pathname = '/login';
  const next = req.nextUrl.pathname + (req.nextUrl.search ?? '');
  if (next && next !== '/login') {
    url.searchParams.set('next', next);
  }
  return NextResponse.redirect(url);
});

export const config = {
  matcher: [
    '/dashboard/:path*',
    // 可按需扩展: '/agent', '/board/:path*'
  ],
};
