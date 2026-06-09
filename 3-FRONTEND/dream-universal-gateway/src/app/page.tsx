import Link from "next/link";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col bg-white dark:bg-zinc-950">
      {/* 顶部导航 */}
      <nav className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <div className="text-lg font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
          Dream Universal Gateway
        </div>
        <div className="flex gap-3">
          <Link
            href="/login"
            className="rounded-md px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            登录
          </Link>
          <Link
            href="/register"
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            注册
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <main className="flex flex-1 flex-col items-center justify-center px-6 pb-20 pt-24 text-center">
        <h1 className="max-w-2xl text-4xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100 sm:text-5xl">
          AI 驱动的数字资产
          <br />
          交易策略平台
        </h1>
        <p className="mt-6 max-w-md text-lg leading-8 text-zinc-600 dark:text-zinc-400">
          连接交易所、配置策略、自动执行。让 AI 帮您做交易决策。
        </p>
        <div className="mt-10 flex gap-4">
          <Link
            href="/register"
            className="rounded-full bg-zinc-900 px-6 py-3 text-sm font-medium text-white transition hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            免费开始
          </Link>
          <Link
            href="/login"
            className="rounded-full border border-zinc-300 px-6 py-3 text-sm font-medium text-zinc-700 transition hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-zinc-500"
          >
            已有账户
          </Link>
        </div>
      </main>

      {/* 功能卡片 */}
      <section className="grid gap-6 px-6 pb-20 sm:grid-cols-2 lg:grid-cols-3">
        {[
          {
            title: "策略配置",
            desc: "通过自然语言描述交易策略，AI 自动解析并生成可执行策略。",
          },
          {
            title: "交易所连接",
            desc: "加密连接 OKX 等主流交易所，API Key 使用 AES-256-GCM 加密存储。",
          },
          {
            title: "自动执行",
            desc: "策略审核通过后一键下发到交易所，支持回测与实盘模式。",
          },
        ].map((card) => (
          <div
            key={card.title}
            className="rounded-lg border border-zinc-200 p-6 dark:border-zinc-800"
          >
            <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
              {card.title}
            </h3>
            <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-400">
              {card.desc}
            </p>
          </div>
        ))}
      </section>
    </div>
  );
}
