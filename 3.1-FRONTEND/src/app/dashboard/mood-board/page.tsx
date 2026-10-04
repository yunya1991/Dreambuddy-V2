'use client';

import React from 'react';
import { MoodBoardPanel } from '@/components/features/chat/MoodBoardPanel';

/**
 * F7.3: Mood Board 情绪板页面
 *
 * Muse 启发: 多源信息综合成视觉化情绪板
 * 一屏综合展示: 多空信号 + 相关性矩阵 + 风险热力图 + 资金流向 + Portfolio Heat
 */

export default function MoodBoardPage() {
  return (
    <div className="p-4 sm:p-6">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-slate-200">Mood Board 情绪板</h1>
        <p className="text-sm text-slate-500 mt-1">
          多空信号 · 相关性矩阵 · 风险热力图 · 资金流向 · Portfolio Heat · ML 压力测试
        </p>
      </div>
      <MoodBoardPanel />
    </div>
  );
}
