'use client';

// T1 表格渲染：列类型由后端声明（percent 为比率，前端只乘 100 展示）

import { formatCell, type VisualColumn } from './types';

export function TableView({
  columns,
  rows,
}: {
  columns: VisualColumn[];
  rows: Record<string, unknown>[];
}) {
  return (
    <div className="max-h-[460px] overflow-auto rounded-lg border border-slate-800/60">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-slate-900/95 backdrop-blur">
          <tr>
            {columns.map(column => (
              <th
                key={column.key}
                className="px-2.5 py-2 text-left font-medium text-slate-400 whitespace-nowrap border-b border-slate-800"
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="hover:bg-slate-800/40">
              {columns.map(column => (
                <td
                  key={column.key}
                  className="px-2.5 py-1.5 text-slate-300 tabular-nums whitespace-nowrap border-b border-slate-800/40"
                >
                  {formatCell(row[column.key], column.type)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default TableView;
