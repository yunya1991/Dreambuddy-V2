'use client';

// ============================================
// V3 Spinner — 加载指示器
// ============================================

import React from 'react';

interface V3SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  color?: string;
  className?: string;
}

const sizeMap = { sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-10 w-10' };

export function V3Spinner({ size = 'md', color = 'text-blue-400', className = '' }: V3SpinnerProps) {
  return (
    <svg className={`animate-spin ${sizeMap[size]} ${color} ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

export default V3Spinner;
