'use client';

import { useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { useClassicStore } from '@/stores';
import { GenerationPanel } from '@/components/features/classic/GenerationPanel';
import { ManagementPanel } from '@/components/features/classic/ManagementPanel';
import { GovernancePanelEnhanced } from '@/components/features/classic/GovernancePanelEnhanced';
import { SignalsPanel } from '@/components/features/classic/SignalsPanel';

const VALID_SUBTABS = ['generation', 'management', 'governance', 'signals'] as const;
type SubTab = (typeof VALID_SUBTABS)[number];

export default function ClassicSubTabPage() {
  const router = useRouter();
  const params = useParams();
  const subtab = params?.subtab as SubTab;
  const setActivePhase = useClassicStore((s) => s.setActivePhase);

  useEffect(() => {
    if (!VALID_SUBTABS.includes(subtab as SubTab)) {
      router.replace('/dashboard/classic/generation');
    }
  }, [subtab, router]);

  useEffect(() => {
    if (subtab === 'governance') {
      setActivePhase('C0');
    }
  }, [subtab, setActivePhase]);

  if (!VALID_SUBTABS.includes(subtab as SubTab)) {
    return <div className="text-slate-500 text-center py-8">跳转中...</div>;
  }

  switch (subtab) {
    case 'generation':
      return <GenerationPanel />;
    case 'management':
      return <ManagementPanel />;
    case 'governance':
      return <GovernancePanelEnhanced />;
    case 'signals':
      return <SignalsPanel />;
    default:
      return null;
  }
}
