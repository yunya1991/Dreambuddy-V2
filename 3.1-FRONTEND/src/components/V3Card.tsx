'use client';

// ============================================
// V3 Card — 卡片容器组件
// ============================================

import React from 'react';

interface V3CardProps {
  title?: string;
  subtitle?: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  hover?: boolean;
  border?: boolean;
}

const paddingClasses = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6',
};

export function V3Card({
  title,
  subtitle,
  icon,
  badge,
  actions,
  children,
  className = '',
  padding = 'md',
  hover = false,
  border = true,
}: V3CardProps) {
  return (
    <div className={`
      bg-gray-900/50 backdrop-blur-sm rounded-xl
      ${border ? 'border border-gray-700/50' : ''}
      ${hover ? 'hover:border-gray-600/50 transition-colors' : ''}
      ${className}
    `}>
      {(title || icon || badge || actions) && (
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700/30">
          <div className="flex items-center gap-2">
            {icon && <span className="text-gray-400">{icon}</span>}
            <div>
              {title && <h3 className="text-sm font-semibold text-gray-100">{title}</h3>}
              {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {badge}
            {actions}
          </div>
        </div>
      )}
      <div className={paddingClasses[padding]}>
        {children}
      </div>
    </div>
  );
}

export default V3Card;
