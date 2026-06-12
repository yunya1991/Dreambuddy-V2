import Link from "next/link";

export function AdminTopBar({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <header className="bg-white border-b border-gray-200 px-6 py-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{title}</h1>
          {subtitle && (
            <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
          )}
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/ui-map"
            className="text-sm text-gray-600 hover:text-blue-600 transition-colors"
          >
            ← 返回 UI Map
          </Link>
          <Link
            href="/admin/data"
            className="text-sm text-gray-600 hover:text-blue-600 transition-colors"
          >
            数据沉淀索引
          </Link>
        </div>
      </div>
    </header>
  );
}

export function Breadcrumb({
  items,
}: {
  items: { label: string; href?: string }[];
}) {
  return (
    <nav className="flex items-center text-sm text-gray-500">
      {items.map((item, idx) => (
        <span key={idx} className="flex items-center">
          {idx > 0 && <span className="mx-2 text-gray-300">/</span>}
          {item.href ? (
            <Link href={item.href} className="hover:text-blue-600 transition-colors">
              {item.label}
            </Link>
          ) : (
            <span className="text-gray-700 font-medium">{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
