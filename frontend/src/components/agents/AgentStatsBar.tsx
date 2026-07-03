'use client';

import type { AgentInfo } from '@/lib/types';

interface AgentStatsBarProps {
  agents: AgentInfo[];
  agentFilter: 'all' | 'running' | 'error' | 'idle';
  onAgentFilterChange: (filter: 'all' | 'running' | 'error' | 'idle') => void;
  priorityFilter: 'all' | 'P0' | 'P1' | 'P2' | 'P3';
  onPriorityFilterChange: (filter: 'all' | 'P0' | 'P1' | 'P2' | 'P3') => void;
  showPriorityFilter?: boolean;
}

const filterLabels: Record<string, string> = {
  all: '全部',
  running: '运行中',
  error: '异常',
  idle: '空闲',
};

const priorityLabels: Record<string, string> = {
  all: '全部',
  P0: 'P0',
  P1: 'P1',
  P2: 'P2',
  P3: 'P3',
};

export default function AgentStatsBar({
  agents,
  agentFilter,
  onAgentFilterChange,
  priorityFilter,
  onPriorityFilterChange,
  showPriorityFilter = false,
}: AgentStatsBarProps) {
  const running = agents.filter((a) => a.status === 'running').length;
  const idle = agents.filter((a) => a.status === 'idle').length;
  const error = agents.filter((a) => a.status === 'error').length;

  return (
    <div className="flex items-center gap-4 mb-4 text-xs text-slate-500 flex-shrink-0">
      <span>
        活跃:{' '}
        <strong className="text-slate-700">{running}</strong>
      </span>
      <span>
        空闲:{' '}
        <strong className="text-slate-700">{idle}</strong>
      </span>
      <span className="text-red-500">
        异常: <strong>{error}</strong>
      </span>
      <div className="flex-1" />

      {/* Priority filter (swarm view) */}
      {showPriorityFilter && (
        <div className="flex gap-1">
          {(['all', 'P0', 'P1', 'P2', 'P3'] as const).map((f) => (
            <button
              key={f}
              onClick={() => onPriorityFilterChange(f)}
              className={`text-[10px] px-2 py-1 rounded-lg transition-colors ${
                priorityFilter === f
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {priorityLabels[f]}
            </button>
          ))}
        </div>
      )}

      {/* Agent status filter */}
      <div className="flex gap-1">
        {(['all', 'running', 'error', 'idle'] as const).map((f) => (
          <button
            key={f}
            onClick={() => onAgentFilterChange(f)}
            className={`text-[10px] px-2 py-1 rounded-lg transition-colors ${
              agentFilter === f
                ? 'bg-slate-900 text-white'
                : 'text-slate-500 hover:bg-slate-100'
            }`}
          >
            {filterLabels[f]}
          </button>
        ))}
      </div>
    </div>
  );
}
