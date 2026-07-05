'use client';

import React, { useState } from 'react';
import { useThreeScreensStore } from '@/stores';
import { Screen1Panel } from '@/components/features/three-screens/Screen1Panel';
import { Screen2Panel } from '@/components/features/three-screens/Screen2Panel';
import { Screen3Panel } from '@/components/features/three-screens/Screen3Panel';
import { PipelineView } from '@/components/features/three-screens/PipelineView';
import { V3Badge } from '@/components/V3Badge';

export default function ThreeScreensPage() {
  const { activeScreen, setActiveScreen, symbol, directionConstraint } = useThreeScreensStore();

  const tabs = [
    { key: 'overview' as const, label: '总览' },
    { key: 'screen1' as const, label: 'Screen 1' },
    { key: 'screen2' as const, label: 'Screen 2' },
    { key: 'screen3' as const, label: 'Screen 3' },
    { key: 'pipeline' as const, label: 'Pipeline' },
  ];

  return (
    <div className="p-4 h-full flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold text-gray-100">三屏交易系统</h1>
          <V3Badge variant="default">{symbol}</V3Badge>
          {directionConstraint?.direction && (
            <V3Badge variant={directionConstraint.direction === 'LONG' ? 'success' : 'danger'}>
              {directionConstraint.direction}
            </V3Badge>
          )}
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-1 mb-4 border-b border-gray-700/30 pb-0">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveScreen(tab.key)}
            className={`
              px-3 py-2 text-xs font-medium rounded-t-lg transition-colors
              ${activeScreen === tab.key
                ? 'text-blue-400 bg-blue-500/10 border-b-2 border-blue-400'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/30'}
            `}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto">
        {activeScreen === 'overview' && (
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2"><PipelineView /></div>
          </div>
        )}
        {activeScreen === 'screen1' && <Screen1Panel />}
        {activeScreen === 'screen2' && <Screen2Panel />}
        {activeScreen === 'screen3' && <Screen3Panel />}
        {activeScreen === 'pipeline' && <PipelineView />}
      </div>
    </div>
  );
}
