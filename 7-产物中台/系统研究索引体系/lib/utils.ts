import { clsx, type ClassValue } from 'clsx';

/** Merge class names (Tailwind-safe) */
export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

/** Format ISO date string to readable Chinese format */
export function formatDate(dateStr: string): string {
  if (!dateStr || dateStr === 'unknown') return '未知日期';

  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return '未知日期';

    // 如果原始字符串只有日期部分（无时间），直接显示日期
    const dateOnlyMatch = dateStr.match(/^\d{4}-\d{2}-\d{2}$/);
    if (dateOnlyMatch) {
      const month = (date.getMonth() + 1).toString().padStart(2, '0');
      const day = date.getDate().toString().padStart(2, '0');
      return `${month}-${day}`;
    }

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
      const hours = date.getHours();
      const minutes = date.getMinutes();
      // 如果是 00:00 或接近 00:00（如 08:00 可能是时区转换结果），显示日期
      if (hours === 0 && minutes === 0) {
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const day = date.getDate().toString().padStart(2, '0');
        return `${month}-${day}`;
      }
      return `今天 ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
    } else if (diffDays === 1) {
      return `昨天 ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
    } else if (diffDays < 7) {
      return `${diffDays}天前`;
    } else {
      const month = (date.getMonth() + 1).toString().padStart(2, '0');
      const day = date.getDate().toString().padStart(2, '0');
      return `${month}-${day}`;
    }
  } catch {
    return '未知日期';
  }
}

/** Format file size to human-readable */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

/** Department display name mapping */
export const DEPARTMENT_LABELS: Record<string, string> = {
  trading: '交易部',
  dream: '做梦部',
  governance: '治理部',
  knowledge: '知识库',
  hr: 'HR',
  cfo: 'CFO',
  support: '支撑部',
};

/** Type display name mapping (common types) */
export const TYPE_LABELS: Record<string, string> = {
  daily_report: '日报',
  execution_record: '执行记录',
  proposal: '提案',
  dream_journal: '做梦日志',
  dream_summary: '做梦摘要',
  consultation: '顾问评审',
  validation: '验证报告',
  intelligence: '情报分析',
  health_report: '健康报告',
  performance_review: '绩效评审',
  risk_report: '风险报告',
  cost_report: '成本报告',
  audit: '审计报告',
  strategy: '战略文档',
  research: '深度调研',
  analysis: '分析报告',
  maintenance: '维护报告',
  meeting_record: '会议纪要',
  knowledge_base: '知识库',
  master_profile: '大师画像',
  master_index: '大师索引',
  learning: '学习记录',
  pending_task: '待办',
  assessment: '评估报告',
  verification: '验证',
  backtest: '回测',
  proposal_summary: '提案摘要',
  chain_summary: '链路摘要',
  documentation: '文档',
  template: '模板',
};

/** Chain phase display names */
export const CHAIN_PHASE_LABELS: Record<string, string> = {
  A1: 'A1 调研',
  A2: 'A2 原理',
  A3: 'A3 推演',
  A4: 'A4 验证',
  A5: 'A5 执行',
  A6: 'A6 情报',
  A7: 'A7 实践',
  A8: 'A8 自检',
  A9: 'A9 离场',
};

/** Get a human-readable type label */
export function getTypeLabel(type: string): string {
  return TYPE_LABELS[type] || type;
}

/** Get a human-readable department label */
export function getDeptLabel(dept: string): string {
  return DEPARTMENT_LABELS[dept] || dept;
}

/** Check if a date is within a time range */
export function isDateInRange(dateStr: string, range: string): boolean {
  if (!dateStr || dateStr === 'unknown') return false;

  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return false;

    const now = new Date();
    now.setHours(23, 59, 59, 999);

    if (range === 'today') {
      const todayStart = new Date(now);
      todayStart.setHours(0, 0, 0, 0);
      return date >= todayStart && date <= now;
    }

    if (range === 'week') {
      const weekAgo = new Date(now);
      weekAgo.setDate(weekAgo.getDate() - 7);
      weekAgo.setHours(0, 0, 0, 0);
      return date >= weekAgo && date <= now;
    }

    if (range === 'month') {
      const monthAgo = new Date(now);
      monthAgo.setMonth(monthAgo.getMonth() - 1);
      monthAgo.setHours(0, 0, 0, 0);
      return date >= monthAgo && date <= now;
    }

    return true; // 'all'
  } catch {
    return false;
  }
}
