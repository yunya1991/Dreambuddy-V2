'use client';

import { ChatPanel } from '@/components/features/chat/ChatPanel';
import { SteerPanel } from '@/components/features/chat/SteerPanel';
import { V3StatusDot } from '@/components';

export default function ChatPage() {
  return (
    <div className="flex h-screen flex-col bg-[var(--color-bg-primary)]">
      <header className="flex items-center justify-between border-b border-slate-800 px-6 py-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-indigo-400">DreamBuddy Chat</span>
          <V3StatusDot status="success" size="sm" label="在线" />
        </div>
      </header>
      <main className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-hidden">
          <ChatPanel />
        </div>
        <aside className="w-72 border-l border-slate-800 p-3 overflow-y-auto hidden lg:block">
          <SteerPanel />
        </aside>
      </main>
    </div>
  );
}
