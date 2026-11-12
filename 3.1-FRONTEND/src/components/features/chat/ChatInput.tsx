'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { V3Button, IconSend, IconPlus } from '@/components';

export interface ChatInputSuggestion {
  label: string;
  value: string;
  hint?: string;
}

interface ChatInputProps {
  /** 当前输入值 */
  value: string;
  /** 输入值变更回调 */
  onChange: (value: string) => void;
  /** 发送回调（T-B9：可选携带附件文件名，不上传） */
  onSend: (attachments?: string[]) => void;
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
  /** T-B9：停止生成（loading 时显示停止入口） */
  onStop?: () => void;
  /** T-B9：重生成最后一条回复 */
  onRegenerate?: () => void;
  /** T-B9：草稿自动保存 key（sessionStorage）；不传则不启用 */
  draftKey?: string;
  /** T-B9：输入历史 key（上/下键，最多 50 条）；不传则不启用 */
  historyKey?: string;
  /** T-B9：`@` 候选（技能 / Agent）；不传则不启用 */
  suggestions?: ChatInputSuggestion[];
  /** T-B9：附件选择回调（仅文件名，不做上传） */
  onAttachFiles?: (names: string[]) => void;
}

const DRAFT_PREFIX = 'dreambuddy.chat.draft:';
const HISTORY_PREFIX = 'dreambuddy.chat.history:';
const MAX_HISTORY = 50;
const MAX_SUGGESTIONS = 8;
const AT_PATTERN = /@([\w\u4e00-\u9fa5-]*)$/;

function readDraft(key: string): string {
  try {
    return sessionStorage.getItem(DRAFT_PREFIX + key) || '';
  } catch {
    return '';
  }
}

function writeDraft(key: string, value: string): void {
  try {
    sessionStorage.setItem(DRAFT_PREFIX + key, value);
  } catch {
    /* 配额/隐私模式：静默降级 */
  }
}

function clearDraft(key: string): void {
  try {
    sessionStorage.removeItem(DRAFT_PREFIX + key);
  } catch {
    /* noop */
  }
}

function readHistory(key: string): string[] {
  try {
    const raw = sessionStorage.getItem(HISTORY_PREFIX + key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    return [];
  }
}

function pushHistory(key: string, value: string): void {
  const text = value.trim();
  if (!text) return;
  try {
    const history = readHistory(key).filter((v) => v !== text);
    history.push(text);
    sessionStorage.setItem(HISTORY_PREFIX + key, JSON.stringify(history.slice(-MAX_HISTORY)));
  } catch {
    /* noop */
  }
}

/**
 * ChatInput — 聊天输入组件
 *
 * 从 ChatPanel 中拆分，可独立使用。
 * 基线行为（交易域）：Enter 发送 / Shift+Enter 换行 / 模式切换（chat / command）。
 * T-B9 增强项全部为可选 props：不传时行为与基线完全一致。
 */
export function ChatInput({
  value, onChange, onSend, disabled = false, loading = false,
  mode = 'chat', onModeToggle, placeholder,
  onStop, onRegenerate, draftKey, historyKey, suggestions, onAttachFiles,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  const [historyCursor, setHistoryCursor] = useState<number | null>(null);
  const draftBeforeHistory = useRef('');

  // 草稿恢复（仅首次挂载 / 切换 draftKey）
  useEffect(() => {
    if (!draftKey) return;
    const saved = readDraft(draftKey);
    if (saved) onChange(saved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);

  // 草稿自动保存
  useEffect(() => {
    if (!draftKey) return;
    writeDraft(draftKey, value);
  }, [draftKey, value]);

  const canSend = value.trim().length > 0 && !disabled && !loading;

  const doSend = useCallback(() => {
    if (!canSend) return;
    if (historyKey) pushHistory(historyKey, value);
    if (draftKey) clearDraft(draftKey);
    setHistoryCursor(null);
    const names = attachments.map((a) => a);
    setAttachments([]);
    onSend(names.length > 0 ? names : undefined);
  }, [canSend, historyKey, value, draftKey, attachments, onSend]);

  // @ 候选：值以 @token 结尾时展示
  const atMatch = suggestions ? AT_PATTERN.exec(value) : null;
  const suggestionQuery = atMatch ? atMatch[1].toLowerCase() : null;
  const visibleSuggestions =
    suggestions && suggestionQuery !== null
      ? suggestions
          .filter(
            (s) =>
              s.label.toLowerCase().includes(suggestionQuery) ||
              s.value.toLowerCase().includes(suggestionQuery),
          )
          .slice(0, MAX_SUGGESTIONS)
      : [];

  const insertSuggestion = useCallback(
    (suggestion: ChatInputSuggestion) => {
      const next = AT_PATTERN.test(value)
        ? value.replace(AT_PATTERN, `${suggestion.value} `)
        : `${value}${suggestion.value} `;
      onChange(next);
      setSuggestionIndex(0);
      textareaRef.current?.focus();
    },
    [value, onChange],
  );

  const navigateHistory = useCallback(
    (direction: -1 | 1) => {
      if (!historyKey) return;
      const history = readHistory(historyKey);
      if (history.length === 0) return;
      if (historyCursor === null && direction === 1) return;
      if (historyCursor === null) draftBeforeHistory.current = value;
      const next = historyCursor === null ? history.length - 1 : historyCursor + direction;
      if (next < 0) return;
      if (next >= history.length) {
        setHistoryCursor(null);
        onChange(draftBeforeHistory.current);
        return;
      }
      setHistoryCursor(next);
      onChange(history[next]);
    },
    [historyKey, historyCursor, value, onChange],
  );

  // 键盘快捷键处理
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (visibleSuggestions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSuggestionIndex((i) => Math.min(i + 1, visibleSuggestions.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSuggestionIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        insertSuggestion(visibleSuggestions[Math.min(suggestionIndex, visibleSuggestions.length - 1)]);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        // 关闭候选：删除尾部 @token 的触发态
        onChange(value.replace(/@([\w\u4e00-\u9fa5-]*)$/, ''));
        return;
      }
    }

    if (!suggestions && historyKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      navigateHistory(e.key === 'ArrowUp' ? -1 : 1);
      return;
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const names = Array.from(e.target.files ?? []).map((f) => f.name);
    if (names.length === 0) return;
    const next = Array.from(new Set([...attachments, ...names])).slice(0, 10);
    setAttachments(next);
    onAttachFiles?.(next);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="flex flex-col gap-2">
      {visibleSuggestions.length > 0 && (
        <div
          data-testid="chat-input-suggestions"
          role="listbox"
          className="rounded-lg border border-gray-700/40 bg-gray-900/95 overflow-hidden"
        >
          {visibleSuggestions.map((s, i) => (
            <button
              key={`${s.value}-${i}`}
              role="option"
              aria-selected={i === suggestionIndex}
              onMouseDown={(e) => {
                e.preventDefault();
                insertSuggestion(s);
              }}
              onMouseEnter={() => setSuggestionIndex(i)}
              className={`w-full text-left px-3 py-1.5 text-xs transition-colors ${
                i === suggestionIndex ? 'bg-indigo-600/25 text-indigo-200' : 'text-gray-300 hover:bg-gray-800'
              }`}
            >
              <span className="font-medium">{s.label}</span>
              {s.hint && <span className="ml-2 text-[10px] text-gray-500">{s.hint}</span>}
            </button>
          ))}
        </div>
      )}

      {attachments.length > 0 && (
        <div data-testid="chat-input-attachments" className="flex flex-wrap gap-1.5">
          {attachments.map((name) => (
            <span
              key={name}
              className="inline-flex items-center gap-1 rounded bg-gray-800 px-2 py-0.5 text-[11px] text-gray-300"
            >
              {name}
              <button
                type="button"
                aria-label={`移除附件 ${name}`}
                onClick={() => setAttachments((prev) => prev.filter((n) => n !== name))}
                className="text-gray-500 hover:text-gray-300"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

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

        {/* 附件选择（仅文件名引用，不上传） */}
        {onAttachFiles && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".txt,.md,.json,.csv,.log"
              data-testid="chat-input-file"
              className="hidden"
              onChange={handleFileChange}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="shrink-0 p-2 text-gray-400 hover:text-gray-200 transition-colors rounded-lg hover:bg-gray-800/50"
              title="引用文本附件（仅文件名，不上传）"
            >
              附件
            </button>
          </>
        )}

        {/* 输入框 */}
        <div className="flex-1">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              setHistoryCursor(null);
              onChange(e.target.value);
            }}
            onKeyDown={handleKeyDown}
            placeholder={placeholder || (mode === 'chat' ? '输入你的问题...' : '输入命令...')}
            rows={1}
            disabled={disabled}
            className="w-full resize-none bg-gray-800/50 border border-gray-700/30 rounded-xl px-4 py-2.5 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500/40 disabled:opacity-50 transition-colors"
          />
        </div>

        {onRegenerate && !loading && (
          <button
            type="button"
            onClick={onRegenerate}
            disabled={disabled}
            className="shrink-0 px-2 py-2 text-[11px] text-gray-400 hover:text-gray-200 disabled:opacity-40"
            title="重新生成最后一条回复"
          >
            重生成
          </button>
        )}

        {/* 停止 / 发送 */}
        {loading && onStop ? (
          <button
            type="button"
            onClick={onStop}
            data-testid="chat-input-stop"
            className="shrink-0 px-3 py-2 rounded-lg bg-red-600/20 border border-red-500/40 text-xs text-red-300 hover:bg-red-600/30 transition-colors"
          >
            停止
          </button>
        ) : (
          <V3Button
            variant="primary"
            size="md"
            onClick={doSend}
            disabled={!canSend}
            loading={loading}
            icon={<IconSend className="w-4 h-4" />}
          >
            发送
          </V3Button>
        )}
      </div>
    </div>
  );
}

export default ChatInput;
