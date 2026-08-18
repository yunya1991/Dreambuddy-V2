'use client';

import { cn } from '@/lib/utils';
import type { TimeRange } from '@/lib/types';

const TIME_RANGES: { id: TimeRange; label: string }[] = [
  { id: 'all', label: '最新' },
  { id: 'today', label: '今日' },
  { id: 'week', label: '本周' },
  { id: 'month', label: '本月' },
];

interface TimeFilterProps {
  selected: TimeRange;
  onSelect: (range: TimeRange) => void;
}

export default function TimeFilter({ selected, onSelect }: TimeFilterProps) {
  return (
    <div className="flex items-center gap-1">
      {TIME_RANGES.map((range) => {
        const isActive = selected === range.id;
        return (
          <button
            key={range.id}
            onClick={() => onSelect(range.id)}
            className={cn(
              'rounded-lg px-3 py-1.5 text-sm font-medium transition-all',
              'hover:bg-gray-100',
              isActive
                ? 'bg-gray-900 text-white shadow-sm hover:bg-gray-800'
                : 'text-gray-600 bg-white border border-gray-200 hover:border-gray-300'
            )}
          >
            {range.label}
          </button>
        );
      })}
    </div>
  );
}
