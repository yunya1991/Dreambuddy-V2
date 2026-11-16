// 统计能力目录 / 预检 / 执行的前端客户端（TASKS-20261116 T2-1 / T2-3 / T8-1）
// 原则：前端零计算，一切数值都来自 capability_result 信封。

import type { VisualSpec } from '@/components/visual/types';

export interface CapabilityItem {
  capability_id: string;
  domain: string;
  intent: string;
  mode: string;
  min_n: number | null;
  min_span_days?: number | null;
  methods: string[];
  data_scope: string[];
  visibility?: string;
  notes?: string;
}

export interface CapabilityListResponse {
  ok: boolean;
  manifest_version?: number;
  manifest_updated?: string;
  total?: number;
  returned?: number;
  domains?: { domain: string; count: number }[];
  items?: CapabilityItem[];
  degraded?: boolean;
  error?: string;
}

export interface CapabilityQuality {
  status?: string;
  sample_n?: number | null;
  degraded_reason?: string | null;
  sources?: string[];
  [key: string]: unknown;
}

export interface CapabilityEnvelope {
  ok?: boolean;
  capability?: string;
  intent?: string;
  answer?: string | null;
  data?: Record<string, unknown>;
  visual?: VisualSpec | null;
  quality?: CapabilityQuality | null;
  [key: string]: unknown;
}

export interface ValidateResponse {
  ok: boolean;
  capability_id?: string;
  missing_params?: string[];
  unknown_params?: string[];
  warnings?: string[];
  min_n?: number;
  degraded?: boolean;
  reason?: string;
}

export interface RunResponse {
  ok: boolean;
  capability_id?: string;
  result?: CapabilityEnvelope;
  degraded?: boolean;
  reason?: string;
}

export interface ListParams {
  domain?: string;
  q?: string;
  limit?: number;
  min_n_max?: number;
}

export async function listCapabilities(params: ListParams = {}): Promise<CapabilityListResponse> {
  const search = new URLSearchParams();
  if (params.domain) search.set('domain', params.domain);
  if (params.q) search.set('q', params.q);
  if (params.limit) search.set('limit', String(params.limit));
  if (params.min_n_max !== undefined) search.set('min_n_max', String(params.min_n_max));
  const response = await fetch(`/api/visual/capabilities?${search.toString()}`, {
    cache: 'no-store',
  });
  return (await response.json()) as CapabilityListResponse;
}

async function post(body: Record<string, unknown>): Promise<any> {
  const response = await fetch('/api/visual/capabilities', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  return response.json();
}

export async function validateCapability(
  capabilityId: string,
  payload: Record<string, unknown> = {},
): Promise<ValidateResponse> {
  return (await post({ op: 'validate', capability_id: capabilityId, payload })) as ValidateResponse;
}

export async function explainCapability(capabilityId: string): Promise<CapabilityItem & {
  ok?: boolean;
  accepted_params?: string[];
  accepts_extra?: boolean;
  executable?: boolean;
  degraded?: boolean;
  reason?: string;
}> {
  return post({ op: 'explain', capability_id: capabilityId });
}

export async function runCapability(
  capabilityId: string,
  payload: Record<string, unknown> = {},
): Promise<RunResponse> {
  return (await post({ op: 'run', capability_id: capabilityId, payload })) as RunResponse;
}
