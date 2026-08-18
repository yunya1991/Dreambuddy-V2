'use client';

import type { ArtifactStatus } from '@/lib/types';
import { cn } from '@/lib/utils';

const STATUS_CONFIG: Record<ArtifactStatus, { label: string; className: string; dot: string }> = {
  completed: {
    label: '已完成',
    className: 'bg-status-green/15 text-status-green border border-status-green/30',
    dot: 'bg-status-green',
  },
  in_progress: {
    label: '进行中',
    className: 'bg-status-amber/15 text-status-amber border border-status-amber/30',
    dot: 'bg-status-amber',
  },
  rejected: {
    label: '已拒绝',
    className: 'bg-status-red/15 text-status-red border border-status-red/30',
    dot: 'bg-status-red',
  },
  unknown: {
    label: '未知',
    className: 'bg-status-gray/15 text-status-gray border border-status-gray/30',
    dot: 'bg-status-gray',
  },
};

interface StatusBadgeProps {
  status: string;
  size?: 'sm' | 'md';
}

export default function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const s = STATUS_CONFIG[status as ArtifactStatus] || STATUS_CONFIG.unknown;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full font-medium',
        s.className,
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'
      )}
    >
      <span className={cn('rounded-full', s.dot, size === 'sm' ? 'h-1.5 w-1.5' : 'h-2 w-2')} />
      {s.label}
    </span>
  );
}
