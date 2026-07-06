'use client';

// Inline SVG icon components (no external dependency)
function IconMessageSquare({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}
function IconLayoutGrid({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
    </svg>
  );
}
function IconCompass({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
    </svg>
  );
}
function IconActivity({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}
function IconDatabase({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" /><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  );
}
function IconImageDown({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.5 4.5L15 9l-4.5 4.5" /><path d="M15 9H3" /><rect x="3" y="2" width="18" height="20" rx="2" /><path d="M3 18l6-6 3 3 4-4 4 4" />
    </svg>
  );
}
function IconWorkflow({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" /><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
  );
}
function IconSettings({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

const mainNavItems = [
  { id: 'chat', label: '对话交易', Icon: IconMessageSquare },
  { id: 'classic', label: '经典交易体系', Icon: IconLayoutGrid },
  { id: 'fundamental', label: '基本面分析', Icon: IconCompass },
] as const;

const secondaryNavItems = [
  { id: 'monitor', label: '系统监控', Icon: IconActivity },
  { id: 'memory', label: '记忆库', Icon: IconDatabase },
  { id: 'image-compress', label: '图压缩', Icon: IconImageDown },
  { id: 'workflow', label: '编排', Icon: IconWorkflow },
] as const;

interface SidebarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
}

export default function Sidebar({ activeTab, onTabChange }: SidebarProps) {
  return (
    <aside
      className="w-[260px] h-screen flex flex-col shrink-0"
      style={{
        background: 'var(--bg-secondary, #111827)',
        borderRight: '1px solid var(--border-default, #1e293b)',
      }}
    >
      {/* Logo area */}
      <div className="py-5 px-5">
        <div className="flex items-center gap-2">
          <span
            className="inline-block w-2 h-2 rounded-full bg-[#3b82f6]"
            aria-hidden="true"
          />
          <span className="text-[16px] font-bold text-[#f1f5f9]">Dream Gateway</span>
        </div>
        <p className="mt-1 text-[10px] text-[#64748b]">智能交易策略平台</p>
      </div>

      {/* Main navigation */}
      <nav className="py-3 px-3 flex-1 overflow-y-auto">
        <ul className="flex flex-col gap-0.5">
          {mainNavItems.map(({ id, label, Icon }) => {
            const isActive = activeTab === id;
            return (
              <li key={id}>
                <button
                  onClick={() => onTabChange(id)}
                  className={`
                    w-full h-9 flex items-center gap-3 px-3 rounded-md text-[13px]
                    transition-colors duration-150 cursor-pointer
                    ${
                      isActive
                        ? 'bg-[rgba(59,130,246,0.1)] text-[#3b82f6] border-l-2 border-[#3b82f6]'
                        : 'text-[#94a3b8] hover:bg-[rgba(255,255,255,0.03)] hover:text-[#f1f5f9] border-l-2 border-transparent'
                    }
                  `}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{label}</span>
                </button>
              </li>
            );
          })}
        </ul>

        {/* Divider */}
        <div className="border-t border-[#1e293b] mx-3 my-3" />

        {/* Secondary navigation */}
        <ul className="flex flex-col gap-0.5">
          {secondaryNavItems.map(({ id, label, Icon }) => (
            <li key={id}>
              <button
                className="w-full h-9 flex items-center gap-3 px-3 rounded-md text-[13px] text-[#64748b] hover:bg-[rgba(255,255,255,0.03)] hover:text-[#94a3b8] border-l-2 border-transparent transition-colors duration-150 cursor-pointer"
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span>{label}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* User section */}
      <div className="border-t border-[#1e293b] p-3 mt-auto">
        <div className="flex items-center gap-3">
          <span className="w-7 h-7 rounded-full bg-[#1e293b] text-[#94a3b8] text-[11px] flex items-center justify-center font-medium shrink-0">
            A
          </span>
          <span className="text-[12px] font-medium text-[#f1f5f9] flex-1 truncate">
            Analyst
          </span>
          <button className="text-[#64748b] hover:text-[#94a3b8] transition-colors duration-150 cursor-pointer">
            <IconSettings className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
