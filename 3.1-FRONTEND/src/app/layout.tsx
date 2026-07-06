import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'DreamBuddy v3 — AI Trading OS',
  description: 'SACG 四层 AI 交易操作系统',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh" className="dark">
      <body className="min-h-screen bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] antialiased">
        {children}
      </body>
    </html>
  );
}
