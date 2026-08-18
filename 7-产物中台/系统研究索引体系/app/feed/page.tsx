import { getArtifactsIndex, getArtifactsData } from '@/lib/content.server';
import FeedClient from './FeedClient';

export const dynamic = 'force-dynamic';

export default function FeedPage() {
  // Server-side data loading — reads latest data on every request
  const artifactsIndex = getArtifactsIndex();
  const artifactsData = getArtifactsData();

  // Compute department counts for the filter bar
  const deptCounts: Record<string, number> = { all: artifactsIndex.length };
  for (const a of artifactsIndex) {
    deptCounts[a.department] = (deptCounts[a.department] || 0) + 1;
  }

  // Compute A0-A9 phase counts (cross-department)
  const phaseCounts: Record<string, number> = {};
  for (const a of artifactsIndex) {
    const p = a.chainPhase;
    if (p) phaseCounts[p] = (phaseCounts[p] || 0) + 1;
  }

  const knowledgeCounts: Record<string, number> = {};
  for (const a of artifactsIndex) {
    if (a.department !== 'knowledge') continue;
    for (const tag of a.tags) {
      knowledgeCounts[tag] = (knowledgeCounts[tag] || 0) + 1;
    }
  }

  return (
    <FeedClient
      artifacts={artifactsIndex}
      deptCounts={deptCounts}
      phaseCounts={phaseCounts}
      knowledgeCounts={knowledgeCounts}
      totalArtifacts={artifactsData.total}
    />
  );
}
