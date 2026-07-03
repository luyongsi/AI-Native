'use client';

import type { DiffLine } from '@/lib/types';

interface DiffLineRowProps {
  line: DiffLine;
}

const typeStyles: Record<string, string> = {
  add: 'bg-emerald-50 border-l-2 border-emerald-400',
  remove: 'bg-red-50 border-l-2 border-red-400',
  context: 'bg-white',
};

const prefixStyles: Record<string, string> = {
  add: 'text-emerald-600 font-medium',
  remove: 'text-red-500 font-medium',
  context: 'text-slate-300',
};

export default function DiffLineRow({ line }: DiffLineRowProps) {
  const prefix = line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' ';
  const style = typeStyles[line.type] || typeStyles.context;
  const prefixStyle = prefixStyles[line.type] || prefixStyles.context;

  return (
    <div className={`flex text-xs leading-6 ${style}`}>
      {/* Old line number */}
      <span className="w-10 text-right flex-shrink-0 select-none text-[10px] text-slate-300 pr-2">
        {line.oldLineNumber ?? ''}
      </span>
      {/* New line number */}
      <span className="w-10 text-right flex-shrink-0 select-none text-[10px] text-slate-300 pr-2">
        {line.newLineNumber ?? ''}
      </span>
      {/* Prefix */}
      <span className={`w-4 flex-shrink-0 select-none text-center ${prefixStyle}`}>
        {prefix}
      </span>
      {/* Content */}
      <span className={`pl-1 font-mono whitespace-pre ${
        line.type === 'add' ? 'text-emerald-800' : line.type === 'remove' ? 'text-red-800' : 'text-slate-700'
      }`}>
        {line.content}
      </span>
    </div>
  );
}
