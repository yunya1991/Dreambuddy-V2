// SPEC-52 F5/F7 — 插件市场客户端
import { api } from '@/lib/api-client';

export type PluginGroup = 'own' | 'official' | 'community';

export interface PluginItem {
  id: string;
  source: string;
  version: string;
  status: 'approved' | 'candidate' | 'forbidden';
  owner: string;
  riskLevel: string;
  securityScanned: boolean;
  sandboxVerified: boolean;
  failOpenVerified: boolean;
  permittedProfiles: string[];
  notes: string;
  group: PluginGroup;
  permissions: string[];
  enabled: boolean;
  enabledProfile: string | null;
  enabledAt: string | null;
  enableable: boolean;
  rejectReason: string | null;
}

export interface PluginListData {
  items: PluginItem[];
  counts: Record<PluginGroup, number>;
  product_entitled: boolean;
}

export interface PluginAuditRecord {
  id: string;
  plugin_id: string;
  action: 'enable' | 'disable' | 'reject';
  result: 'ok' | 'denied';
  profile: string;
  trace_id: string;
  created_at: string;
}

export interface InstalledDshPlugin {
  name: string;
  spec: string;
  installed: boolean;
  is_core: boolean;
  in_bundles: boolean;
  whitelist: { status: string; group: string; permitted_profiles: string[] } | null;
}

export interface DshProfileInfo {
  profile: string;
  home: string;
  dir: string;
  exists: boolean;
  bundles: string[];
  dependencies: Record<string, string>;
  installed: InstalledDshPlugin[];
  installable_profiles: string[];
}

export const dshPlugins = {
  profile: (profile = 'sandbox') =>
    api.get<DshProfileInfo>(`/api/dsh/plugins?profile=${encodeURIComponent(profile)}`),
  install: (id: string, profile = 'sandbox') =>
    api.post<DshProfileInfo>('/api/dsh/plugins/install', { id, profile }),
  uninstall: (id: string, profile = 'sandbox') =>
    api.post<DshProfileInfo>('/api/dsh/plugins/uninstall', { id, profile }),
};

export const plugins = {
  list: () => api.get<PluginListData>('/api/plugins'),
  // scoped 包名含 `/`：逐段编码但保留分隔符，交由 catch-all 路由还原
  setEnabled: (id: string, enabled: boolean, profile = 'sandbox') =>
    api.post<PluginItem>(
      `/api/plugins/${id.split('/').map(encodeURIComponent).join('/')}/enable`,
      { enabled, profile },
    ),
  audit: (limit = 50) => api.get<PluginAuditRecord[]>(`/api/plugins/audit?limit=${limit}`),
};

export default plugins;
