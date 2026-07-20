'use client';

import { useMemo } from 'react';
import type { Requirement, AgentInfo } from '@/lib/types';
import SwarmCard from './SwarmCard';

interface SwarmViewProps {
  requirements: Requirement[];
  agents: AgentInfo[];
  priorityFilter: 'all' | 'P0' | 'P1' | 'P2' | 'P3';
  onSelectRequirement: (reqId: string) => void;
  selectedRequirementId: string | null;
}

function hasActiveAgents(req: Requirement, agents: AgentInfo[]): boolean {
  const names = new Set(req.stages.filter((s) => s.assignee).map((s) => s.assignee.toLowerCase()));
  return agents.some((a) => names.has(a.name.toLowerCase()));
}

type StatusGroup = { status: string; label: string; count: number; reqs: Requirement[] };

const groupOrder = ['developing', 'testing', 'releasing', 'designing', 'pool', 'done'];
const groupLabels: Record<string, string> = {
  developing: '开发中',
  testing: '测试中',
  releasing: '待发布',
  designing: '设计中',
  pool: '需求池',
  done: '已完成',
};
const groupDots: Record<string, string> = {
  developing: 'bg-blue-500',
  testing: 'bg-purple-500',
  releasing: 'bg-emerald-500',
  designing: 'bg-amber-400',
  pool: 'bg-slate-300',
  done: 'bg-slate-300',
};

export default function SwarmView({
  requirements,
  agents,
  priorityFilter,
  onSelectRequirement,
  selectedRequirementId,
}: SwarmViewProps) {
  const filtered =
    priorityFilter === 'all'
      ? requirements
      : requirements.filter((r) => r.priority === priorityFilter);

  // Group by status
  const groups = useMemo<StatusGroup[]>(() => {
    const map = new Map<string, Requirement[]>();
    filtered.forEach((r) => {
      const list = map.get(r.status) || [];
      list.push(r);
      map.set(r.status, list);
    });
    return groupOrder
      .filter((s) => map.has(s) && map.get(s)!.length > 0)
      .map((s) => ({ status: s, label: groupLabels[s] || s, count: map.get(s)!.length, reqs: map.get(s)! }));
  }, [filtered]);

  const totalActive = filtered.filter((r) => hasActiveAgents(r, agents) && r.status !== 'done').length;

  return (
    <div className="flex-1 overflow-y-auto min-w-0 -mx-1 px-1">
      {/* Header */}
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">
          需求列表
        </span>
        <span className="text-[9px] text-slate-400">
          {groups.reduce((s, g) => s + g.count, 0)} 项
          {totalActive > 0 && (
            <span className="ml-1 text-emerald-500">{totalActive} 活跃</span>
          )}
        </span>
      </div>

      {groups.length > 0 ? (
        <div className="space-y-3">
          {groups.map((group) => (
            <div key={group.status}>
              {/* Group header */}
              <div className="flex items-center gap-2 mb-1.5 px-1">
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${groupDots[group.status]}`} />
                <span className="text-[10px] font-medium text-slate-400">{group.label}</span>
                <span className="text-[9px] text-slate-400">{group.count}</span>
              </div>
              {/* Cards */}
              <div className="space-y-1">
                {group.reqs.map((req) => (
                  <SwarmCard
                    key={req.id}
                    requirement={req}
                    agents={agents}
                    isSelected={selectedRequirementId === req.id}
                    onClick={() => onSelectRequirement(req.id)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center text-[11px] text-slate-400 py-12">
          没有匹配的需求
        </div>
      )}
    </div>
  );
}
