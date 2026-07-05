'use client';

// ============================================
// V3 StatusDot — 状态指示点
// ============================================

import React from 'react';

type StatusType = 'idle' | 'active' | 'success' | 'warning' | 'error' | 'loading';

interface V3StatusDotProps {
  status: StatusType;
  size?: 'sm' | 'md';
  pulse?: boolean;
  className?: string;
}

const colorClasses: Record<StatusType, string> = {
  idle: 'bg-gray-500',
  active: 'bg-blue-400',
  success: 'bg-emerald-400',
  warning: 'bg-amber-400',
  error: 'bg-red-400',
  loading: 'bg-blue-400',
};

const sizeClasses = {
  sm: 'h-1.5 w-1.5',
  md: 'h-2 w-2',
};

export function V3StatusDot({ status, size = 'md', pulse = false, className = '' }: V3StatusDotProps) {
  return (
    <span className={`relative inline-flex ${sizeClasses[size]} ${className}`}>
      {pulse && (status === 'active' || status === 'loading') && (
        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-50 ${colorClasses[status]}`} />
      )}
      <span className={`relative inline-flex rounded-full ${sizeClasses[size]} ${colorClasses[status]}`} />
    </span>
  );
}

export default V3StatusDot;
