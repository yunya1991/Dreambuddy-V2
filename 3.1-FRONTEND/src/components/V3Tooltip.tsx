'use client';

// ============================================
// V3 Tooltip — 工具提示组件
// ============================================

import React, { useState, useRef } from 'react';

interface V3TooltipProps {
  content: string;
  children: React.ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
}

const positionClasses = {
  top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
  left: 'right-full top-1/2 -translate-y-1/2 mr-2',
  right: 'left-full top-1/2 -translate-y-1/2 ml-2',
};

export function V3Tooltip({ content, children, position = 'top', delay = 300 }: V3TooltipProps) {
  const [visible, setVisible] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout>();

  const show = () => {
    timeoutRef.current = setTimeout(() => setVisible(true), delay);
  };
  const hide = () => {
    clearTimeout(timeoutRef.current);
    setVisible(false);
  };

  return (
    <span className="relative inline-flex" onMouseEnter={show} onMouseLeave={hide}>
      {children}
      {visible && (
        <span className={`
          absolute z-50 px-2.5 py-1.5 text-xs text-gray-100 bg-gray-800 border border-gray-600/50
          rounded-lg shadow-lg whitespace-nowrap pointer-events-none
          ${positionClasses[position]}
        `}>
          {content}
        </span>
      )}
    </span>
  );
}

export default V3Tooltip;
