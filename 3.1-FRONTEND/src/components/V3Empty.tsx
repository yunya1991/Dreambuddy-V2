'use client';

// ============================================
// V3 Empty — 空状态组件
// ============================================

import React from 'react';

interface V3EmptyProps {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export function V3Empty({ title, description, icon, action, className = '' }: V3EmptyProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-12 px-4 ${className}`}>
      {icon && <span className="text-gray-600 mb-3">{icon}</span>}
      {!icon && (
        <svg className="w-12 h-12 text-gray-600 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
      )}
      <h3 className="text-sm font-medium text-gray-400">{title}</h3>
      {description && <p className="text-xs text-gray-500 mt-1 max-w-xs text-center">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export default V3Empty;
