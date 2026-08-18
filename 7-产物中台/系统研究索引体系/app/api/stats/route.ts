import { NextResponse } from 'next/server';
import { getArtifactsData } from '@/lib/content.server';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const data = getArtifactsData();

    // Extract just the statistics
    const stats = {
      total: data.total,
      departments: Object.keys(data.statistics.by_department).length,
      by_department: data.statistics.by_department,
      by_type: data.statistics.by_type,
      by_status: data.statistics.by_status,
    };

    return NextResponse.json(stats);
  } catch (error) {
    console.error('Stats API error:', error);
    return NextResponse.json({ total: 0, departments: 0, error: 'Failed to load stats' }, { status: 500 });
  }
}
