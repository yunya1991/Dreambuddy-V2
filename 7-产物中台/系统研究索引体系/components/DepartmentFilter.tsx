'use client';

import { cn } from '@/lib/utils';

const DEPARTMENTS = [
  { id: 'all', label: '全部', color: 'text-gray-900' },
  { id: 'trading', label: '交易部', color: 'text-blue-600' },
  { id: 'dream', label: '做梦部', color: 'text-purple-600' },
  { id: 'governance', label: '治理部', color: 'text-amber-600' },
  { id: 'knowledge', label: '知识库', color: 'text-emerald-600' },
  { id: 'hr', label: 'HR', color: 'text-pink-600' },
  { id: 'cfo', label: 'CFO', color: 'text-orange-600' },
  { id: 'support', label: '支撑部', color: 'text-gray-500' },
];

interface DepartmentFilterProps {
  selected: string;
  onChange: (id: string) => void;
  counts?: Record<string, number>;
  newDepts?: Set<string>;
}

export default function DepartmentFilter({ selected, onChange, counts, newDepts }: DepartmentFilterProps) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto pb-1 scrollbar-hide">
      {DEPARTMENTS.map((dept) => {
        const isActive = selected === dept.id;
        const count = counts?.[dept.id];
        const isNew = newDepts?.has(dept.id);
        return (
          <button
            key={dept.id}
            onClick={() => onChange(dept.id)}
            className={cn(
              'flex-shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium transition-all',
              'hover:bg-gray-100',
              isActive
                ? 'bg-gray-900 text-white shadow-sm hover:bg-gray-800'
                : 'text-gray-600 bg-white border border-gray-200 hover:border-gray-300'
            )}
          >
            {dept.label}
            {count !== undefined && (
              <span
                className={cn(
                  'ml-1.5 text-xs',
                  isActive ? 'text-gray-300' : 'text-gray-400'
                )}
              >
                {count}
              </span>
            )}
            {isNew && count !== undefined && count > 0 && (
              <span className="ml-1 w-2 h-2 bg-red-500 rounded-full inline-block" />
            )}
          </button>
        );
      })}
    </div>
  );
}
