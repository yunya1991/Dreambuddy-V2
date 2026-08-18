import { notFound } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, FileText, Tag, Calendar } from 'lucide-react';
import { marked } from 'marked';
import { getArtifactBySlug, getArtifactRelations } from '@/lib/content';
import StatusBadge from '@/components/StatusBadge';
import { findArtifactChainRelation } from '../feed-chain-link';
import {
  formatDate,
  getDeptLabel,
  getTypeLabel,
  CHAIN_PHASE_LABELS,
} from '@/lib/utils';

interface PageProps {
  params: { slug: string[] };
}

export const dynamicParams = true;

async function getArtifactData(slugParts: string[]) {
  const slug = slugParts.join('/');
  return getArtifactBySlug(slug);
}

export default async function ArtifactDetailPage({ params }: PageProps) {
  const artifact = await getArtifactData(params.slug);

  if (!artifact) {
    notFound();
  }

  const relation = findArtifactChainRelation(
    artifact.canonical.artifactId,
    getArtifactRelations(),
  );

  const { frontmatter, content } = artifact;
  const fm = frontmatter as Record<string, string | string[] | undefined>;
  const canonical = artifact.canonical;
  const title = canonical.title;
  const department = canonical.department;
  const type = canonical.type;
  const status = canonical.status;
  const date = canonical.date;
  const chainPhase = canonical.chainPhase;
  const tags = canonical.tags;

  // Render markdown to HTML using marked (safe, no JSX parsing)
  const rawHtml = marked.parse(content, { async: false }) as string;

  return (
    <article className="max-w-4xl mx-auto">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm text-gray-500 mb-6">
        <Link href="/feed" className="flex items-center gap-1 hover:text-blue-600 transition-colors">
          <ArrowLeft className="h-4 w-4" />
          产物中心
        </Link>
        <span>/</span>
        <span className="text-gray-700">{getDeptLabel(department)}</span>
        <span>/</span>
        <span className="text-gray-400 truncate max-w-[200px]">{title}</span>
      </nav>

      {/* Header */}
      <header className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-3">{title}</h1>

        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={status || 'unknown'} size="md" />

          <span className="flex items-center gap-1 text-sm text-gray-500">
            <FileText className="h-4 w-4" />
            {getDeptLabel(department)}
          </span>

          <span className="rounded bg-gray-100 px-2 py-1 text-sm font-medium text-gray-700">
            {getTypeLabel(type)}
          </span>

          {chainPhase && (
            <span className="rounded bg-gray-100 px-2 py-1 text-sm font-mono text-gray-600">
              {CHAIN_PHASE_LABELS[chainPhase] || chainPhase}
            </span>
          )}

          <span className="flex items-center gap-1 text-sm text-gray-500">
            <Calendar className="h-4 w-4" />
            {formatDate(date)}
          </span>

          {fm.ep && (
            <span className="rounded bg-purple-50 px-2 py-1 text-sm font-medium text-purple-700">
              {fm.ep as string}
            </span>
          )}

          {fm.priority && (
            <span className="rounded bg-red-50 px-2 py-1 text-sm font-medium text-red-700">
              {fm.priority as string}
            </span>
          )}

          {relation && (
            <Link
              href={relation.chainHref}
              className="inline-flex items-center rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-100"
            >
              查看 Chain 定位
            </Link>
          )}
        </div>

        {/* Tags */}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 rounded-md bg-gray-50 px-2 py-0.5 text-xs text-gray-500 border border-gray-100"
              >
                <Tag className="h-3 w-3" />
                {tag}
              </span>
            ))}
          </div>
        )}
      </header>

      {/* Content — render markdown as HTML */}
      <div
        className="prose max-w-none"
        dangerouslySetInnerHTML={{ __html: rawHtml }}
      />

      {/* Footer */}
      <footer className="mt-12 pt-6 border-t border-gray-200">
        <div className="flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-3">
            <span>类型: {getTypeLabel(type)}</span>
            <span>|</span>
            <span>状态: {status || 'unknown'}</span>
          </div>
          <Link href="/feed" className="hover:text-blue-600 transition-colors">
            返回产物中心
          </Link>
        </div>
      </footer>
    </article>
  );
}
