'use client';

import React, { useRef, useCallback } from 'react';
import { V3Button } from '@/components';
import { IconSend, IconPlus } from '@/components';

interface ChatInputProps {
  /** 当前输入值 */
  value: string;
  /** 输入值变更回调 */
  onChange: (value: string) => void;
  /** 发送回调 */
  onSend: () => void;
  /** 是否禁用 */
  disabled?: boolean;
  /** 是否加载中 */
  loading?: boolean;
  /** 输入模式 */
  mode?: 'chat' | 'command';
  /** 模式切换回调（传入则显示切换按钮） */
  onModeToggle?: () => void;
  /** 占位文本 */
  placeholder?: string;
}

/**
 * ChatInput — 聊天输入组件
 *
 * 从 ChatPanel 中拆分，可独立使用。
 * 支持键盘快捷键（Enter 发送 / Shift+Enter 换行）、
 * 模式切换（chat / command）。
 */
export function ChatInput({
  value, onChange, onSend, disabled = false, loading = false,
  mode = 'chat', onModeToggle, placeholder,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 键盘快捷键处理
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (value.trim() && !disabled && !loading) onSend();
    }
  };

  // 发送按钮点击
  const handleSend = useCallback(() => {
    if (value.trim() && !disabled && !loading) onSend();
  }, [value, disabled, loading, onSend]);

  return (
    <div className="flex items-end gap-2">
      {/* 模式切换按钮 */}
      {onModeToggle && (
        <button
          onClick={onModeToggle}
          className="shrink-0 p-2 text-gray-400 hover:text-gray-200 transition-colors rounded-lg hover:bg-gray-800/50"
          title={mode === 'chat' ? '切换到命令模式' : '切换到聊天模式'}
        >
          <IconPlus className="w-5 h-5" />
        </button>
      )}

      {/* 输入框 */}
      <div className="flex-1">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || (mode === 'chat' ? '输入你的问题...' : '输入命令...')}
          rows={1}
          disabled={disabled}
          className="w-full resize-none bg-gray-800/50 border border-gray-700/30 rounded-xl px-4 py-2.5 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500/40 disabled:opacity-50 transition-colors"
        />
      </div>

      {/* 发送按钮 */}
      <V3Button
        variant="primary"
        size="md"
        onClick={handleSend}
        disabled={disabled || loading || !value.trim()}
        loading={loading}
        icon={<IconSend className="w-4 h-4" />}
      >
        发送
      </V3Button>
    </div>
  );
}

export default ChatInput;
