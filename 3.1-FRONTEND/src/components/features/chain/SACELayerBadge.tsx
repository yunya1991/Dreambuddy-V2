'use client';

import React from 'react';
import { V3Badge } from '@/components/V3Badge';

type SACGLayer = 'S' | 'A' | 'C' | 'G';

interface SACELayerBadgeProps {
  layer: SACGLayer;
  label?: string;
  pulse?: boolean;
}

const layerLabels: Record<SACGLayer, string> = {
  S: '感知层',
  A: '编排层',
  C: '执行层',
  G: '存储层',
};

const layerVariants: Record<SACGLayer, 'sacg-s' | 'sacg-a' | 'sacg-c' | 'sacg-g'> = {
  S: 'sacg-s',
  A: 'sacg-a',
  C: 'sacg-c',
  G: 'sacg-g',
};

export function SACELayerBadge({ layer, label, pulse = false }: SACELayerBadgeProps) {
  return (
    <V3Badge variant={layerVariants[layer]} dot pulse={pulse}>
      {label || layerLabels[layer]}
    </V3Badge>
  );
}

export default SACELayerBadge;
