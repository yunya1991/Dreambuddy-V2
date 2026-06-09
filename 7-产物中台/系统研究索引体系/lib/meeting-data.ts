import fs from 'fs';
import path from 'path';
import type { Meeting, MeetingStatus } from './meeting-types';
import { CAMPS } from './meeting-types';

const BOSS_SECRETARY = path.join(process.env.HOME || '/Users/zhangjiangtao', '.workbuddy/skills/boss-secretary');
const MEETINGS_DIR = path.join(BOSS_SECRETARY, 'meetings');
const REPORTS_DIR = path.join(BOSS_SECRETARY, 'reports');

/* ──── All meetings (history + active + scheduled) ──── */
export function getAllMeetings(): Meeting[] {
  const meetings: Meeting[] = [];

  // 1. Existing YAML meetings
  if (fs.existsSync(MEETINGS_DIR)) {
    for (const f of fs.readdirSync(MEETINGS_DIR)) {
      if (!f.endsWith('.yaml') && !f.endsWith('.yml')) continue;
      try {
        const content = fs.readFileSync(path.join(MEETINGS_DIR, f), 'utf-8');
        const m = parseMeetingYaml(content, f.replace(/\.ya?ml$/, ''));
        if (m) meetings.push(m);
      } catch {}
    }
  }

  // 2. Seminar reports
  if (fs.existsSync(REPORTS_DIR)) {
    for (const f of fs.readdirSync(REPORTS_DIR)) {
      if (!f.startsWith('seminar_SEM_') || !f.endsWith('.md')) continue;
      try {
        const content = fs.readFileSync(path.join(REPORTS_DIR, f), 'utf-8');
        const m = parseSeminarMd(content, f.replace('.md', ''));
        if (m) meetings.push(m);
      } catch {}
    }
  }

  // 3. Scheduled templates
  meetings.push(
    {
      id: 'scheduled-weekly',
      title: '每周复盘研讨',
      topic: '周度市场回顾 & 战略校准',
      trigger: '定时 · 每周日 20:00',
      camps: [...CAMPS],
      status: 'scheduled',
      startTime: '',
    },
    {
      id: 'scheduled-a4-gate',
      title: 'A4门禁阻断·紧急研讨',
      topic: '战术验证未通过，需要大师研判',
      trigger: '事件驱动 · A4 gate_blocked',
      camps: [...CAMPS],
      status: 'scheduled',
      startTime: '',
    },
    {
      id: 'scheduled-dream',
      title: '做梦洞察评审会',
      topic: '潜意识分析报告评审 & 落地讨论',
      trigger: '事件驱动 · dream_insight_produced',
      camps: [CAMPS[0], CAMPS[2]], // Only bulls and bears
      status: 'scheduled',
      startTime: '',
    }
  );

  return meetings.sort((a, b) => {
    const order: Record<MeetingStatus, number> = { active: 0, scheduled: 1, completed: 2 };
    return (order[a.status] ?? 3) - (order[b.status] ?? 3);
  });
}

/* ──── Get single meeting ──── */
export function getMeeting(id: string): Meeting | null {
  const all = getAllMeetings();
  return all.find(m => m.id === id) || null;
}

/* ──── YAML parser ──── */
function parseMeetingYaml(content: string, id: string): Meeting | null {
  const lines = content.split('\n');
  const get = (key: string) => {
    const line = lines.find(l => l.trim().startsWith(key + ':'));
    return line ? line.split(':').slice(1).join(':').trim().replace(/['"]/g, '') : '';
  };
  const title = get('title') || get('meeting_id') || id;
  const startTime = get('start_time');
  const endTime = get('end_time');
  const status: MeetingStatus = endTime && endTime !== startTime ? 'completed' : startTime ? 'active' : 'scheduled';

  return {
    id, title,
    topic: get('meeting_type') || get('agenda') || '',
    trigger: get('reason') || '手动发起',
    camps: [...CAMPS],
    status,
    startTime,
    endTime: endTime || undefined,
    conclusions: get('decisions') || undefined,
    sourceYaml: id,
  };
}

/* ──── Seminar MD parser ──── */
function parseSeminarMd(content: string, id: string): Meeting | null {
  const frontmatterEnd = content.indexOf('---', 4);
  const fm = frontmatterEnd > 0 ? content.substring(4, frontmatterEnd) : '';
  const get = (key: string) => {
    const line = fm.split('\n').find(l => l.trim().startsWith(key + ':'));
    return line ? line.split(':').slice(1).join(':').trim().replace(/['"]/g, '') : '';
  };

  return {
    id, title: get('title') || id,
    topic: '大师研讨',
    trigger: 'master_disagreement',
    camps: [...CAMPS],
    status: 'completed',
    startTime: get('date') || '',
    sourceYaml: id,
  };
}
