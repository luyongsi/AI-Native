'use client';

import { useState, useEffect } from 'react';
import ViewSwitcher from './ViewSwitcher';
import AgentStatsBar from './AgentStatsBar';
import LiveTailView from './LiveTailView';
import TopologyView from './TopologyView';
import SwarmView from './SwarmView';
import RequirementDetailPanel from './RequirementDetailPanel';
import { api } from '@/lib/api';
import type { AgentInfo, Requirement, CodeDiff } from '@/lib/types';

type ViewType = 'swarm' | 'livetail' | 'topology';
type AgentFilter = 'all' | 'running' | 'error' | 'idle';
type PriorityFilter = 'all' | 'P0' | 'P1' | 'P2' | 'P3';

export default function AgentCenterApp() {
  const [activeView, setActiveView] = useState<ViewType>('swarm');
  const [agentFilter, setAgentFilter] = useState<AgentFilter>('all');
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>('all');
  const [selectedRequirementId, setSelectedRequirementId] = useState<string | null>(null);

  // Data state
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [codeDiffs, setCodeDiffs] = useState<CodeDiff[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        setError(null);
        const [agentsRes, reqsRes] = await Promise.all([
          api.getAgents(),
          api.getRequirements(),
        ]);
        setAgents(agentsRes.items);
        setRequirements(reqsRes.items);
      } catch (err: any) {
        setError(err.message || '加载数据失败');
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  // Lazy-load diffs when a requirement is selected (if not already cached)
  useEffect(() => {
    if (!selectedRequirementId) return;
    // Only fetch if we have agents loaded and haven't fetched diffs yet
    if (agents.length === 0) return;
    // Fetch diffs for all agents associated with this requirement
    async function loadDiffs() {
      try {
        const diffResults = await Promise.allSettled(
          agents.map((a) => api.getAgentDiffs(a.id))
        );
        const allDiffs: CodeDiff[] = [];
        diffResults.forEach((result) => {
          if (result.status === 'fulfilled') {
            allDiffs.push(...result.value.diffs);
          }
        });
        setCodeDiffs(allDiffs);
      } catch {
        // Diffs are optional; keep whatever we had
      }
    }
    loadDiffs();
  }, [selectedRequirementId, agents]);

  const selectedRequirement = selectedRequirementId
    ? requirements.find((r) => r.id === selectedRequirementId) ?? null
    : null;

  // Loading state
  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex flex-col">
        <div className="flex items-center justify-between mb-4 flex-shrink-0">
          <h1 className="text-lg font-semibold text-slate-100">Agent 中心</h1>
          <ViewSwitcher activeView={activeView} onViewChange={setActiveView} />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <svg
              className="animate-spin w-6 h-6 text-slate-400"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            <span className="text-xs text-slate-400">加载中...</span>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex flex-col">
        <div className="flex items-center justify-between mb-4 flex-shrink-0">
          <h1 className="text-lg font-semibold text-slate-100">Agent 中心</h1>
          <ViewSwitcher activeView={activeView} onViewChange={setActiveView} />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <svg
              className="w-8 h-8 text-red-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
              />
            </svg>
            <span className="text-xs text-red-500">{error}</span>
            <button
              onClick={() => window.location.reload()}
              className="text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg text-slate-400 transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1600px] mx-auto h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h1 className="text-lg font-semibold text-slate-100">Agent 中心</h1>
        <ViewSwitcher activeView={activeView} onViewChange={setActiveView} />
      </div>

      {/* Stats Bar */}
      <AgentStatsBar
        agents={agents}
        agentFilter={agentFilter}
        onAgentFilterChange={setAgentFilter}
        priorityFilter={priorityFilter}
        onPriorityFilterChange={setPriorityFilter}
        showPriorityFilter={activeView === 'swarm'}
      />

      {/* Views */}
      {activeView === 'swarm' && (
        <div className="flex-1 flex gap-4 min-h-0">
          {/* Left: requirement list (compact, narrower) */}
          <div className="w-80 flex-shrink-0 flex flex-col min-h-0">
            {requirements.length > 0 ? (
              <SwarmView
                requirements={requirements}
                agents={agents}
                priorityFilter={priorityFilter}
                onSelectRequirement={setSelectedRequirementId}
                selectedRequirementId={selectedRequirementId}
              />
            ) : (
              <div className="flex-1 flex items-center justify-center text-xs text-slate-400 bg-slate-800 rounded-xl border border-slate-700">
                暂无需求数据
              </div>
            )}
          </div>
          {/* Right: detail panel (takes remaining space) */}
          {selectedRequirement ? (
            <RequirementDetailPanel
              requirement={selectedRequirement}
              agents={agents}
              allDiffs={codeDiffs}
              onClose={() => setSelectedRequirementId(null)}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-xs text-slate-400 bg-slate-800 rounded-xl border border-slate-700">
              选择左侧需求查看 Agent 工作桌面
            </div>
          )}
        </div>
      )}

      {activeView === 'livetail' && <LiveTailView filter={agentFilter} agents={agents} />}

      {activeView === 'topology' && <TopologyView />}
    </div>
  );
}
