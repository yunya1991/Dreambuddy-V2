export const ERROR_REASON_ZH: Record<string, string> = {
  ok: '正常',
  timeout: '连接超时',
  unauthorized: '鉴权失败',
  remote_egress_disabled: '外发关闭',
  invalid_remote_provider: '远端提供方无效',
  unsupported_provider: '不支持的提供方',
  provider_disabled: '提供方已禁用',
  missing_provider_or_model: '缺少提供方或模型',
  empty_content: '响应为空',
  parsed_not_object: '响应格式错误',
  schema_invalid: '响应结构无效',
};

export const toErrorReasonZh = (reasonRaw: unknown): string => {
  const reason = String(reasonRaw ?? '').trim().toLowerCase();
  if (!reason) return '未知';
  return ERROR_REASON_ZH[reason] || `未知错误(${reason})`;
};
