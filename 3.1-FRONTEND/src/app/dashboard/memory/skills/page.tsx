'use client';

import { MemoryTabNav } from '@/components/features/memory/MemoryTabNav';
import { SkillIndexView } from '@/components/features/memory/SkillIndexView';

export default function SkillsPage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">Skill 索引</h1>
        <p className="text-xs text-slate-500">项目自有 Skill 注册表 + 生命周期 + 认知链接</p>
      </div>
      <MemoryTabNav />
      <SkillIndexView />
    </div>
  );
}
