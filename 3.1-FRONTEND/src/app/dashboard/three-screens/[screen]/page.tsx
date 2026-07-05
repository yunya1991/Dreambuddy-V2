'use client';

import { useParams } from 'next/navigation';
import { Screen1Panel } from '@/components/features/three-screens/Screen1Panel';
import { Screen2Panel } from '@/components/features/three-screens/Screen2Panel';
import { Screen3Panel } from '@/components/features/three-screens/Screen3Panel';

export default function ScreenDetailPage() {
  const params = useParams();
  const screen = params.screen as string;

  if (screen === 'screen1') return <div className="p-6"><Screen1Panel /></div>;
  if (screen === 'screen2') return <div className="p-6"><Screen2Panel /></div>;
  if (screen === 'screen3') return <div className="p-6"><Screen3Panel /></div>;

  return <div className="p-6"><p className="text-sm text-slate-500">未知 Screen</p></div>;
}
