'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import type { ChatMessage } from '@/types';
import { IconCopy } from '@/components';
import { ClarifyCard, tryParseClarify } from './ClarifyCard';

interface MessageItemProps {
  /** 消息数据 */
  message: ChatMessage;
  /** 是否为最后一条 assistant 消息（用于显示流式内容） */
  isLast?: boolean;
  /** 当前流式输出内容 */
  streamingContent?: string;
  /** 用户在 clarify 卡片中选择了某个选项 */
  onSelectClarifyOption?: (optionKey: string, optionLabel: string) => void;
}

/**
 * MessageItem — 单条消息组件
 *
 * 支持 user / assistant / system 三种角色。
 * - user: 右对齐蓝色气泡
 * - assistant: 左对齐灰色气泡 + AI 头像；检测 clarify JSON 时渲染为交互卡片
 * - system: 居中灰色标签
 *
 * 悬浮时显示时间戳和复制按钮。
 */
export function MessageItem({ message, isLast, streamingContent, onSelectClarifyOption }: MessageItemProps) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  // 复制消息内容到剪贴板
  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
  };

  // 格式化时间戳（HH:mm）
  const formatTime = (ts: number) => {
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  };

  // 系统消息：居中标签样式
  if (isSystem) {
    return (
      <div className="flex justify-center py-1">
        <span className="text-xs text-gray-500 bg-gray-800/30 px-3 py-1 rounded-full">
          {message.content}
        </span>
      </div>
    );
  }

  // assistant 消息：检测 clarify JSON
  const clarifyData = !isUser ? tryParseClarify(message.content) : null;

  return (
    <div className={`group flex ${isUser ? 'justify-end' : 'justify-start'} gap-2`}>
      {/* AI 头像（仅 assistant 消息） */}
      {!isUser && (
        <div className="shrink-0 w-7 h-7 rounded-lg bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-xs font-bold text-white mt-0.5">
          AI
        </div>
      )}

      <div className={`max-w-[80%] ${isUser ? 'order-first' : ''}`}>
        {/* 消息气泡 */}
        <div className={`
          rounded-xl px-4 py-2.5 text-sm leading-relaxed
          ${isUser
            ? 'bg-blue-600/20 text-blue-100 border border-blue-500/20 rounded-br-sm'
            : clarifyData
              ? 'bg-transparent border-0 p-0' // clarify 卡片自带样式，去掉气泡背景
              : 'bg-gray-800/60 text-gray-200 border border-gray-700/30 rounded-bl-sm'}
        `}>
          {isUser ? (
            <span>{message.content}</span>
          ) : clarifyData ? (
            <ClarifyCard
              data={clarifyData}
              onSelectOption={(key, label) => onSelectClarifyOption?.(key, label)}
              disabled={isLast && !!streamingContent}
            />
          ) : (
            <div className="markdown-body [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_p]:my-1 [&_ul]:my-1 [&_li]:my-0.5 [&_h1]:text-base [&_h2]:text-base [&_h3]:text-sm [&_blockquote]:border-l-2 [&_blockquote]:border-gray-500/50 [&_blockquote]:pl-3 [&_blockquote]:text-gray-300">
              <ReactMarkdown>{message.content || ''}</ReactMarkdown>
            </div>
          )}
          {/* 最后一条 assistant 消息追加流式内容 */}
          {isLast && streamingContent && !clarifyData && (
            <div className="markdown-body mt-1 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_p]:my-1 [&_ul]:my-1 [&_li]:my-0.5">
              <ReactMarkdown>{streamingContent}</ReactMarkdown>
            </div>
          )}
        </div>

        {/* 悬浮操作栏：时间戳 + 复制按钮（clarify 卡片不显示复制） */}
        {!clarifyData && (
          <div className={`flex items-center gap-2 mt-1 ${isUser ? 'justify-end' : 'justify-start'} opacity-0 group-hover:opacity-100 transition-opacity`}>
            <span className="text-[10px] text-gray-500">{formatTime(message.timestamp)}</span>
            {!isUser && message.content && (
              <button onClick={handleCopy} className="text-gray-500 hover:text-gray-300">
                <IconCopy className="w-3 h-3" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default MessageItem;
