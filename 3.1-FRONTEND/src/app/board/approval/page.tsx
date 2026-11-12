import { permanentRedirect } from 'next/navigation';

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

// 旧路径兼容（SPEC-20261111-A §3.1）：308，保留 query
export default async function LegacyBoardApprovalPage({ searchParams }: { searchParams: SearchParams }) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(await searchParams)) {
    if (Array.isArray(v)) v.forEach((x) => qs.append(k, x));
    else if (v != null) qs.append(k, v);
  }
  const query = qs.toString();
  permanentRedirect(`/dashboard/board/approval${query ? `?${query}` : ''}`);
}
