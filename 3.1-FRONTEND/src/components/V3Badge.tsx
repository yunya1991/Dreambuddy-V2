'use client';

// ============================================
// V3 Badge — 状态标记组件
// ============================================

import React from 'react';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'sacg-s' | 'sacg-a' | 'sacg-c' | 'sacg-g';

interface V3BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  dot?: boolean;
  pulse?: boolean;
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-gray-700/50 text-gray-300 border-gray-600/30',
  success: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  warning: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  danger: 'bg-red-500/15 text-red-400 border-red-500/30',
  info: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  'sacg-s': 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  'sacg-a': 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  'sacg-c': 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  'sacg-g': 'bg-red-500/15 text-red-400 border-red-500/30',
};

const dotColorClasses: Record<BadgeVariant, string> = {
  default: 'bg-gray-400',
  success: 'bg-emerald-400',
  warning: 'bg-amber-400',
  danger: 'bg-red-400',
  info: 'bg-blue-400',
  'sacg-s': 'bg-purple-400',
  'sacg-a': 'bg-blue-400',
  'sacg-c': 'bg-emerald-400',
  'sacg-g': 'bg-red-400',
};

export function V3Badge({ variant = 'default', children, dot = false, pulse = false, className = '' }: V3BadgeProps) {
  return (
    <span className={`
      inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium
      border ${variantClasses[variant]} ${className}
    `}>
      {dot && (
        <span className={`relative flex h-1.5 w-1.5`}>
          {pulse && (
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${dotColorClasses[variant]}`} />
          )}
          <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${dotColorClasses[variant]}`} />
        </span>
      )}
      {children}
    </span>
  );
}

export default V3Badge;
