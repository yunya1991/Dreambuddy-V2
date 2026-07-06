'use client';

import Link from 'next/link';
import { V3Card, V3Badge } from '@/components';

const quickLinks = [
  { label: 'AI Skill 交易', href: '/dashboard/trade', desc: '自然语言驱动 SACG 链执行', color: 'border-blue-500/20 hover:border-blue-500/40' },
  { label: '经典指标系统', href: '/dashboard/classic', desc: 'C0→C8 八阶段 + 治理审批流', color: 'border-emerald-500/20 hover:border-emerald-500/40' },
  { label: '基本面分析', href: '/dashboard/fundamental', desc: '多维基本面评估与链上数据', color: 'border-purple-500/20 hover:border-purple-500/40' },
  { label: '三屏交易系统', href: '/dashboard/three-screens', desc: '战略→战术→执行 方向约束传播', color: 'border-amber-500/20 hover:border-amber-500/40' },
  { label: 'SACG 监控', href: '/dashboard/monitor', desc: '四层运行状态 / DAG / BAC 压缩', color: 'border-cyan-500/20 hover:border-cyan-500/40' },
  { label: '记忆管理', href: '/dashboard/memory', desc: 'D-Z-E 工程链 / BAC 压缩统计', color: 'border-pink-500/20 hover:border-pink-500/40' },
  { label: '治理面板', href: '/dashboard/governance', desc: 'Draft→Gate→Approval→Apply→Audit', color: 'border-orange-500/20 hover:border-orange-500/40' },
  { label: '产物中台', href: '/dashboard/reports', desc: '交易报告 / 数据产物 / 图表归档', color: 'border-teal-500/20 hover:border-teal-500/40' },
];

export default function DashboardPage() {
  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-200">DreamBuddy v3</h1>
        <p className="text-sm text-slate-500">SACG 四层 AI 交易操作系统</p>
      </div>
      <div className="grid grid-cols-4 gap-3 mb-6">
        {[
          { layer: 'S', label: '感知层', desc: '意图识别 · 市场感知', variant: 'sacg-s' as const },
          { layer: 'A', label: '编排层', desc: 'Chain 编排 · DAG 调度', variant: 'sacg-a' as const },
          { layer: 'C', label: '执行层', desc: '交易执行 · 风控守卫', variant: 'sacg-c' as const },
          { layer: 'G', label: '存储层', desc: '图记忆 · BAC 压缩', variant: 'sacg-g' as const },
        ].map(l => (
          <V3Card key={l.layer} padding="sm">
            <div className="flex items-center gap-2 mb-1">
              <V3Badge variant={l.variant} dot label={l.layer} />
              <span className="text-xs font-medium text-slate-300">{l.label}</span>
            </div>
            <p className="text-[10px] text-slate-500">{l.desc}</p>
          </V3Card>
        ))}
      </div>
      <h2 className="text-sm font-semibold text-slate-400 mb-3">快速入口</h2>
      <div className="grid grid-cols-2 gap-3">
        {quickLinks.map(link => (
          <Link key={link.href} href={link.href} className={`block p-4 rounded-xl border bg-slate-800/30 transition-colors ${link.color}`}>
            <p className="text-sm font-medium text-slate-200 mb-1">{link.label}</p>
            <p className="text-[10px] text-slate-500">{link.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
