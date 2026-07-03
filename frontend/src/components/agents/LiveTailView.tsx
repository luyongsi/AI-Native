'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import { wsClient } from '@/lib/ws';
import type { AgentInfo } from '@/lib/types';
import AgentStatusDot from './AgentStatusDot';
import AgentActivityTimeline from './AgentActivityTimeline';
import AgentActionBar from './AgentActionBar';

const statusConfig: Record<string, { color: string; label: string }> = {
  running: { color: 'text-emerald-600 bg-emerald-50', label: '运行中' },
  idle: { color: 'text-slate-500 bg-slate-100', label: '空闲' },
  waiting: { color: 'text-amber-600 bg-amber-50', label: '等待中' },
  error: { color: 'text-red-600 bg-red-50', label: '异常' },
};

const anomalyRules = [
  { type: '卡住', condition: '同一状态 >5min', icon: '⏸️', color: 'text-amber-500' },
  { type: '失败', condition: '任务返回错误', icon: '❌', color: 'text-red-500' },
  { type: '慢', condition: '耗时 >3x 平均', icon: '🐢', color: 'text-amber-500' },
  { type: '工具故障', condition: '连续失败3次', icon: '🔧', color: 'text-red-500' },
  { type: '超时', condition: '超过预估2x', icon: '⏰', color: 'text-amber-500' },
  { type: '无进展', condition: '30min无修改', icon: '😴', color: 'text-slate-400' },
];

interface LiveTailViewProps {
  filter: 'all' | 'running' | 'error' | 'idle';
  agents?: AgentInfo[];
}

export default function LiveTailView({ filter, agents: externalAgents }: LiveTailViewProps) {
  const [internalAgents, setInternalAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(!externalAgents);
  const [error, setError] = useState<string | null>(null);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<AgentInfo | null>(null);

  // Use external agents if provided, otherwise fetch internally
  const agents: AgentInfo[] = externalAgents ?? internalAgents;

  // Internal fetch (only when no external agents provided)
  useEffect(() => {
    if (externalAgents !== undefined) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function loadAgents() {
      try {
        setLoading(true);
        setError(null);
        const res = await api.getAgents();
        if (!cancelled) {
          setInternalAgents(res.items);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err.message || '加载 Agent 数据失败');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadAgents();

    return () => {
      cancelled = true;
    };
  }, [externalAgents]);

  // Subscribe to agent status changes via WebSocket
  useEffect(() => {
    if (externalAgents !== undefined) return; // parent manages data when external

    const handleStatusChange = (data: any) => {
      const agentId = data.agent_id || data.agentId;
      const newStatus = data.status;
      if (!agentId || !newStatus) return;

      setInternalAgents((prev) =>
        prev.map((a) => (a.id === agentId ? { ...a, status: newStatus } : a))
      );
    };

    wsClient.on('agent.status.changed', handleStatusChange);

    return () => {
      wsClient.off('agent.status.changed', handleStatusChange);
    };
  }, [externalAgents]);

  const filteredAgents =
    filter === 'all' ? agents : agents.filter((a) => a.status === filter);

  const hasAnomalies = agents.some((a) => a.anomaly);

  // Loading state
  if (loading) {
    return (
      <div className="flex-1 flex gap-4 min-h-0">
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
            <span className="text-xs text-slate-400">加载 Agent 数据...</span>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex-1 flex gap-4 min-h-0">
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
              className="text-xs px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded-lg text-slate-600 transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Empty state
  if (agents.length === 0) {
    return (
      <div className="flex-1 flex gap-4 min-h-0">
        <div className="flex-1 flex items-center justify-center">
          <span className="text-xs text-slate-400">暂无 Agent 数据</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex gap-4 min-h-0">
      {/* Agent List */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Anomaly alert banner */}
        {hasAnomalies && (
          <div className="mb-3 p-2.5 bg-red-50 border border-red-100 rounded-xl flex items-center gap-2 text-xs text-red-600 flex-shrink-0">
            <svg
              className="w-3.5 h-3.5 flex-shrink-0"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
              />
            </svg>
            CIAgent-1 构建失败，已通知相关人员
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-2">
          {filteredAgents.length > 0 ? (
            filteredAgents.map((agent) => {
              const isExpanded = expandedAgent === agent.id;
              const config = statusConfig[agent.status];

              return (
                <div
                  key={agent.id}
                  className="border border-slate-200 rounded-xl overflow-hidden bg-white"
                >
                  {/* Agent Row */}
                  <button
                    onClick={() => {
                      setExpandedAgent(isExpanded ? null : agent.id);
                      setSelectedAgent(agent);
                    }}
                    className={`w-full flex items-center gap-3 p-3.5 hover:bg-slate-50 transition-colors text-left ${
                      isExpanded ? 'bg-slate-50' : ''
                    }`}
                  >
                    <AgentStatusDot status={agent.status} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-slate-800">{agent.name}</span>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded-full ${config.color}`}
                        >
                          {config.label}
                        </span>
                      </div>
                      {agent.taskId && (
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[10px] text-slate-400">{agent.taskId}</span>
                          <span className="text-[10px] text-slate-400">·</span>
                          <span className="text-[10px] text-slate-500 truncate">
                            {agent.taskName}
                          </span>
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-[10px] text-slate-400 flex-shrink-0">
                      {agent.runtime && <span>运行: {agent.runtime}</span>}
                      {agent.toolCalls > 0 && (
                        <span>
                          工具调用 {agent.toolCalls}次
                          {agent.toolFailed > 0 && (
                            <span className="text-red-500"> ({agent.toolFailed}失败)</span>
                          )}
                        </span>
                      )}
                    </div>
                    {agent.anomaly && (
                      <span className="text-[10px] text-red-500 font-medium flex-shrink-0">
                        {agent.anomaly}
                      </span>
                    )}
                    <svg
                      className={`w-3 h-3 text-slate-300 transition-transform flex-shrink-0 ${
                        isExpanded ? 'rotate-180' : ''
                      }`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {/* Expanded Activity Timeline */}
                  {isExpanded && (
                    <div className="border-t border-slate-100 px-4 pb-4 pt-3 bg-slate-50/50">
                      <AgentActivityTimeline activities={agent.lastActivity} />
                    </div>
                  )}

                  {/* Action Bar */}
                  {isExpanded && (
                    <AgentActionBar
                      agent={agent}
                      onViewDiff={() => {}}
                    />
                  )}
                </div>
              );
            })
          ) : (
            <div className="text-center text-xs text-slate-400 py-12">
              没有匹配的 Agent
            </div>
          )}
        </div>
      </div>

      {/* Agent Detail Panel */}
      {selectedAgent && (
        <div className="w-80 bg-white rounded-xl border border-slate-200 flex-shrink-0 overflow-y-auto">
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <AgentStatusDot status={selectedAgent.status} />
                <h3 className="text-sm font-semibold text-slate-800">
                  {selectedAgent.name}
                </h3>
              </div>
              <button
                onClick={() => setSelectedAgent(null)}
                className="p-1 hover:bg-slate-100 rounded-lg"
              >
                <svg
                  className="w-3.5 h-3.5 text-slate-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>

            {selectedAgent.taskId && (
              <div className="text-xs text-slate-500 mb-3">
                关联任务: {selectedAgent.taskId} ({selectedAgent.taskName})
              </div>
            )}

            {/* Stats */}
            {selectedAgent.toolCalls > 0 && (
              <div className="grid grid-cols-2 gap-2 mb-4">
                <div className="bg-slate-50 rounded-lg p-2.5 text-center">
                  <div className="text-lg font-bold text-slate-800">
                    {selectedAgent.toolCalls}
                  </div>
                  <div className="text-[10px] text-slate-400">工具调用</div>
                </div>
                <div className="bg-slate-50 rounded-lg p-2.5 text-center">
                  <div className="text-lg font-bold text-slate-800">
                    {selectedAgent.toolSuccess}/{selectedAgent.toolCalls}
                  </div>
                  <div className="text-[10px] text-slate-400">成功率</div>
                </div>
                <div className="bg-slate-50 rounded-lg p-2.5 text-center">
                  <div className="text-lg font-bold text-emerald-600">
                    +{selectedAgent.codeAdded}
                  </div>
                  <div className="text-[10px] text-slate-400">新增行</div>
                </div>
                <div className="bg-slate-50 rounded-lg p-2.5 text-center">
                  <div className="text-lg font-bold text-red-500">
                    -{selectedAgent.codeRemoved}
                  </div>
                  <div className="text-[10px] text-slate-400">删除行</div>
                </div>
              </div>
            )}

            {/* Anomaly Rules */}
            <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">
              异常检测规则
            </h4>
            <div className="space-y-1.5 mb-4">
              {anomalyRules.map((rule, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 text-[10px] py-1 px-2 rounded hover:bg-slate-50"
                >
                  <span className="w-5 text-center">{rule.icon}</span>
                  <span className="text-slate-600">{rule.type}</span>
                  <span className="text-slate-400 ml-auto">{rule.condition}</span>
                </div>
              ))}
            </div>

            {/* Time Distribution */}
            {selectedAgent.toolCalls > 0 && (
              <>
                <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">
                  耗时分布
                </h4>
                <div className="space-y-1.5">
                  {[
                    { label: '思考', pct: 45, color: 'bg-purple-500' },
                    { label: '工具调用', pct: 30, color: 'bg-blue-500' },
                    { label: '代码生成', pct: 20, color: 'bg-emerald-500' },
                    { label: '等待', pct: 5, color: 'bg-slate-300' },
                  ].map((d) => (
                    <div key={d.label} className="flex items-center gap-2 text-[10px]">
                      <span className="text-slate-500 w-14">{d.label}</span>
                      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${d.color}`}
                          style={{ width: `${d.pct}%` }}
                        />
                      </div>
                      <span className="text-slate-400 w-8 text-right">{d.pct}%</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
