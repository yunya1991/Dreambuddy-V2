import { notFound } from 'next/navigation';
import archMap from '@/data/arch-map/arch-map.json';
import capMap from '@/data/arch-map/cap-map.json';
import { ArchMapView } from '@/components/features/arch-map/ArchMapView';
import type { ArchMapData, CapMapData } from '@/lib/arch-map/types';

/**
 * /dev/arch-map — 架构工程地图（仅开发阶段）
 * 生产环境默认 404；如需在生产预览，显式设置 NEXT_PUBLIC_ARCH_MAP=1。
 */
export const dynamic = 'force-dynamic';

export default function ArchMapPage() {
  if (process.env.NODE_ENV === 'production' && process.env.NEXT_PUBLIC_ARCH_MAP !== '1') {
    notFound();
  }
  return (
    <ArchMapView data={archMap as unknown as ArchMapData} capMap={capMap as unknown as CapMapData} />
  );
}
