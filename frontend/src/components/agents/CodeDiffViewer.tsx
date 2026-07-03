'use client';

import type { CodeDiff } from '@/lib/types';
import DiffHunkRenderer from './DiffHunkRenderer';

interface CodeDiffViewerProps {
  diff: CodeDiff;
  onClose?: () => void;
}

const langLabels: Record<string, string> = {
  tsx: 'TSX',
  ts: 'TS',
  jsx: 'JSX',
  js: 'JS',
  css: 'CSS',
  json: 'JSON',
};

export default function CodeDiffViewer({ diff, onClose }: CodeDiffViewerProps) {
  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden bg-white">
      {/* File header */}
      <div className="bg-slate-900 text-white text-xs px-3 py-2 flex items-center gap-2">
        <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <span className="flex-1 font-mono truncate">{diff.file}</span>
        <span className="text-[10px] text-slate-400">
          {langLabels[diff.language] || diff.language}
        </span>
        <span className="text-[10px] text-emerald-400">+{diff.addedLines}</span>
        <span className="text-[10px] text-red-400">-{diff.removedLines}</span>
        {onClose && (
          <button onClick={onClose} className="p-0.5 hover:bg-slate-700 rounded flex-shrink-0">
            <svg className="w-3 h-3 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Diff hunks */}
      <div className="overflow-x-auto">
        {diff.hunks.length === 0 ? (
          <div className="p-4 text-center text-[10px] text-slate-400">无变更内容</div>
        ) : (
          diff.hunks.map((hunk, i) => (
            <DiffHunkRenderer key={i} hunk={hunk} />
          ))
        )}
      </div>
    </div>
  );
}
