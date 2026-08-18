"use client";

import { useEffect, useState, useMemo } from "react";

interface ContentItem {
  id: string;
  title: string;
  tags: string[];
  department: string;
  type: string;
  date: string;
  status: "completed" | "processing" | "failed" | "unknown";
  excerpt?: string;
  url: string;
}

const STATUS_LABEL: Record<ContentItem["status"], { label: string; color: string }> = {
  completed:  { label: "已完成", color: "#4ade80" },
  processing: { label: "处理中", color: "#60a5fa" },
  failed:     { label: "失败",   color: "#f87171" },
  unknown:    { label: "未知",   color: "#9ca3af" },
};

export default function ContentPoolPage() {
  const [items, setItems] = useState<ContentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    fetch("/api/market/content")
      .then(r => r.json())
      .then(json => {
        if (json.success) setItems(json.data ?? []);
        else setError(json.error ?? "加载失败");
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    items.forEach(item => item.tags.forEach(t => set.add(t)));
    return Array.from(set).sort();
  }, [items]);

  const filtered = useMemo(() => {
    return items.filter(item => {
      if (selectedTag && !item.tags.includes(selectedTag)) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        return item.title.toLowerCase().includes(q) || (item.excerpt?.toLowerCase().includes(q) ?? false);
      }
      return true;
    });
  }, [items, selectedTag, searchQuery]);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">内容池</h1>
        <p className="text-gray-400 text-sm mb-6">市场情报内容列表 — 支持标签过滤与关键词搜索</p>

        {/* Search + tag filter bar */}
        <div className="flex flex-wrap gap-3 mb-6">
          <input
            type="text"
            placeholder="搜索内容..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="flex-1 min-w-48 rounded-md bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
          />
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setSelectedTag(null)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${ selectedTag === null ? "bg-indigo-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700" }`}
            >
              全部
            </button>
            {allTags.map(tag => (
              <button
                key={tag}
                onClick={() => setSelectedTag(tag === selectedTag ? null : tag)}
                className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${ selectedTag === tag ? "bg-indigo-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700" }`}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading && (
          <div className="space-y-3">
            {[0,1,2,3].map(i => (
              <div key={i} className="h-20 rounded-lg bg-gray-900 animate-pulse" />
            ))}
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <p className="text-center text-gray-500 py-16">暂无内容数据</p>
        )}

        <div className="space-y-3">
          {filtered.map(item => {
            const st = STATUS_LABEL[item.status] ?? STATUS_LABEL.unknown;
            return (
              <div key={item.id} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
                        {item.type}
                      </span>
                      <span className="text-xs font-medium" style={{ color: st.color }}>
                        {st.label}
                      </span>
                    </div>
                    <h3 className="text-sm font-medium text-white truncate">{item.title}</h3>
                    {item.excerpt && (
                      <p className="text-xs text-gray-500 mt-1 line-clamp-2">{item.excerpt}</p>
                    )}
                    <div className="flex flex-wrap gap-1 mt-2">
                      {item.tags.map(tag => (
                        <span key={tag} className="text-xs bg-indigo-900/40 text-indigo-300 px-1.5 py-0.5 rounded">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="text-xs text-gray-500 shrink-0">{item.date}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}