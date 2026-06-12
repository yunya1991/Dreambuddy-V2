import Link from "next/link";
import { getStatusLabel, getStatusBadgeClass } from "../../lib/utils/admin-format";

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => React.ReactNode;
  href?: (row: T) => string;
  className?: string;
  align?: "left" | "right" | "center";
}

interface AdminTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  emptyMessage?: string;
  title?: string;
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
}

export function AdminTable<T>({
  columns,
  rows,
  rowKey,
  emptyMessage = "暂无数据",
  title,
  total,
  page,
  pageSize,
  onPageChange,
}: AdminTableProps<T>) {
  const totalPages = total && pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      {title && (
        <div className="px-6 py-3 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
          {total !== undefined && (
            <span className="text-xs text-gray-500">共 {total} 条记录</span>
          )}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wider ${
                    col.align === "right"
                      ? "text-right"
                      : col.align === "center"
                        ? "text-center"
                        : "text-left"
                  } ${col.className || ""}`}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-12 text-center text-gray-400">
                  <div className="text-3xl mb-2">📭</div>
                  <div className="text-sm">{emptyMessage}</div>
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={rowKey(row)} className="hover:bg-gray-50 transition-colors">
                  {columns.map((col) => {
                    const content = col.render
                      ? col.render(row)
                      : ((row as unknown) as Record<string, unknown>)[col.key];
                    const href = col.href ? col.href(row) : undefined;
                    const isLink = !!href;

                    return (
                      <td
                        key={col.key}
                        className={`px-4 py-3 text-sm text-gray-700 ${
                          col.align === "right"
                            ? "text-right"
                            : col.align === "center"
                              ? "text-center"
                              : "text-left"
                        } ${col.className || ""}`}
                      >
                        {isLink ? (
                          <Link
                            href={href!}
                            className="text-blue-600 hover:text-blue-800 hover:underline font-medium"
                          >
                            {content as React.ReactNode}
                          </Link>
                        ) : (
                          content as React.ReactNode
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {page !== undefined && pageSize !== undefined && total !== undefined && total > pageSize && (
        <div className="px-6 py-3 border-t border-gray-200 flex items-center justify-between bg-gray-50">
          <div className="text-xs text-gray-500">
            第 {page} 页 / 共 {totalPages} 页
          </div>
          <div className="flex items-center gap-2">
            {page > 1 && onPageChange && (
              <button
                onClick={() => onPageChange(page - 1)}
                className="px-3 py-1 text-xs bg-white border border-gray-200 rounded hover:bg-gray-100 transition-colors"
              >
                ← 上一页
              </button>
            )}
            {page < totalPages && onPageChange && (
              <button
                onClick={() => onPageChange(page + 1)}
                className="px-3 py-1 text-xs bg-white border border-gray-200 rounded hover:bg-gray-100 transition-colors"
              >
                下一页 →
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${getStatusBadgeClass(status)}`}
    >
      {getStatusLabel(status)}
    </span>
  );
}

export function SearchToolbar({
  search,
  onSearchChange,
  status,
  statusOptions,
  onStatusChange,
  extra,
}: {
  search: string;
  onSearchChange: (v: string) => void;
  status?: string;
  statusOptions?: { value: string; label: string }[];
  onStatusChange?: (v: string) => void;
  extra?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 mb-4 flex-wrap">
      <div className="relative flex-1 min-w-[200px]">
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="搜索..."
          className="w-full pl-4 pr-4 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
        />
      </div>
      {statusOptions && onStatusChange && (
        <select
          value={status || ""}
          onChange={(e) => onStatusChange(e.target.value)}
          className="px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400"
        >
          <option value="">全部状态</option>
          {statusOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      )}
      {extra}
    </div>
  );
}
