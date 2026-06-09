import { getAllMeetings } from '@/lib/meeting-data';
import type { Meeting } from '@/lib/meeting-types';
import MeetingCard from '@/components/MeetingCard';

export default function MeetingListPage() {
  const meetings = getAllMeetings();

  const active = meetings.filter(m => m.status === 'active');
  const scheduled = meetings.filter(m => m.status === 'scheduled');
  const completed = meetings.filter(m => m.status === 'completed');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">会议室</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {active.length}场进行中 · {scheduled.length}场定时 · {completed.length}场已完成
        </p>
      </div>

      {/* Quick Start */}
      <div className="rounded-xl border-2 border-blue-200 bg-blue-50 p-4 flex items-center gap-4">
        <div className="flex-1">
          <h2 className="text-sm font-semibold text-blue-700">快速发起研讨</h2>
          <p className="text-xs text-blue-500 mt-0.5">三阵营大师辩论 · SSE实时流式</p>
        </div>
        <a href="/meeting/quick-start" className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-500 text-white hover:bg-blue-600">
          立即开始
        </a>
      </div>

      {/* Active */}
      {active.length > 0 && (
        <Section title="进行中" count={active.length} meetings={active} />
      )}

      {/* Scheduled */}
      {scheduled.length > 0 && (
        <Section title="定时组会" count={scheduled.length} meetings={scheduled} />
      )}

      {/* Completed */}
      {completed.length > 0 && (
        <Section title="历史会议" count={completed.length} meetings={completed} />
      )}
    </div>
  );
}

function Section({ title, count, meetings }: { title: string; count: number; meetings: Meeting[] }) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-700 mb-3">{title} · {count}场</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {meetings.map(m => (
          <MeetingCard key={m.id} meeting={m} />
        ))}
      </div>
    </div>
  );
}
