'use client';

import { useState, useMemo, useCallback, useEffect } from 'react';
import FeedCard from '@/components/FeedCard';
import DepartmentFilter from '@/components/DepartmentFilter';
import TimeFilter from '@/components/TimeFilter';
import SearchBar from '@/components/SearchBar';
import Pagination from '@/components/Pagination';
import DreamAgentChat from '@/components/DreamAgentChat';
import { searchArtifacts, searchFullText, initSearchIndex, filterByDepartment, filterByTimeRange, paginate } from '@/lib/search';
import type { CanonicalArtifactIndex, TimeRange } from '@/lib/types';

const PAGE_SIZE = 20;
const A_PHASES = ['A0','A1','A2','A3','A4','A5','A6','A7','A8','A9'];

// ============================================================
// 知识库过滤器分类体系 v3
// 按功能维度组织，基于实际数据标签
// ============================================================
const KNOWLEDGE_CATS: Record<string, { label: string; emoji: string; tags: string[] }> = {
  masters: {
    label: '蒸馏大师库',
    emoji: '🏛️',
    tags: ['master', 'masters', 'master_livermore', 'master_douglas', 'master_tharp',
           'master_turtle', 'master_buffett', 'master_druckenmiller', 'master_lynch',
           'master_paulson', 'master_soros'],
  },
  tools: {
    label: 'OKX工具库',
    emoji: '🛠️',
    tags: ['okx_tools', 'okx_strategy', 'tools', 'commands'],
  },
  macro: {
    label: '宏观资产库',
    emoji: '📊',
    tags: ['macro', 'macro_assets', 'correlation', 'cross_asset'],
  },
  risk: {
    label: '风险库',
    emoji: '⚠️',
    tags: ['risk', 'thresholds'],
  },
  exit: {
    label: '离场规则库',
    emoji: '🚪',
    tags: ['exit', 'rules'],
  },
  practice: {
    label: '实践教训库',
    emoji: '⚔️',
    tags: ['practice', 'lessons'],
  },
  web_strategy: {
    label: '联网策略库',
    emoji: '🌐',
    tags: ['web_strategy'],
  },
  advanced_orders: {
    label: '高级委托库',
    emoji: '⚡',
    tags: ['advanced_order', 'trailing', 'oco'],
  },
  audit: {
    label: '审计报告库',
    emoji: '📋',
    tags: ['audit', 'report'],
  },
  exit_rules: {
    label: '离场规则库',
    emoji: '🚪',
    tags: ['exit_rules', 'L0', 'L1', 'L2'],
  },
  risk_concept: {
    label: '风险概念库',
    emoji: '⚠️',
    tags: ['risk_concept', 'risk'],
  },
  template: {
    label: '模板库',
    emoji: '📝',
    tags: ['template', 'log_template'],
  },
};

const KNOWLEDGE_KEYS = Object.keys(KNOWLEDGE_CATS);

interface FeedClientProps {
  artifacts: CanonicalArtifactIndex[];
  deptCounts: Record<string, number>;
  phaseCounts: Record<string, number>;
  knowledgeCounts: Record<string, number>;
  totalArtifacts: number;
}

export default function FeedClient({ artifacts, deptCounts, phaseCounts, knowledgeCounts, totalArtifacts }: FeedClientProps) {
  const [department, setDepartment] = useState('all');
  const [timeRange, setTimeRange] = useState<TimeRange>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const [phaseFilter, setPhaseFilter] = useState<string>('all');
  const [knowledgeFilter, setKnowledgeFilter] = useState<string>('all');
  const [lastRead, setLastRead] = useState<Record<string, string>>({});
  const [newPhases, setNewPhases] = useState<Set<string>>(new Set());
  const [newDepts, setNewDepts] = useState<Set<string>>(new Set());
  const [isClient, setIsClient] = useState(false);
  const [searchIndexLoaded, setSearchIndexLoaded] = useState(false);
  const [fullTextIds, setFullTextIds] = useState<string[]>([]);
  const [isDreamAgentOpen, setIsDreamAgentOpen] = useState(false);

  // Initialize on mount
  useEffect(() => {
    const load = async () => {
      try {
        await initSearchIndex();
        setSearchIndexLoaded(true);
      } catch (e) {
        console.error('Failed to init search index:', e);
      }
      try {
        const stored = localStorage.getItem('productHub_lastRead');
        if (stored) {
          const parsed = JSON.parse(stored);
          // Normalize old ISO format to date-only
          const normalized: Record<string, string> = {};
          for (const [key, val] of Object.entries(parsed)) {
            normalized[key] = (val as string).split('T')[0];
          }
          setLastRead(normalized);
        }
      } catch (e) {
        console.error('Failed to load lastRead:', e);
      }
      setIsClient(true);
    };
    load();
  }, []);

  // Compute which phases/departments have new artifacts
  useEffect(() => {
    if (!isClient) return;
    const newP = new Set<string>();
    const newD = new Set<string>();
    
    for (const phase of A_PHASES) {
      const last = lastRead[phase];
      if (!last) {
        const hasAny = artifacts.some(a => a.chainPhase === phase);
        if (hasAny) newP.add(phase);
        continue;
      }
      const hasNew = artifacts.some(a =>
        a.chainPhase === phase && a.date && a.date > last
      );
      if (hasNew) newP.add(phase);
    }
    
    const deptList = ['trading', 'governance', 'knowledge', 'dream', 'support'];
    for (const dept of deptList) {
      const key = `dept_${dept}`;
      const last = lastRead[key];
      if (!last) {
        const hasAny = artifacts.some(a => a.department === dept);
        if (hasAny) newD.add(dept);
        continue;
      }
      const hasNew = artifacts.some(a =>
        a.department === dept && a.date && a.date > last
      );
      if (hasNew) newD.add(dept);
    }
    
    setNewPhases(newP);
    setNewDepts(newD);
  }, [artifacts, lastRead, isClient]);

  // Full-text search when query changes
  useEffect(() => {
    if (!searchIndexLoaded || !searchQuery.trim()) {
      setFullTextIds([]);
      return;
    }
    const performSearch = async () => {
      try {
        const ids = await searchFullText(searchQuery, 50);
        setFullTextIds(ids);
      } catch (e) {
        console.error('Full-text search failed:', e);
      }
    };
    performSearch();
  }, [searchQuery, searchIndexLoaded]);

  // Apply all filters
  const filteredArtifacts = useMemo(() => {
    let result = artifacts;
    result = filterByDepartment(department, result);
    if (department === 'all' || department === 'trading') {
      if (phaseFilter !== 'all') {
        result = result.filter(a => a.chainPhase === phaseFilter);
      }
    }
    if (department === 'knowledge') {
      if (knowledgeFilter !== 'all') {
        result = result.filter(a => {
          const artifactTags = Array.isArray(a.tags) ? a.tags : [];
          const catTags = KNOWLEDGE_CATS[knowledgeFilter]?.tags || [];
          return artifactTags.some((t) => catTags.includes(t));
        });
      }
    }
    result = filterByTimeRange(timeRange, result);
    result = searchArtifacts(searchQuery, result, fullTextIds);
    // 默认按时间倒序排序（最新优先），unknown 日期排最后
    result = [...result].sort((a, b) => {
      const dateA = String(a.date || 'unknown');
      const dateB = String(b.date || 'unknown');
      if (dateA === 'unknown' || dateA === '' || dateA === 'null' || dateA === 'undefined') return 1;
      if (dateB === 'unknown' || dateB === '' || dateB === 'null' || dateB === 'undefined') return -1;
      const cmp = dateB.localeCompare(dateA);
      if (cmp !== 0) return cmp;
      return String(b.id).localeCompare(String(a.id));
    });
    return result;
  }, [artifacts, department, timeRange, searchQuery, phaseFilter, knowledgeFilter, fullTextIds]);

  const { items: pageItems, totalPages } = useMemo(
    () => paginate(filteredArtifacts, page, PAGE_SIZE),
    [filteredArtifacts, page]
  );

  const handleDepartmentChange = useCallback((id: string) => {
    if (isClient) {
      const now = new Date().toISOString().split('T')[0];  // 仅日期格式
      const key = `dept_${id}`;
      const updated = { ...lastRead, [key]: now };
      setLastRead(updated);
      try { localStorage.setItem('productHub_lastRead', JSON.stringify(updated)); } catch {}
      setNewDepts(prev => { const next = new Set(prev); next.delete(id); return next; });
    }
    setDepartment(id);
    setPhaseFilter('all');
    setKnowledgeFilter('all');
    setPage(1);
  }, [lastRead, isClient]);

  const handleTimeRangeChange = useCallback((range: TimeRange) => {
    setTimeRange(range);
    setPage(1);
  }, []);

  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query);
    setPage(1);
  }, []);

  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  const handlePhaseChange = useCallback((phase: string) => {
    if (isClient) {
      const now = new Date().toISOString().split('T')[0]; // 仅日期格式
      const updated = { ...lastRead, [phase]: now };
      setLastRead(updated);
      try { localStorage.setItem('productHub_lastRead', JSON.stringify(updated)); } catch {}
      setNewPhases(prev => { const next = new Set(prev); next.delete(phase); return next; });
    }
    setPhaseFilter(phase);
    setPage(1);
  }, [lastRead, isClient]);

  const handleKnowledgeCategory = useCallback((cat: string) => {
    setKnowledgeFilter(cat);
    setPage(1);
  }, []);

  // Compute category counts from raw tag counts
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const key of KNOWLEDGE_KEYS) {
      const catTags = KNOWLEDGE_CATS[key].tags;
      let total = 0;
      for (const tag of catTags) {
        total += knowledgeCounts[tag] || 0;
      }
      counts[key] = total;
    }
    return counts;
  }, [knowledgeCounts]);

  const showPhaseFilter = department === 'all' || department === 'trading';
  const showKnowledgeFilter = department === 'knowledge';

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <h1 className="text-2xl font-bold text-gray-900">Dream 产物中心</h1>
              {/* Dream Agent Button */}
              <button
                onClick={() => setIsDreamAgentOpen(true)}
                className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-blue-500 to-purple-600 text-white rounded-lg hover:from-blue-600 hover:to-purple-700 transition shadow-md"
              >
                <span className="text-xl">🧠</span>
                <span className="font-medium">Dream Agent</span>
              </button>
            </div>
            <div className="text-sm text-gray-500">共 {totalArtifacts} 个产物</div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Search Bar */}
        <SearchBar onSearch={handleSearch} />

        {/* Filter Panel */}
        <div className="bg-white rounded-lg shadow p-4 mb-6 space-y-4">
          {/* Row 1: Department + Time (always visible) */}
          <div className="flex flex-wrap gap-4 items-center">
            <DepartmentFilter
              counts={deptCounts}
              selected={department}
              onChange={handleDepartmentChange}
              newDepts={newDepts}
            />
            <TimeFilter onSelect={handleTimeRangeChange} selected={timeRange} />
          </div>

          {/* Row 2: A-Phase Filter (only for 'all' or 'trading') */}
          {showPhaseFilter && (
            <div className="flex flex-wrap gap-2 pt-3 border-t border-gray-100">
              <span className="text-sm font-medium text-gray-500 mr-1 self-center">
                {department === 'all' ? '全部·A阶段：' : 'A阶段：'}
              </span>
              <button
                onClick={() => handlePhaseChange('all')}
                className={`px-3 py-1 rounded text-sm ${
                  phaseFilter === 'all' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                全部
              </button>
              {A_PHASES.map(phase => {
                const count = phaseCounts[phase] || 0;
                const isNew = newPhases.has(phase);
                return (
                  <button
                    key={phase}
                    onClick={() => handlePhaseChange(phase)}
                    className={`px-3 py-1 rounded text-sm relative ${
                      phaseFilter === phase ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    <span>{phase}</span>
                    {count > 0 && (
                      <span className={`ml-1 text-xs px-1 py-px rounded-full ${
                        phaseFilter === phase ? 'bg-blue-500' : 'bg-gray-200 text-gray-600'
                      }`}>
                        {count}
                      </span>
                    )}
                    {isNew && count > 0 && (
                      <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-500 rounded-full" />
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {/* Row 3: Knowledge Category Filter (only for 'knowledge') */}
          {showKnowledgeFilter && (
            <div className="flex flex-wrap gap-2 pt-3 border-t border-gray-100">
              <span className="text-sm font-medium text-gray-500 mr-1 self-center">知识分类：</span>
              <button
                onClick={() => handleKnowledgeCategory('all')}
                className={`px-3 py-1 rounded text-sm ${
                  knowledgeFilter === 'all' ? 'bg-purple-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                全部知识
              </button>
              {KNOWLEDGE_KEYS.map(key => (
                <button
                  key={key}
                  onClick={() => handleKnowledgeCategory(key)}
                  className={`px-3 py-1 rounded text-sm flex items-center gap-1 ${
                    knowledgeFilter === key ? 'bg-purple-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  <span>{KNOWLEDGE_CATS[key].emoji}</span>
                  <span>{KNOWLEDGE_CATS[key].label}</span>
                  {categoryCounts[key] > 0 && (
                    <span className={`text-xs px-1 py-px rounded-full ${
                      knowledgeFilter === key ? 'bg-purple-500' : 'bg-gray-200'
                    }`}>
                      {categoryCounts[key]}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Stats + Feed Cards */}
        {filteredArtifacts.length > 0 && (
          <div className="mb-4 text-sm text-gray-500">
            找到 {filteredArtifacts.length} 个产物
          </div>
        )}

        {/* Feed Cards */}
        <div className="space-y-4">
          {pageItems.length > 0 ? (
            pageItems.map(artifact => (
              <FeedCard key={artifact.id} artifact={artifact} />
            ))
          ) : (
            <div className="bg-white rounded-lg shadow p-8 text-center">
              <p className="text-gray-500">没有找到匹配的产物</p>
            </div>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <Pagination
            currentPage={page}
            totalPages={totalPages}
            onPageChange={handlePageChange}
            totalItems={totalArtifacts}
            pageSize={PAGE_SIZE}
          />
        )}

        {/* Dream Agent Chat */}
        {isDreamAgentOpen && (
          <DreamAgentChat
            isOpen={isDreamAgentOpen}
            onClose={() => setIsDreamAgentOpen(false)}
          />
        )}
      </div>
    </div>
  );
}
