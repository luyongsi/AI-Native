'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api';
import type {
  Requirement,
  AgentInfo,
  ApprovalItem,
  TopologyNode,
  TopologyEdge,
} from '@/lib/types';

/* ============================================================
   Computed myTasks stats from requirements & approvals data
   ============================================================ */
function computeMyTasks(
  requirements: Requirement[],
  approvals: ApprovalItem[],
) {
  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

  const createdThisWeek = requirements.filter((r) => {
    try {
      return new Date(r.createdAt) >= weekAgo;
    } catch {
      return false;
    }
  }).length;

  const approvedThisWeek = approvals.filter((a) => {
    if (a.status !== 'approved') return false;
    try {
      return new Date(a.createdAt) >= weekAgo;
    } catch {
      return false;
    }
  }).length;

  return {
    weeklyStats: {
      created: createdThisWeek,
      approved: approvedThisWeek,
      avgApprovalTime: '--',
    },
  };
}

export default function DashboardPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [topologyNodes, setTopologyNodes] = useState<TopologyNode[]>([]);
  const [topologyEdges, setTopologyEdges] = useState<TopologyEdge[]>([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [reqRes, agentRes, approvalRes, topoRes] = await Promise.all([
        api.getRequirements(),
        api.getAgents(),
        api.getApprovals(),
        api.getTopology(),
      ]);
      setRequirements(reqRes.items);
      setAgents(agentRes.items);
      setApprovals(approvalRes.items);
      setTopologyNodes(topoRes.nodes);
      setTopologyEdges(topoRes.edges);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to load data';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <h1 className="text-lg font-semibold text-slate-900 mb-6">
          首页 Dashboard
        </h1>
        <div className="flex items-center justify-center py-20">
          <p className="text-slate-500">Loading...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <h1 className="text-lg font-semibold text-slate-900 mb-6">
          首页 Dashboard
        </h1>
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <p className="text-red-500">Error: {error}</p>
          <button
            onClick={fetchData}
            className="px-4 py-2 bg-slate-900 text-white text-sm rounded-lg hover:bg-slate-800 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const myTasks = computeMyTasks(requirements, approvals);

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      <h1 className="text-lg font-semibold text-slate-900 mb-6">
        首页 Dashboard
      </h1>
      <div className="grid grid-cols-3 gap-4">
        {/* Pipeline Widget */}
        <PipelineWidget requirements={requirements} />
        {/* Pending Approvals */}
        <ApprovalWidget approvals={approvals} />
        {/* My Requirements */}
        <MyRequirementsWidget
          requirements={requirements}
          myTasks={myTasks}
        />
        {/* Agent Activity */}
        <AgentActivityWidget agents={agents} />
        {/* Agent Topology Mini */}
        <TopologyWidget
          nodes={topologyNodes}
          edges={topologyEdges}
        />
      </div>
    </div>
  );
}

/* ============================================================
   Widget 1: 实时研发流水线状态条
   ============================================================ */
function PipelineWidget({ requirements }: { requirements: Requirement[] }) {
  const stageOrder = ['pool', 'designing', 'developing', 'testing', 'releasing'];
  const stageLabels: Record<string, string> = {
    pool: '需求池',
    designing: '设计中',
    developing: '开发中',
    testing: '测试中',
    releasing: '待发布',
  };
  const wipLimits: Record<string, number> = {
    pool: 20,
    designing: 3,
    developing: 4,
    testing: 3,
    releasing: 5,
  };

  const counts = stageOrder.reduce(
    (acc, s) => {
      acc[s] = requirements.filter((r) => r.status === s).length;
      return acc;
    },
    {} as Record<string, number>,
  );

  const overWip = stageOrder.filter((s) => counts[s] > wipLimits[s]);

  return (
    <div className="col-span-2 bg-white rounded-2xl border border-slate-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-800">实时研发流水线</h2>
        <span className="text-[10px] text-slate-400 bg-slate-50 px-2 py-1 rounded">
          实时更新
        </span>
      </div>

      <div className="flex items-stretch gap-2">
        {stageOrder.map((stage, i) => {
          const count = counts[stage];
          const isOver = count > wipLimits[stage];
          return (
            <div key={stage} className="flex-1 flex flex-col">
              {i > 0 && (
                <div className="flex items-center justify-center h-8">
                  <svg
                    className="w-3 h-3 text-slate-300"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9 5l7 7-7 7"
                    />
                  </svg>
                </div>
              )}
              <div
                className={`flex-1 rounded-xl p-4 text-center border-2 transition-colors ${
                  isOver
                    ? 'bg-red-50 border-red-200'
                    : 'bg-slate-50 border-transparent hover:border-slate-200'
                }`}
              >
                <div
                  className={`text-2xl font-bold ${isOver ? 'text-red-600' : 'text-slate-800'}`}
                >
                  {count}
                </div>
                <div
                  className={`text-xs mt-1 ${isOver ? 'text-red-500 font-medium' : 'text-slate-500'}`}
                >
                  {stageLabels[stage]}
                </div>
                {isOver && (
                  <div className="text-[10px] text-red-400 mt-1">
                    WIP 超限({wipLimits[stage]})
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Status details */}
      <div className="mt-4 grid grid-cols-5 gap-2">
        {stageOrder.map((stage) => {
          const reqs = requirements.filter((r) => r.status === stage);
          const blocked = reqs.filter((r) => r.blocked).length;
          return (
            <div key={stage} className="text-[10px] text-slate-400">
              {reqs.length > 0 ? (
                <>
                  {blocked > 0 && (
                    <span className="text-red-500">{blocked}个阻塞 </span>
                  )}
                  {reqs.length - blocked > 0 && (
                    <span>{reqs.length - blocked}个正常</span>
                  )}
                </>
              ) : (
                <span>--</span>
              )}
            </div>
          );
        })}
      </div>

      {overWip.length > 0 && (
        <div className="mt-3 flex items-center gap-2 p-2 bg-amber-50 rounded-lg text-xs text-amber-700">
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
          开发中(4) 超过 WIP 限制(4)，建议暂缓低优先级需求
        </div>
      )}
    </div>
  );
}

/* ============================================================
   Widget 2: 待我审批
   ============================================================ */
function ApprovalWidget({ approvals }: { approvals: ApprovalItem[] }) {
  const pendingApprovals = approvals.filter(
    (a) => a.status === 'pending' || a.status === 'overdue',
  );

  return (
    <div className="bg-white rounded-2xl border border-slate-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-800">待我审批</h2>
        <span className="text-[10px] font-medium bg-red-50 text-red-600 px-2 py-0.5 rounded-full">
          {pendingApprovals.length}
        </span>
      </div>

      {pendingApprovals.length === 0 ? (
        <p className="text-xs text-slate-400 py-8 text-center">暂无待审批项</p>
      ) : (
        <div className="space-y-3">
          {pendingApprovals.map((a) => {
            const isOverdue = a.status === 'overdue';
            return (
              <div
                key={a.id}
                className={`p-3 rounded-xl border ${isOverdue ? 'border-red-200 bg-red-50/50' : 'border-slate-100 hover:border-slate-200'} transition-colors`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <span
                    className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${isOverdue ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}
                  >
                    {a.gate}
                  </span>
                  <span
                    className={`text-[10px] ${isOverdue ? 'text-red-500' : 'text-slate-400'}`}
                  >
                    {isOverdue ? '已超时' : a.slaDeadline}
                  </span>
                </div>
                <p className="text-xs font-medium text-slate-800">
                  {a.requirementTitle}
                </p>
                <p className="text-[10px] text-slate-400 mt-0.5">
                  {a.submitter} · {a.createdAt}
                </p>
                <div className="flex gap-2 mt-2">
                  <button className="flex-1 py-1.5 bg-slate-900 text-white text-[10px] font-medium rounded-lg hover:bg-slate-800 transition-colors">
                    通过
                  </button>
                  <button className="flex-1 py-1.5 bg-white border border-slate-200 text-slate-600 text-[10px] font-medium rounded-lg hover:bg-slate-50 transition-colors">
                    打回
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <button className="w-full mt-3 text-[10px] text-slate-400 hover:text-slate-600 transition-colors py-1">
        查看全部审批 &rarr;
      </button>
    </div>
  );
}

/* ============================================================
   Widget 3: 我的需求
   ============================================================ */
function MyRequirementsWidget({
  requirements,
  myTasks,
}: {
  requirements: Requirement[];
  myTasks: ReturnType<typeof computeMyTasks>;
}) {
  const myReqs = requirements;
  const statusColors: Record<string, string> = {
    pool: 'bg-slate-100 text-slate-600',
    designing: 'bg-amber-100 text-amber-700',
    developing: 'bg-blue-100 text-blue-700',
    testing: 'bg-purple-100 text-purple-700',
    releasing: 'bg-emerald-100 text-emerald-700',
    done: 'bg-green-100 text-green-700',
  };
  const statusLabels: Record<string, string> = {
    pool: '需求池',
    designing: '设计中',
    developing: '开发中',
    testing: '测试中',
    releasing: '待发布',
    done: '已上线',
  };

  return (
    <div className="col-span-2 bg-white rounded-2xl border border-slate-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-800">我的需求</h2>
        <button className="text-[10px] text-slate-400 hover:text-slate-600 bg-slate-50 hover:bg-slate-100 px-2 py-1 rounded-lg transition-colors">
          + 新建需求
        </button>
      </div>

      <div className="space-y-1">
        {myReqs.map((req) => (
          <div
            key={req.id}
            className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-slate-50 transition-colors cursor-pointer group"
          >
            <span className="text-xs font-mono text-slate-400 w-20 flex-shrink-0">
              {req.id}
            </span>
            <span className="text-sm text-slate-700 flex-1 truncate">
              {req.title}
            </span>
            <span
              className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${statusColors[req.status] || 'bg-slate-100 text-slate-600'}`}
            >
              {statusLabels[req.status] || req.status}
            </span>
            {req.blocked && (
              <span
                className="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0"
                title={req.blockReason || '阻塞'}
              />
            )}
            <span className="text-[10px] text-slate-300 opacity-0 group-hover:opacity-100 transition-opacity">
              &rarr;
            </span>
          </div>
        ))}
      </div>

      {myTasks.weeklyStats && (
        <div className="mt-4 pt-3 border-t border-slate-100 flex gap-4 text-[10px] text-slate-400">
          <span>
            本周创建:{' '}
            <strong className="text-slate-600">
              {myTasks.weeklyStats.created}
            </strong>
          </span>
          <span>
            本周审批:{' '}
            <strong className="text-slate-600">
              {myTasks.weeklyStats.approved}
            </strong>
          </span>
          <span>
            审批均长:{' '}
            <strong className="text-slate-600">
              {myTasks.weeklyStats.avgApprovalTime}
            </strong>
          </span>
        </div>
      )}
    </div>
  );
}

/* ============================================================
   Widget 4: Agent 实时活动流
   ============================================================ */
function AgentActivityWidget({ agents }: { agents: AgentInfo[] }) {
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

  const statusIcons: Record<string, string> = {
    running: 'bg-emerald-500',
    idle: 'bg-slate-300',
    waiting: 'bg-amber-400',
    error: 'bg-red-500',
  };

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
    think: 'text-purple-600 bg-purple-50',
    tool_call: 'text-blue-600 bg-blue-50',
    code_gen: 'text-emerald-600 bg-emerald-50',
    commit: 'text-slate-600 bg-slate-100',
    test: 'text-cyan-600 bg-cyan-50',
    error: 'text-red-600 bg-red-50',
    wait: 'text-amber-600 bg-amber-50',
  };

  const activeAgents = agents.filter((a) => a.status !== 'idle');

  return (
    <div className="col-span-2 bg-white rounded-2xl border border-slate-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-800">
          Agent 实时活动流
        </h2>
        <div className="flex gap-3 text-[10px] text-slate-400">
          <span>活跃: {activeAgents.length}</span>
          <span>空闲: {agents.filter((a) => a.status === 'idle').length}</span>
          <span className="text-red-500">
            异常: {agents.filter((a) => a.status === 'error').length}
          </span>
        </div>
      </div>

      <div className="space-y-2 max-h-[500px] overflow-y-auto">
        {agents.map((agent) => {
          const isExpanded = expandedAgent === agent.id;
          return (
            <div
              key={agent.id}
              className="border border-slate-100 rounded-xl overflow-hidden"
            >
              {/* Agent row header */}
              <button
                onClick={() =>
                  setExpandedAgent(isExpanded ? null : agent.id)
                }
                className="w-full flex items-center gap-3 p-3 hover:bg-slate-50 transition-colors text-left"
              >
                <span
                  className={`w-2 h-2 rounded-full flex-shrink-0 ${statusIcons[agent.status] || 'bg-slate-300'}`}
                />
                <span className="text-xs font-medium text-slate-700">
                  {agent.name}
                </span>
                {agent.taskId && (
                  <>
                    <span className="text-[10px] text-slate-300">·</span>
                    <span className="text-[10px] text-slate-400 truncate flex-1">
                      {agent.taskName}
                    </span>
                  </>
                )}
                <span className="text-[10px] text-slate-400 flex-shrink-0">
                  {agent.runtime}
                </span>
                {agent.anomaly && (
                  <span className="text-[10px] text-red-500 flex-shrink-0">
                    {agent.anomaly}
                  </span>
                )}
                <svg
                  className={`w-3 h-3 text-slate-300 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M19 9l-7 7-7-7"
                  />
                </svg>
              </button>

              {/* Expanded activity timeline */}
              {isExpanded && agent.lastActivity.length > 0 && (
                <div className="border-t border-slate-50 px-3 pb-3 pt-2 space-y-2 bg-slate-50/50">
                  {agent.lastActivity.map((act, i) => (
                    <div key={i} className="flex gap-3 text-xs">
                      <span className="text-[10px] text-slate-400 flex-shrink-0 w-10 text-right">
                        {act.time}
                      </span>
                      <span
                        className={`text-[10px] font-medium px-1.5 py-0.5 rounded flex-shrink-0 ${typeColors[act.type] || 'text-slate-500 bg-slate-100'}`}
                      >
                        {typeLabels[act.type] || act.type}
                      </span>
                      <span className="text-xs text-slate-600 truncate">
                        {act.content}
                      </span>
                      {act.success === false && (
                        <span className="text-[10px] text-red-500 flex-shrink-0">
                          失败
                        </span>
                      )}
                    </div>
                  ))}
                  {agent.status === 'idle' && (
                    <p className="text-[10px] text-slate-400 text-center py-4">
                      空闲中
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ============================================================
   Widget 5: Agent 协作拓扑图 (迷你版)
   ============================================================ */
function TopologyWidget({
  nodes,
  edges,
}: {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-800">
          Agent 协作拓扑
        </h2>
        <button className="text-[10px] text-slate-400 hover:text-slate-600 transition-colors">
          全屏展开
        </button>
      </div>

      {/* Mini topology using CSS grid positioning */}
      <div className="relative h-64 bg-slate-50/50 rounded-xl overflow-hidden border border-slate-100">
        {/* SVG lines for edges */}
        <svg
          className="absolute inset-0 w-full h-full"
          style={{ zIndex: 1 }}
        >
          <line
            x1="50%"
            y1="12%"
            x2="20%"
            y2="35%"
            stroke="#cbd5e1"
            strokeWidth="1"
          />
          <line
            x1="50%"
            y1="12%"
            x2="50%"
            y2="35%"
            stroke="#cbd5e1"
            strokeWidth="1"
          />
          <line
            x1="50%"
            y1="12%"
            x2="80%"
            y2="35%"
            stroke="#cbd5e1"
            strokeWidth="1"
            strokeDasharray="3,3"
          />
          <line
            x1="20%"
            y1="35%"
            x2="35%"
            y2="58%"
            stroke="#cbd5e1"
            strokeWidth="1"
          />
          <line
            x1="50%"
            y1="35%"
            x2="35%"
            y2="58%"
            stroke="#cbd5e1"
            strokeWidth="1"
          />
          <line
            x1="35%"
            y1="58%"
            x2="8%"
            y2="78%"
            stroke="#cbd5e1"
            strokeWidth="1"
          />
          <line
            x1="35%"
            y1="58%"
            x2="35%"
            y2="78%"
            stroke="#cbd5e1"
            strokeWidth="1"
          />
          <line
            x1="35%"
            y1="58%"
            x2="62%"
            y2="78%"
            stroke="#cbd5e1"
            strokeWidth="1"
          />
          <line
            x1="62%"
            y1="78%"
            x2="80%"
            y2="35%"
            stroke="#cbd5e1"
            strokeWidth="1"
            strokeDasharray="3,3"
          />
          <line
            x1="8%"
            y1="78%"
            x2="22%"
            y2="90%"
            stroke="#cbd5e1"
            strokeWidth="1"
            strokeDasharray="3,3"
          />
          <line
            x1="35%"
            y1="78%"
            x2="22%"
            y2="90%"
            stroke="#cbd5e1"
            strokeWidth="1"
          />
        </svg>

        {/* Node positions (approximating the topology layout) */}
        <div className="absolute inset-0" style={{ zIndex: 2 }}>
          {/* Orchestrator */}
          <div className="absolute left-1/2 -translate-x-1/2 top-[8%] bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span className="text-[10px] font-medium text-slate-700">
                Orchestrator
              </span>
            </div>
          </div>

          {/* PRD Agent */}
          <div className="absolute left-[14%] top-[30%] bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span className="text-[10px] font-medium text-slate-700">
                PRD Agent
              </span>
            </div>
          </div>

          {/* UI Agent */}
          <div className="absolute left-1/2 -translate-x-1/2 top-[30%] bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span className="text-[10px] font-medium text-slate-700">
                UI Agent
              </span>
            </div>
          </div>

          {/* Test Agent */}
          <div className="absolute left-[74%] top-[30%] bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <span className="text-[10px] font-medium text-slate-700">
                Test Agent
              </span>
            </div>
          </div>

          {/* Spec Decomposer */}
          <div className="absolute left-[30%] top-[55%] bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span className="text-[10px] font-medium text-slate-700">
                Spec Decomposer
              </span>
            </div>
          </div>

          {/* DevAgent-1 */}
          <div className="absolute left-[4%] top-[75%] bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              <span className="text-[10px] font-medium text-slate-700">
                DevAgent-1
              </span>
            </div>
          </div>

          {/* DevAgent-2 */}
          <div className="absolute left-[30%] top-[75%] bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              <span className="text-[10px] font-medium text-slate-700">
                DevAgent-2
              </span>
            </div>
          </div>

          {/* DevAgent-3 */}
          <div className="absolute left-[57%] top-[75%] bg-white border border-slate-200 rounded-lg px-2.5 py-1 shadow-sm">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
              <span className="text-[10px] font-medium text-slate-700">
                DevAgent-3
              </span>
            </div>
          </div>

          {/* CI Agent */}
          <div className="absolute left-[16%] top-[88%] bg-white border border-red-200 rounded-lg px-2.5 py-1 shadow-sm bg-red-50/30">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
              <span className="text-[10px] font-medium text-slate-700">
                CI Agent
              </span>
            </div>
          </div>
        </div>

        {/* Legend */}
        <div
          className="absolute bottom-2 right-2 flex gap-2 text-[9px] text-slate-400"
          style={{ zIndex: 3 }}
        >
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            运行中
          </span>
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
            编码中
          </span>
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            等待中
          </span>
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
            异常
          </span>
        </div>
      </div>
    </div>
  );
}
