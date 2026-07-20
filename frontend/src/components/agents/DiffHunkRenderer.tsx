'use client';

import type { DiffHunk } from '@/lib/types';
import DiffLineRow from './DiffLineRow';

interface DiffHunkRendererProps {
  hunk: DiffHunk;
}

export default function DiffHunkRenderer({ hunk }: DiffHunkRendererProps) {
  return (
    <div>
      {/* Hunk header */}
      <div className="bg-slate-700 text-slate-400 text-[10px] font-medium py-1 px-3 font-mono">
        {hunk.header}
      </div>
      {/* Hunk lines */}
      {hunk.lines.map((line, i) => (
        <DiffLineRow key={i} line={line} />
      ))}
    </div>
  );
}
