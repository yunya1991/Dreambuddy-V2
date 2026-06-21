import React, { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchDocSnippet } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Input } from './ui/input';

const _copy = async (txt: string): Promise<boolean> => {
  const v = String(txt ?? '').trim();
  if (!v) return false;
  try {
    await navigator.clipboard.writeText(v);
    return true;
  } catch {
    return false;
  }
};

export const DocsPage: React.FC = () => {
  const [sp, setSp] = useSearchParams();

  const doc = String(sp.get('doc') ?? '技术文档.md').trim() || '技术文档.md';
  const section = String(sp.get('section') ?? '').trim();
  const startLineParam = useMemo(() => {
    const raw = sp.get('start_line');
    if (raw == null) return null;
    const x = Number(raw);
    if (!Number.isFinite(x)) return null;
    return Math.max(1, Math.trunc(x));
  }, [sp]);
  const endLineParam = useMemo(() => {
    const raw = sp.get('end_line');
    if (raw == null) return null;
    const x = Number(raw);
    if (!Number.isFinite(x)) return null;
    return Math.max(1, Math.trunc(x));
  }, [sp]);
  const maxChars = useMemo(() => {
    const raw = sp.get('max_chars');
    const x = raw == null ? 20000 : Number(raw);
    if (!Number.isFinite(x)) return 20000;
    return Math.max(2000, Math.min(200000, Math.floor(x)));
  }, [sp]);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['docs', 'snippet', doc, section, startLineParam, endLineParam, maxChars],
    queryFn: () => fetchDocSnippet({ doc, section, start_line: startLineParam ?? undefined, end_line: endLineParam ?? undefined, max_chars: maxChars }),
    refetchOnWindowFocus: false,
    retry: false,
  });

  const txt = String(data?.text ?? '').trimEnd();
  const ok = Boolean(data?.ok);
  const startLineOut = Number(data?.start_line ?? 0);
  const endLineOut = Number(data?.end_line ?? 0);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-2xl font-bold">Docs</div>
          <div className="text-sm text-slate-600">按 section 抽取文档片段，用于跳转与排障定位</div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={isFetching ? 'secondary' : 'outline'}>{isFetching ? 'refreshing' : 'ready'}</Badge>
          <Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>Refresh</Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Query</span>
            <Button
              variant="outline"
              onClick={() => void _copy(window.location.href)}
            >
              Copy URL
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-1">
              <div className="text-xs text-slate-500">doc</div>
              <Input
                value={doc}
                onChange={(e) => {
                  const v = String(e.target.value ?? '').trim();
                  const next = new URLSearchParams(sp);
                  next.set('doc', v || '技术文档.md');
                  setSp(next);
                }}
              />
            </div>
            <div className="space-y-1">
              <div className="text-xs text-slate-500">section</div>
              <Input
                value={section}
                placeholder="例如：14.8.3"
                onChange={(e) => {
                  const v = String(e.target.value ?? '').trim();
                  const next = new URLSearchParams(sp);
                  if (v) next.set('section', v);
                  else next.delete('section');
                  setSp(next);
                }}
              />
            </div>
            <div className="space-y-1">
              <div className="text-xs text-slate-500">max_chars</div>
              <Input
                value={String(maxChars)}
                onChange={(e) => {
                  const v = String(e.target.value ?? '').trim();
                  const next = new URLSearchParams(sp);
                  if (v) next.set('max_chars', v);
                  else next.delete('max_chars');
                  setSp(next);
                }}
              />
            </div>
          </div>
          <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="space-y-1">
              <div className="text-xs text-slate-500">start_line</div>
              <Input
                value={sp.get('start_line') ?? ''}
                placeholder="例如：745"
                onChange={(e) => {
                  const v = String(e.target.value ?? '').trim();
                  const next = new URLSearchParams(sp);
                  if (v) next.set('start_line', v);
                  else next.delete('start_line');
                  setSp(next);
                }}
              />
            </div>
            <div className="space-y-1">
              <div className="text-xs text-slate-500">end_line</div>
              <Input
                value={sp.get('end_line') ?? ''}
                placeholder="例如：748"
                onChange={(e) => {
                  const v = String(e.target.value ?? '').trim();
                  const next = new URLSearchParams(sp);
                  if (v) next.set('end_line', v);
                  else next.delete('end_line');
                  setSp(next);
                }}
              />
            </div>
            <div className="space-y-1">
              <div className="text-xs text-slate-500">mode</div>
              <Input value={(sp.get('start_line') || sp.get('end_line')) ? 'lines' : (section ? 'section' : 'top')} readOnly />
            </div>
          </div>
        </CardContent>
      </Card>

      {isLoading ? (
        <Card>
          <CardHeader>
            <CardTitle>Loading</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-slate-500">Loading...</div>
          </CardContent>
        </Card>
      ) : error ? (
        <Card>
          <CardHeader>
            <CardTitle>Error</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-red-600">{String((error as Error)?.message ?? error)}</div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center justify-between gap-2">
              <span>Snippet</span>
              <div className="flex items-center gap-2">
                <Badge variant={ok ? 'secondary' : 'destructive'}>{ok ? 'ok' : 'not found'}</Badge>
                <Badge variant="outline">{doc}</Badge>
                <Badge variant="outline">sec {section || '-'}</Badge>
                <Badge variant="outline">L{startLineOut > 0 ? startLineOut : '-'}~{endLineOut > 0 ? endLineOut : '-'}</Badge>
                <Button variant="outline" onClick={() => void _copy(txt)} disabled={!txt}>Copy Text</Button>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap break-words font-mono text-xs rounded border bg-white p-3 max-h-[70vh] overflow-auto">
              {txt || String(data?.error ?? '-')}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
