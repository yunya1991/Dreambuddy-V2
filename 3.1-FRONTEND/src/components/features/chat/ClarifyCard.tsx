'use client';

import React, { useState } from 'react';
import { V3Badge } from '@/components';

// === Clarify 卡片数据结构（与后端 task-manager.ts ClarificationOutput 对齐）===
interface ClarifyOption {
  key: string;
  label: string;
  description?: string;
}

interface ClarifyData {
  id: string;
  type: 'multiple_choice';
  question: string;
  dimension?: string;
  priority?: number;
  options: ClarifyOption[];
}

interface ClarifyCardProps {
  data: ClarifyData;
  /** 选中某个选项时触发，参数为 option.key + option.label */
  onSelectOption: (optionKey: string, optionLabel: string) => void;
  /** 是否禁用（例如正在流式输出时） */
  disabled?: boolean;
}

/**
 * ClarifyCard — 多轮澄清交互卡片
 *
 * 当 AI 返回 type=multiple_choice 的 JSON 时渲染为可点选的卡片，
 * 而非原始 JSON 文本。用户点选后自动作为用户消息发回对话。
 */
export function ClarifyCard({ data, onSelectOption, disabled = false }: ClarifyCardProps) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const handleSelect = (opt: ClarifyOption) => {
    if (disabled || selectedKey) return;
    setSelectedKey(opt.key);
    onSelectOption(opt.key, opt.label);
  };

  return (
    <div className="rounded-lg border border-indigo-500/30 bg-indigo-950/20 p-3 my-1">
      {/* 问题头部 */}
      <div className="flex items-start gap-2 mb-3">
        <span className="text-sm">🤔</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-100 font-medium leading-relaxed">{data.question}</p>
          <div className="flex items-center gap-1.5 mt-1.5">
            {data.dimension && (
              <V3Badge variant="info" className="text-[9px]">{data.dimension}</V3Badge>
            )}
            {data.priority != null && (
              <V3Badge variant="default" className="text-[9px]">P{data.priority}</V3Badge>
            )}
            <V3Badge variant="warning" className="text-[9px]" dot pulse={!selectedKey}>
              {selectedKey ? '已回答' : '待选择'}
            </V3Badge>
          </div>
        </div>
      </div>

      {/* 选项列表 */}
      <div className="space-y-1.5">
        {data.options.map((opt, idx) => {
          const isSelected = selectedKey === opt.key;
          const isOther = selectedKey && !isSelected;
          return (
            <button
              key={opt.key}
              onClick={() => handleSelect(opt)}
              disabled={disabled || !!selectedKey}
              className={`
                w-full text-left px-3 py-2 rounded-lg text-xs transition-all flex items-start gap-2
                ${isSelected
                  ? 'bg-emerald-600/20 border border-emerald-500/40 text-emerald-200'
                  : isOther
                    ? 'bg-slate-800/20 border border-slate-700/20 text-slate-500 opacity-60'
                    : 'bg-slate-800/40 border border-slate-700/30 text-slate-200 hover:border-indigo-500/40 hover:bg-slate-700/40'}
                ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}
              `}
            >
              <span className={`text-[10px] font-bold mt-0.5 ${isSelected ? 'text-emerald-400' : 'text-slate-500'}`}>
                {isSelected ? '✓' : String.fromCharCode(65 + idx)}
              </span>
              <div className="flex-1 min-w-0">
                <p className="font-medium">{opt.label}</p>
                {opt.description && (
                  <p className="text-[10px] text-slate-500 mt-0.5 leading-relaxed">{opt.description}</p>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* 已选提示 */}
      {selectedKey && (
        <p className="text-[10px] text-slate-500 mt-2 flex items-center gap-1">
          <span>✓</span>
          <span>已选择，正在继续分析...</span>
        </p>
      )}
    </div>
  );
}

/**
 * 检测 content 是否为 clarify JSON 数据
 * 返回 parsed data 或 null
 */
export function tryParseClarify(content: string): ClarifyData | null {
  const trimmed = (content || '').trim();
  if (!trimmed.startsWith('{')) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === 'object'
        && parsed.type === 'multiple_choice'
        && typeof parsed.question === 'string'
        && Array.isArray(parsed.options)) {
      return parsed as ClarifyData;
    }
    return null;
  } catch {
    return null;
  }
}

export default ClarifyCard;
