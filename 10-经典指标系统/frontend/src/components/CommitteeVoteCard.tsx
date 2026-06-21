import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface CommitteeDetails {
  [key: string]: {
    p: number;
    pc: number;
    vote: string;
  };
}

interface CommitteeVoteCardProps {
  committee: CommitteeDetails;
  pair: string;
  side: string;
  ts: number;
}

export const CommitteeVoteCard: React.FC<CommitteeVoteCardProps> = ({ committee, pair, side, ts }) => {
  if (!committee || Object.keys(committee).length === 0) {
    return null;
  }

  const tsNum = Number(ts ?? 0);
  const tsMs = Number.isFinite(tsNum) && tsNum > 0 ? (tsNum < 1_000_000_000_000 ? tsNum * 1000 : tsNum) : 0;
  const timeText = tsMs > 0 ? new Date(tsMs).toLocaleString('zh-CN', { hour12: false }) : '-';

  const prettyModelName = (raw: string) => {
    let s = String(raw ?? '');
    s = s.replace(/^online_/, '');
    s = s.replace(/\.(pkl|pth|joblib)$/i, '');
    s = s.replace(/_model$/i, '');
    if (s.startsWith('__') && s.endsWith('__') && s.length >= 4) {
      s = s.slice(2, -2);
    }
    return s;
  };

  const models = Object.entries(committee).map(([name, details]) => {
    const p = typeof details?.p === 'number' ? details.p : Number(details?.p ?? NaN);
    const pc = typeof details?.pc === 'number' ? details.pc : Number(details?.pc ?? NaN);
    return {
      id: name,
      name: prettyModelName(name),
      p: Number.isFinite(p) ? p : 0,
      pc: Number.isFinite(pc) ? pc : 0,
      vote: String(details?.vote ?? ''),
    };
  });

  const agreeCount = models.filter(m => m.vote === 'agree').length;
  const vetoCount = models.filter(m => m.vote === 'veto').length;

  return (
    <Card className="mb-4 border-slate-200 shadow-sm">
      <CardHeader className="py-3 px-4 bg-slate-50 border-b border-slate-100 flex flex-row items-center justify-between">
        <div className="flex items-center gap-2">
            <CardTitle className="text-sm font-semibold text-slate-700">Committee Vote</CardTitle>
            <span className="text-xs text-slate-500 font-normal">
                {timeText} • {pair} • <span className={side === 'long' ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>{side.toUpperCase()}</span>
            </span>
        </div>
        <div className="flex gap-2 text-xs font-medium">
            <span className="text-green-600 bg-green-50 px-2 py-0.5 rounded-full border border-green-100">Agree: {agreeCount}</span>
            <span className="text-red-600 bg-red-50 px-2 py-0.5 rounded-full border border-red-100">Veto: {vetoCount}</span>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-slate-500 uppercase bg-slate-50/50">
              <tr>
                <th className="px-4 py-2 font-medium">Model</th>
                <th className="px-4 py-2 font-medium text-right">Raw Prob (p)</th>
                <th className="px-4 py-2 font-medium text-right">Calib Prob (pc)</th>
                <th className="px-4 py-2 font-medium text-center">Vote</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {models.map((m) => (
                <tr key={m.id} className="hover:bg-slate-50/30 transition-colors">
                  <td className="px-4 py-2 font-medium text-slate-700">{m.name}</td>
                  <td className="px-4 py-2 text-slate-600 text-right">{m.p.toFixed(4)}</td>
                  <td className="px-4 py-2 text-slate-600 text-right">{m.pc.toFixed(4)}</td>
                  <td className="px-4 py-2 text-center">
                    <span className={`px-2 py-1 rounded text-xs font-semibold ${
                      m.vote === 'agree' 
                        ? 'bg-green-100 text-green-700 border border-green-200' 
                        : 'bg-red-100 text-red-700 border border-red-200'
                    }`}>
                      {m.vote.toUpperCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
};
