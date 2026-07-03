'use client';

import type { Requirement, AgentInfo } from '@/lib/types';
import AgentStatusDot from './AgentStatusDot';

interface SwarmCardProps {
  requirement: Requirement;
  agents: AgentInfo[];
  isSelected: boolean;
  onClick: () => void;
}

const priorityC: Record<string, string> = {
  P0: 'text-red-600 bg-red-50',
  P1: 'text-amber-600 bg-amber-50',
  P2: 'text-blue-600 bg-blue-50',
  P3: 'text-slate-500 bg-slate-100',
};

function getAgentsForReq(req: Requirement, agents: AgentInfo[]): AgentInfo[] {
  const names = new Set(req.stages.filter((s) => s.assignee).map((s) => s.assignee.toLowerCase()));
  return agents.filter((a) => names.has(a.name.toLowerCase()));
}

function getHumanCount(req: Requirement, agents: AgentInfo[]): number {
  const agNames = new Set(agents.map((a) => a.name.toLowerCase()));
  return req.assignees.filter((n) => !agNames.has(n.toLowerCase())).length;
}

export default function SwarmCard({ requirement, agents, isSelected, onClick }: SwarmCardProps) {
  const swarmAgents = getAgentsForReq(requirement, agents);
  const humanCount = getHumanCount(requirement, agents);
  const running = swarmAgents.filter((a) => a.status === 'running').length;
  const errored = swarmAgents.filter((a) => a.status === 'error').length;
  const aiPct = requirement.aiCompletion;

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-2.5 py-2 rounded-lg border transition-all ${
        isSelected
          ? 'border-slate-900 ring-1 ring-slate-900/10 bg-slate-50'
          : 'border-slate-100 bg-white hover:border-slate-200 hover:bg-slate-50/50'
      }`}
    >
      {/* Row 1: priority + ID + title */}
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={`text-[9px] font-bold px-1 rounded leading-tight flex-shrink-0 ${priorityC[requirement.priority] || priorityC.P3}`}>
          {requirement.priority}
        </span>
        <span className="text-[10px] font-mono text-slate-400 flex-shrink-0">{requirement.id}</span>
        <span className="text-[11px] font-medium text-slate-800 truncate">{requirement.title}</span>
      </div>

      {/* Row 2: agent dots + stats + progress */}
      <div className="flex items-center gap-2 mt-1">
        {/* Agent swarm dots */}
        {swarmAgents.length > 0 ? (
          <div className="flex items-center gap-0.5 flex-shrink-0">
            {swarmAgents.slice(0, 4).map((a) => (
              <AgentStatusDot key={a.id} status={a.status} />
            ))}
            {swarmAgents.length > 4 && (
              <span className="text-[9px] text-slate-400 ml-0.5">+{swarmAgents.length - 4}</span>
            )}
          </div>
        ) : (
          <span className="w-5 flex-shrink-0" />
        )}

        {/* Agent summary */}
        <span className="text-[9px] text-slate-400 flex-shrink-0">
          {running > 0 && `${running}活跃`}
          {errored > 0 && <span className="text-red-500 ml-1">{errored}异常</span>}
          {humanCount > 0 && <span className="ml-1">+{humanCount}人</span>}
          {running === 0 && errored === 0 && humanCount === 0 && '待分配'}
        </span>

        {/* AI progress bar (flex-1 pushes it right) */}
        <div className="flex-1" />
        {aiPct > 0 && (
          <div className="flex items-center gap-1 flex-shrink-0">
            <div className="w-8 h-1 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${aiPct}%` }} />
            </div>
            <span className="text-[9px] text-emerald-600 font-medium w-7 text-right">{aiPct}%</span>
          </div>
        )}

        {/* Blocked flag */}
        {requirement.blocked && (
          <svg className="w-3.5 h-3.5 text-red-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
        )}
      </div>
    </button>
  );
}
