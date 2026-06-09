import React from "react";
import Link from "next/link";

export default function VerifyEmailPage() {
  return (
    <main className="min-h-screen bg-zinc-950 px-4 py-16 text-zinc-100">
      <div className="mx-auto max-w-xl rounded-2xl border border-zinc-800 bg-zinc-900/80 p-8 shadow-2xl">
        <div className="mb-6">
          <p className="mb-2 text-sm font-medium text-blue-400">Account Security</p>
          <h1 className="text-3xl font-bold">验证邮箱</h1>
          <p className="mt-3 text-sm leading-6 text-zinc-400">
            继续前请先完成邮箱验证。系统检测到当前账户还没有通过邮箱校验，因此暂时限制进入部分交易与配置页面。
          </p>
        </div>

        <div className="rounded-xl border border-amber-700/40 bg-amber-500/10 p-4 text-sm text-amber-200">
          <p>请检查注册邮箱中的验证邮件。</p>
          <p className="mt-2 text-amber-100/80">
            如果没有收到邮件，请返回登录或注册流程后重新触发验证。
          </p>
        </div>

        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <Link
            href="/login"
            className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-500"
          >
            返回登录
          </Link>
          <Link
            href="/dashboard"
            className="inline-flex items-center justify-center rounded-lg border border-zinc-700 px-4 py-2.5 text-sm font-medium text-zinc-200 transition hover:bg-zinc-800"
          >
            返回仪表盘
          </Link>
        </div>
      </div>
    </main>
  );
}
