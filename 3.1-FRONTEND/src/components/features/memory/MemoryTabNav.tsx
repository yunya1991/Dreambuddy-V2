'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const TABS = [
  { href: '/dashboard/memory', label: '概览', exact: true },
  { href: '/dashboard/memory/user', label: '用户层' },
  { href: '/dashboard/memory/skills', label: 'Skill 索引' },
  { href: '/dashboard/memory/docs', label: '文档索引' },
  { href: '/dashboard/memory/dze', label: 'DZE 工程链' },
];

export function MemoryTabNav() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1 border-b border-slate-700/40 mb-4">
      {TABS.map(tab => {
        const active = tab.exact
          ? pathname === tab.href
          : pathname?.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`px-3 py-1.5 text-xs rounded-t-md border-b-2 transition-colors ${
              active
                ? 'border-blue-400 text-blue-300 bg-slate-800/40'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
