import { notFound } from 'next/navigation';
import { getOrgTreeWithStatus } from '@/lib/org-data';
import NodeDetailPanel from '@/components/NodeDetailPanel';

export default async function NodePage({
  params,
}: {
  params: { dept: string; sub: string; node: string };
}) {
  const data = getOrgTreeWithStatus();
  const dept = data.company.departments.find((d) => d.id === params.dept);
  if (!dept) notFound();

  const sub = dept.subsystems.find((s) => s.id === params.sub);
  if (!sub) notFound();

  const node = sub.nodes.find((n) => n.id === params.node);
  if (!node) notFound();

  return (
    <NodeDetailPanel
      node={node}
      deptName={dept.name}
      subName={sub.name}
      deptId={dept.id}
    />
  );
}
