
import { useEffect, useMemo, useState } from 'react';
import { getUiEnv } from './api';
import { getOrdersUiDefaults, type OrdersUiDefaults } from './ordersUi';

type OrdersUiPrefs = Partial<OrdersUiDefaults>;

const _storageKey = (scope: string): string => {
  const env = getUiEnv();
  const s = String(scope || '').trim() || 'default';
  return `${env}_orders_ui_prefs_v1:${s}`;
};

const _loadPrefs = (key: string): OrdersUiPrefs | null => {
  try {
    if (typeof window === 'undefined') return null;
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const obj = JSON.parse(raw) as Record<string, unknown>;
    if (!obj || typeof obj !== 'object') return null;
    const out: OrdersUiPrefs = {};
    if (typeof obj.showShadow === 'boolean') out.showShadow = obj.showShadow;
    if (typeof obj.showSimulated === 'boolean') out.showSimulated = obj.showSimulated;
    return out;
  } catch {
    return null;
  }
};

const _savePrefs = (key: string, prefs: OrdersUiPrefs): void => {
  try {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(key, JSON.stringify(prefs));
  } catch {
    void 0;
  }
};

export const useOrdersUiPrefs = (opts?: { scope?: string; defaults?: OrdersUiPrefs }) => {
  const scope = String(opts?.scope ?? 'default').trim() || 'default';
  const key = useMemo(() => _storageKey(scope), [scope]);

  const baseDefaults = useMemo(() => {
    const d = getOrdersUiDefaults();
    const o = opts?.defaults ?? {};
    return {
      showShadow: typeof o.showShadow === 'boolean' ? o.showShadow : d.showShadow,
      showSimulated: typeof o.showSimulated === 'boolean' ? o.showSimulated : d.showSimulated,
    };
  }, [opts?.defaults]);

  const [showShadow, setShowShadow] = useState<boolean>(() => {
    const saved = _loadPrefs(key);
    return typeof saved?.showShadow === 'boolean' ? saved.showShadow : baseDefaults.showShadow;
  });
  const [showSimulated, setShowSimulated] = useState<boolean>(() => {
    const saved = _loadPrefs(key);
    return typeof saved?.showSimulated === 'boolean' ? saved.showSimulated : baseDefaults.showSimulated;
  });

  useEffect(() => {
    _savePrefs(key, { showShadow, showSimulated });
  }, [key, showShadow, showSimulated]);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (!e || e.key !== key) return;
      const saved = _loadPrefs(key);
      if (!saved) return;
      if (typeof saved.showShadow === 'boolean') setShowShadow(saved.showShadow);
      if (typeof saved.showSimulated === 'boolean') setShowSimulated(saved.showSimulated);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [key]);

  return { showShadow, setShowShadow, showSimulated, setShowSimulated };
};

