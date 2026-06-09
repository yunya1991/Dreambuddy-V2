import Link from 'next/link';
import { FileText, Clock, Tag } from 'lucide-react';
import StatusBadge from './StatusBadge';
import { cn, formatDate, getDeptLabel, getTypeLabel, CHAIN_PHASE_LABELS } from '@/lib/utils';
import type { CanonicalArtifactIndex } from '@/lib/types';

// Department color mapping for left border
const DEPT_BORDER_COLORS: Record<string, string> = {
  trading: 'border-l-blue-500',
  dream: 'border-l-purple-500',
  governance: 'border-l-amber-500',
  knowledge: 'border-l-emerald-500',
  hr: 'border-l-pink-500',
  cfo: 'border-l-orange-500',
  support: 'border-l-gray-400',
};

// Type badge colors
const TYPE_COLORS: Record<string, string> = {
  daily_report: 'bg-blue-50 text-blue-700',
  execution_record: 'bg-green-50 text-green-700',
  proposal: 'bg-amber-50 text-amber-700',
  dream_journal: 'bg-purple-50 text-purple-700',
  dream_summary: 'bg-purple-50 text-purple-700',
  consultation: 'bg-cyan-50 text-cyan-700',
  validation: 'bg-indigo-50 text-indigo-700',
  intelligence: 'bg-red-50 text-red-700',
  health_report: 'bg-teal-50 text-teal-700',
  performance_review: 'bg-pink-50 text-pink-700',
  risk_report: 'bg-rose-50 text-rose-700',
  audit: 'bg-gray-50 text-gray-700',
  strategy: 'bg-violet-50 text-violet-700',
  research: 'bg-sky-50 text-sky-700',
  analysis: 'bg-emerald-50 text-emerald-700',
  maintenance: 'bg-slate-50 text-slate-700',
  meeting_record: 'bg-fuchsia-50 text-fuchsia-700',
  knowledge_base: 'bg-lime-50 text-lime-700',
  master_profile: 'bg-orange-50 text-orange-700',
  master_index: 'bg-orange-50 text-orange-700',
  learning: 'bg-yellow-50 text-yellow-700',
  pending_task: 'bg-gray-100 text-gray-600',
  cost_report: 'bg-emerald-50 text-emerald-700',
  default: 'bg-gray-50 text-gray-600',
};

interface FeedCardProps {
  artifact: CanonicalArtifactIndex;
}

export default function FeedCard({ artifact }: FeedCardProps) {
  const borderColor = DEPT_BORDER_COLORS[artifact.department] || 'border-l-gray-300';
  const typeColor = TYPE_COLORS[artifact.type] || TYPE_COLORS.default;

  const tags = artifact.tags;

  return (
    <Link
      href={artifact.detailUrl}
      className={cn(
        'group block rounded-lg border border-gray-200 bg-white p-4 transition-all',
        'hover:shadow-md hover:border-gray-300',
        'border-l-4',
        borderColor
      )}
    >
      {/* Header: Title + Status */}
      <div className="flex items-start justify-between gap-3">
        <h3 className="flex-1 text-base font-semibold text-gray-900 group-hover:text-blue-600 transition-colors line-clamp-2">
          {artifact.title}
        </h3>
        <StatusBadge status={artifact.status} size="sm" />
      </div>

      {/* Meta row: Department + Type + Date */}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <FileText className="h-3 w-3" />
          {getDeptLabel(artifact.department)}
        </span>

        <span className={cn('rounded px-1.5 py-0.5 font-medium', typeColor)}>
          {getTypeLabel(artifact.type)}
        </span>

        {artifact.chainPhase && (
          <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-gray-600">
            {CHAIN_PHASE_LABELS[artifact.chainPhase] || artifact.chainPhase}
          </span>
        )}

        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatDate(artifact.date)}
        </span>
      </div>

      {/* Tags */}
      {tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {tags.slice(0, 5).map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-0.5 rounded-md bg-gray-50 px-1.5 py-0.5 text-xs text-gray-500"
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
            </span>
          ))}
          {tags.length > 5 && (
            <span className="text-xs text-gray-400">+{tags.length - 5}</span>
          )}
        </div>
      )}

      {/* Excerpt */}
      {artifact.excerpt && (
        <p className="mt-2 text-sm text-gray-600 line-clamp-2 leading-relaxed">
          {artifact.excerpt}
        </p>
      )}
    </Link>
  );
}
