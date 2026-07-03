'use client';

import type { AgentInfo } from '@/lib/types';

interface AgentActionBarProps {
  agent: AgentInfo;
  onViewFullLog?: () => void;
  onViewDiff?: () => void;
  onPause?: () => void;
  onIntervene?: () => void;
}

export default function AgentActionBar({ agent, onViewFullLog, onViewDiff, onPause, onIntervene }: AgentActionBarProps) {
  const hasDiff = agent.lastActivity.some((a) => a.type === 'code_gen' && a.diffId);

  return (
    <div className="flex gap-2 px-4 pb-3 bg-slate-50/50 border-t border-slate-100 pt-2">
      <button
        onClick={onViewFullLog}
        className="text-[10px] px-2.5 py-1.5 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50"
      >
        查看完整日志
      </button>
      {hasDiff && (
        <button
          onClick={onViewDiff}
          className="text-[10px] px-2.5 py-1.5 bg-white border border-emerald-200 rounded-lg text-emerald-600 hover:bg-emerald-50"
        >
          查看 Diff
        </button>
      )}
      <button
        onClick={onPause}
        className="text-[10px] px-2.5 py-1.5 bg-amber-50 border border-amber-200 rounded-lg text-amber-700 hover:bg-amber-100"
      >
        暂停 Agent
      </button>
      <button
        onClick={onIntervene}
        className="text-[10px] px-2.5 py-1.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 ml-auto"
      >
        介入接管
      </button>
    </div>
  );
}
