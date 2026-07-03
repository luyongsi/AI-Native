'use client';

import type { AgentActivity } from '@/lib/types';

const typeLabels: Record<string, string> = {
  think: '思考',
  tool_call: '工具调用',
  code_gen: '代码生成',
  commit: '提交',
  test: '测试',
  error: '异常',
  wait: '等待中',
};

const typeColors: Record<string, string> = {
  think: 'text-purple-600 bg-purple-50 border-purple-100',
  tool_call: 'text-blue-600 bg-blue-50 border-blue-100',
  code_gen: 'text-emerald-600 bg-emerald-50 border-emerald-100',
  commit: 'text-slate-600 bg-slate-100 border-slate-200',
  test: 'text-cyan-600 bg-cyan-50 border-cyan-100',
  error: 'text-red-600 bg-red-50 border-red-100',
  wait: 'text-amber-600 bg-amber-50 border-amber-100',
};

interface AgentActivityTimelineProps {
  activities: AgentActivity[];
  onViewDiff?: (activity: AgentActivity) => void;
  compact?: boolean;
}

export default function AgentActivityTimeline({ activities, onViewDiff, compact = false }: AgentActivityTimelineProps) {
  if (activities.length === 0) {
    return (
      <div className={`text-center text-slate-400 ${compact ? 'text-[10px] py-2' : 'text-[10px] p-4'}`}>
        空闲中 — 无最近活动
      </div>
    );
  }

  return (
    <div className={compact ? 'space-y-1.5' : 'space-y-2'}>
      {activities.map((act, i) => {
        const hasDiff = act.type === 'code_gen' && act.diffId && onViewDiff;
        return (
          <div key={i} className="flex items-start gap-3">
            <span className="text-[10px] text-slate-400 flex-shrink-0 w-10 text-right pt-0.5">
              {act.time}
            </span>
            <div className="flex-1 flex items-start gap-2 min-w-0">
              <span
                className={`text-[10px] font-medium px-1.5 py-0.5 rounded border flex-shrink-0 ${
                  typeColors[act.type] || 'text-slate-500 bg-slate-50 border-slate-100'
                }`}
              >
                {typeLabels[act.type] || act.type}
              </span>
              <div className="min-w-0">
                <span className="text-xs text-slate-700">{act.content}</span>
                {act.detail && (
                  <span className="text-[10px] text-slate-400 ml-2">{act.detail}</span>
                )}
                {act.success === false && (
                  <span className="text-[10px] text-red-500 font-medium ml-1">失败</span>
                )}
                {hasDiff && (
                  <button
                    onClick={() => onViewDiff!(act)}
                    className="text-[10px] text-emerald-600 hover:text-emerald-800 ml-2 underline underline-offset-1"
                  >
                    查看 Diff
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
