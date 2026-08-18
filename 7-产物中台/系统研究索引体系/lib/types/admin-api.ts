export interface ApiMeta {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

export interface ApiSuccess<T> {
  success: true;
  data: T;
  message?: string;
  meta?: ApiMeta;
}

export interface ApiError {
  success: false;
  data: null;
  error: string;
  message?: string;
}

export type ApiResponse<T> = ApiSuccess<T> | ApiError;

export function apiSuccess<T>(
  data: T,
  opts: { message?: string; meta?: ApiMeta } = {},
): ApiSuccess<T> {
  return { success: true, data, ...opts };
}

export function apiError(error: string, message?: string): ApiError {
  return { success: false, data: null, error, message };
}

export function calculateMeta(
  total: number,
  page: number,
  pageSize: number,
): ApiMeta {
  return {
    page,
    pageSize,
    total,
    totalPages: Math.max(1, Math.ceil(total / pageSize)),
  };
}

export interface ListQuery {
  page: number;
  pageSize: number;
  search?: string;
  sort?: string;
  order?: "asc" | "desc";
  status?: string;
  type?: string;
  uid?: string;
  strategyId?: string;
}

export function parseListQuery(
  url: URL,
  defaults: { pageSize: number } = { pageSize: 20 },
): ListQuery {
  const page = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10) || 1);
  const pageSize = Math.min(
    100,
    Math.max(1, parseInt(url.searchParams.get("pageSize") || String(defaults.pageSize), 10) || defaults.pageSize),
  );
  return {
    page,
    pageSize,
    search: url.searchParams.get("search") || undefined,
    sort: url.searchParams.get("sort") || undefined,
    order: (url.searchParams.get("order") as "asc" | "desc") || "desc",
    status: url.searchParams.get("status") || undefined,
    type: url.searchParams.get("type") || undefined,
    uid: url.searchParams.get("uid") || undefined,
    strategyId: url.searchParams.get("strategyId") || undefined,
  };
}
