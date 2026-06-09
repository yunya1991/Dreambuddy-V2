import { getOrgTreeWithStatus } from '@/lib/org-data';
import OrgTree from '@/components/OrgTree';

export default function OrgPage() {
  const data = getOrgTreeWithStatus();

  return (
    <div className="space-y-2">
      <OrgTree
        departments={data.company.departments}
        companyName={data.company.name}
        stats={{ total_nodes: data.company.total_nodes }}
      />

      {/* Stats Footer */}
      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">数据统计</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div className="bg-blue-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-blue-600">{data.stats.total_skills}</div>
            <div className="text-xs text-blue-500">总技能数</div>
          </div>
          <div className="bg-green-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-green-600">{data.stats.in_org_tree}</div>
            <div className="text-xs text-green-500">已编入架构</div>
          </div>
          <div className="bg-amber-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-amber-600">{data.stats.utility}</div>
            <div className="text-xs text-amber-500">工具类技能</div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-gray-600">{data.stats.unclassified}</div>
            <div className="text-xs text-gray-500">未分类</div>
          </div>
        </div>
      </div>
    </div>
  );
}
