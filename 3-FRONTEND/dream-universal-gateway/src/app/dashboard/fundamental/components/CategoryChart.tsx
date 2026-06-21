"use client";

import React from "react";

interface CategoryItem {
  name: string;
  count: number;
}

interface CategoryChartProps {
  data: CategoryItem[];
  title?: string;
}

export default function CategoryChart({ data, title }: CategoryChartProps) {
  if (!data || data.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full rounded-lg"
        style={{ backgroundColor: "#1a1a1a", minHeight: 200 }}
      >
        <p className="text-[#6b7280] text-sm">暂无数据</p>
      </div>
    );
  }

  const sortedData = [...data].sort((a, b) => b.count - a.count);
  const maxCount = Math.max(...sortedData.map((d) => d.count));

  return (
    <div
      className="rounded-lg p-4"
      style={{ backgroundColor: "#1a1a1a", border: "1px solid #2a2a2a" }}
    >
      {title && (
        <h3 className="text-sm font-semibold text-white mb-4">{title}</h3>
      )}
      <div className="space-y-3">
        {sortedData.map((item, index) => {
          const percentage = (item.count / maxCount) * 100;
          return (
            <div key={index} className="flex items-center gap-3">
              <div
                className="text-xs text-[#8a8a8a] truncate"
                style={{ width: 80 }}
              >
                {item.name}
              </div>
              <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ backgroundColor: "#2a2a2a" }}>
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${percentage}%`,
                    backgroundColor: "#3b82f6",
                  }}
                />
              </div>
              <div className="text-xs text-[#e0e0e0] font-mono" style={{ width: 30 }}>
                {item.count}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
