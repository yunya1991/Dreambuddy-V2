import Link from 'next/link';
import type { Meeting } from '@/lib/meeting-types';

export default function MeetingCard({ meeting }: { meeting: Meeting }) {
  const statusConfig = {
    active: { label: '进行中', bg: 'bg-green-50', text: 'text-status-green', dot: 'bg-status-green' },
    scheduled: { label: '定时', bg: 'bg-amber-50', text: 'text-status-amber', dot: 'bg-status-amber' },
    completed: { label: '已完成', bg: 'bg-gray-50', text: 'text-gray-500', dot: 'bg-gray-400' },
  };
  const sc = statusConfig[meeting.status];

  return (
    <Link href={`/meeting/${meeting.id}`} className="block rounded-xl border border-gray-200 bg-white p-4 hover:shadow-sm hover:border-gray-300 transition-all">
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-sm font-semibold text-gray-900 flex-1">{meeting.title}</h3>
        <span className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded ${sc.bg} ${sc.text}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${sc.dot}`}/> {sc.label}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-2">{meeting.topic}</p>
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>{meeting.trigger}</span>
        {meeting.startTime && <span>{meeting.startTime.slice(0, 10)}</span>}
      </div>
      {meeting.conclusions && (
        <p className="text-xs text-gray-500 mt-2 pt-2 border-t border-gray-100 truncate">{meeting.conclusions}</p>
      )}
    </Link>
  );
}
