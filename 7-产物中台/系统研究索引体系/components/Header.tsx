'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Building2, LayoutDashboard } from 'lucide-react';
import { cn } from '@/lib/utils';

export default function Header() {
  const pathname = usePathname();
  const isFeedActive = pathname.startsWith('/feed');
  const isOrgActive = pathname.startsWith('/org');
  const isChainActive = pathname.startsWith('/chain');
  const isMeetingActive = pathname.startsWith('/meeting');

  const [totalArtifacts, setTotalArtifacts] = useState<number | null>(null);
  const [numDepartments, setNumDepartments] = useState<number | null>(null);

  useEffect(() => {
    // Fetch stats from API
    fetch('/api/stats')
      .then(res => res.json())
      .then(data => {
        if (data.total !== undefined) {
          setTotalArtifacts(data.total);
        }
        if (data.departments !== undefined) {
          setNumDepartments(data.departments);
        }
      })
      .catch(err => {
        console.error('Failed to fetch stats:', err);
      });
  }, []);

  return (
    <header className="sticky top-0 z-50 border-b border-gray-200 bg-white/80 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        {/* Logo & Nav */}
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2">
            <Building2 className="h-6 w-6 text-gray-900" />
            <span className="text-lg font-bold text-gray-900">Dream 产物中心</span>
          </Link>

          <nav className="hidden sm:flex items-center gap-1">
            <Link
              href="/feed"
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                isFeedActive
                  ? 'text-gray-900 bg-gray-100'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              )}
            >
              产物中心
            </Link>
            <Link
              href="/org"
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                isOrgActive
                  ? 'text-gray-900 bg-gray-100'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              )}
            >
              组织架构
            </Link>
            <Link
              href="/chain"
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                isChainActive
                  ? 'text-gray-900 bg-gray-100'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              )}
            >
              驾驶舱
            </Link>
            <Link
              href="/meeting"
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                isMeetingActive
                  ? 'text-gray-900 bg-gray-100'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
              )}
            >
              会议室
            </Link>
          </nav>
        </div>

        {/* Stats indicator */}
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <LayoutDashboard className="h-4 w-4" />
          <span>{totalArtifacts !== null ? `${totalArtifacts} 产物` : '加载中...'}</span>
          <span className="text-gray-300">|</span>
          <span>{numDepartments !== null ? `${numDepartments} 部门` : '-'}</span>
        </div>
      </div>
    </header>
  );
}
