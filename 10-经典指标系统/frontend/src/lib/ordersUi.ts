
import { getUiEnv } from './api';

export type OrdersUiDefaults = {
  showShadow: boolean;
  showSimulated: boolean;
};

export const getOrdersUiDefaults = (): OrdersUiDefaults => {
  const isExplore = getUiEnv() === 'explore';
  return { showShadow: isExplore, showSimulated: isExplore };
};

export const isOrderSimulatedLike = (o: unknown): boolean => {
  const mode0 = String((o as { mode?: unknown } | null | undefined)?.mode ?? '').toLowerCase().trim();
  const execAny = (o as { exec?: unknown } | null | undefined)?.exec as { execute?: unknown } | undefined;
  const execFlag = typeof execAny?.execute === 'boolean' ? execAny.execute : undefined;
  if (execFlag === false) return true;
  if (!mode0) return false;
  if (mode0.includes('dry') || mode0.includes('paper') || mode0.includes('sim')) return true;
  return false;
};

export const isOrderShadowLike = (o: unknown): boolean => {
  const status0 = String((o as { status?: unknown } | null | undefined)?.status ?? '').toLowerCase().trim();
  if (status0 === 'observed') return true;
  const shadow = (o as { shadow?: unknown } | null | undefined)?.shadow;
  if (shadow === true) return true;
  return false;
};

export const filterOrdersForUi = <T>(
  rows: T[],
  opts: { showShadow: boolean; showSimulated: boolean }
): T[] => {
  let out = rows;
  if (!opts.showShadow) out = out.filter((o) => !isOrderShadowLike(o));
  if (!opts.showSimulated) out = out.filter((o) => !isOrderSimulatedLike(o));
  return out;
};
