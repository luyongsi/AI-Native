'use client';

import { useState, useMemo } from 'react';
import type { Requirement, AgentInfo, CodeDiff } from '@/lib/types';
import AgentStatusDot from './AgentStatusDot';
import AgentActivityTimeline from './AgentActivityTimeline';
import CodeDiffViewer from './CodeDiffViewer';

/* ================================================================
   Helpers & config
   ================================================================ */

function getAgentsForReq(req: Requirement, agents: AgentInfo[]): AgentInfo[] {
  const names = new Set(req.stages.filter((s) => s.assignee).map((s) => s.assignee.toLowerCase()));
  return agents.filter((a) => names.has(a.name.toLowerCase()));
}
function getHumanAssignees(req: Requirement, agents: AgentInfo[]): string[] {
  const agentNames = new Set(agents.map((a) => a.name.toLowerCase()));
  return req.assignees.filter((n) => !agentNames.has(n.toLowerCase()));
}

const priorityC: Record<string, string> = {
  P0: 'bg-red-100 text-red-700 border-red-200', P1: 'bg-amber-100 text-amber-700 border-amber-200',
  P2: 'bg-blue-100 text-blue-700 border-blue-200', P3: 'bg-slate-700 text-slate-400 border-slate-700',
};
const statusL: Record<string, string> = {
  pool: '需求池', designing: '设计中', developing: '开发中', testing: '测试中', releasing: '待发布', done: '已上线',
};
const statusBg: Record<string, string> = {
  pool: 'bg-slate-700 text-slate-400', designing: 'bg-amber-50 text-amber-600',
  developing: 'bg-blue-50 text-blue-600', testing: 'bg-purple-50 text-purple-600',
  releasing: 'bg-emerald-50 text-emerald-600', done: 'bg-green-50 text-green-600',
};
const stageDot: Record<string, string> = { done: 'bg-emerald-500', in_progress: 'bg-blue-500', waiting: 'bg-amber-400', pending: 'bg-slate-300' };
const stagePill: Record<string, string> = { done: 'border-emerald-200 text-emerald-700', in_progress: 'border-blue-200 text-blue-700', waiting: 'border-amber-200 text-amber-700', pending: 'border-slate-700 text-slate-400' };
const stageLabel: Record<string, string> = { done: '✓', in_progress: '◉', waiting: '⌛', pending: '○' };

/* ================================================================
   Mini icon SVGs
   ================================================================ */

function IconClock() { return <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>; }
function IconList() { return <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>; }
function IconFile() { return <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>; }
function IconChart() { return <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>; }
function IconDesktop() { return <svg className="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>; }
function IconUser() { return <svg className="w-2.5 h-2.5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>; }
function IconWarning() { return <svg className="w-3 h-3 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>; }
function IconClose() { return <svg className="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>; }
function IconChevronDown() { return <svg className="w-3 h-3 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7"/></svg>; }

/* ================================================================
   Agent Desk Card (selector grid)
   ================================================================ */

function AgentDeskCard({ agent, isSelected, onClick }: { agent: AgentInfo; isSelected: boolean; onClick: () => void }) {
  const errorCount = agent.lastActivity.filter((a) => a.success === false).length;
  return (
    <button onClick={onClick}
      className={`text-left p-2.5 rounded-lg border transition-all ${
        isSelected ? 'border-slate-900 ring-1 ring-slate-900/10 bg-slate-800/50' : 'border-slate-700 bg-slate-800 hover:border-slate-500 hover:bg-slate-800/50/50'
      }`}>
      <div className="flex items-center gap-1.5 mb-1">
        <AgentStatusDot status={agent.status} />
        <span className="text-[11px] font-medium text-slate-200 truncate">{agent.name}</span>
        <span className="text-[9px] text-slate-400 ml-auto flex-shrink-0">{agent.type}</span>
      </div>
      <div className="flex items-center gap-2 text-[9px] text-slate-400">
        {agent.runtime && <span className="flex items-center gap-0.5 text-slate-400"><IconClock />{agent.runtime}</span>}
        <span>{agent.toolCalls > 0 ? `${agent.toolCalls}次` : '空闲'}</span>
        {agent.codeAdded > 0 && <span className="text-emerald-500">+{agent.codeAdded}</span>}
        {agent.codeRemoved > 0 && <span className="text-red-400">-{agent.codeRemoved}</span>}
        {errorCount > 0 && <span className="text-red-500 ml-auto">{errorCount}错</span>}
      </div>
      {agent.anomaly && (
        <div className="mt-1.5 text-[9px] text-red-600 bg-red-50 rounded px-1.5 py-0.5 flex items-center gap-1">
          <IconWarning />{agent.anomaly}
        </div>
      )}
    </button>
  );
}

/* ================================================================
   Agent Workspace
   ================================================================ */

function AgentWorkspace({ agent, requirement, diffs }: { agent: AgentInfo; requirement: Requirement; diffs: CodeDiff[] }) {
  const [activeTab, setActiveTab] = useState<'activity' | 'diffs' | 'stats'>('activity');
  const [expandedDiffId, setExpandedDiffId] = useState<string | null>(null);
  const agentDiffs = diffs.filter((d) => d.agentId === agent.id);
  const allFiles = [...new Set(agentDiffs.map((d) => d.file))];

  const activitySummary = useMemo(() => {
    const counts: Record<string, number> = {};
    agent.lastActivity.forEach((a) => { counts[a.type] = (counts[a.type] || 0) + 1; });
    return counts;
  }, [agent]);

  const successRate = agent.toolCalls > 0 ? Math.round((agent.toolSuccess / agent.toolCalls) * 100) : 0;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Agent header bar */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-slate-800 flex-shrink-0">
        <div className="w-6 h-6 rounded-md bg-slate-800 flex items-center justify-center flex-shrink-0">
          <IconDesktop />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-200">{agent.name}</span>
            <span className="text-[10px] text-slate-400">{agent.type}</span>
            <span className="text-[10px] text-slate-600">|</span>
            <span className="text-[10px] text-slate-400 truncate">{agent.taskName || '空闲'}</span>
          </div>
          <div className="text-[10px] text-slate-400">
            运行 {agent.runtime || '--'} · {agent.toolCalls}次调用 · 成功率 {successRate}%
          </div>
        </div>
        <div className="flex items-center gap-3 text-[10px] flex-shrink-0">
          <StatBadge value={`+${agent.codeAdded}`} color="emerald" />
          <StatBadge value={`-${agent.codeRemoved}`} color="red" />
          <StatBadge value={String(allFiles.length)} color="slate" label="文件" />
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex px-4 border-b border-slate-800 flex-shrink-0 bg-slate-800">
        <TabBtn active={activeTab === 'activity'} onClick={() => setActiveTab('activity')} icon={<IconList />} label="活动时间线" />
        <TabBtn active={activeTab === 'diffs'} onClick={() => setActiveTab('diffs')} icon={<IconFile />} label={`代码变更`} count={allFiles.length} />
        <TabBtn active={activeTab === 'stats'} onClick={() => setActiveTab('stats')} icon={<IconChart />} label="工作统计" />
        <div className="flex-1 border-b-2 border-transparent" />
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {activeTab === 'activity' && (
          <div className="p-4">
            {agent.lastActivity.length > 0 ? (
              <AgentActivityTimeline activities={agent.lastActivity} onViewDiff={(act) => { if (act.diffId) setExpandedDiffId(act.diffId); }} compact />
            ) : (
              <div className="text-center text-[11px] text-slate-400 py-8">空闲中 — 无最近活动</div>
            )}
          </div>
        )}

        {activeTab === 'diffs' && (
          <div className="p-4 space-y-4">
            {agentDiffs.length > 0 ? agentDiffs.map((diff) => (
              <div key={diff.id}>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <IconFile />
                    <span className="text-[11px] font-mono text-slate-400">{diff.file}</span>
                  </div>
                  <span className="text-[10px] text-slate-400">+{diff.addedLines} -{diff.removedLines}</span>
                </div>
                <CodeDiffViewer diff={diff} onClose={expandedDiffId === diff.id ? () => setExpandedDiffId(null) : undefined} />
              </div>
            )) : (
              <div className="text-center text-[11px] text-slate-400 py-8">暂无代码变更</div>
            )}
          </div>
        )}

        {activeTab === 'stats' && (
          <div className="p-4 space-y-5">
            {/* Activity type distribution */}
            <Section title="活动类型分布">
              {Object.keys(activitySummary).length > 0 ? (
                <div className="space-y-1.5">
                  {Object.entries(activitySummary).map(([type, count]) => (
                    <div key={type} className="flex items-center gap-2 text-[10px]">
                      <span className="text-slate-400 w-14 flex-shrink-0">{typeLabels[type] || type}</span>
                      <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                        <div className="h-full bg-slate-400 rounded-full" style={{ width: `${(count / agent.lastActivity.length) * 100}%` }} />
                      </div>
                      <span className="text-slate-400 w-5 text-right flex-shrink-0">{count}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="text-[10px] text-slate-400">暂无数据</p>}
            </Section>

            {/* Tool call stats */}
            <Section title="工具调用">
              <div className="grid grid-cols-4 gap-2">
                <MiniStat value={agent.toolCalls} label="总调用" />
                <MiniStat value={agent.toolSuccess} label="成功" color="emerald" />
                <MiniStat value={agent.toolFailed} label="失败" color="red" />
                <MiniStat value={`${successRate}%`} label="成功率" />
              </div>
            </Section>

            {/* Code impact */}
            <Section title="代码影响">
              <div className="grid grid-cols-3 gap-2">
                <MiniStat value={`+${agent.codeAdded}`} label="新增行" color="emerald" />
                <MiniStat value={`-${agent.codeRemoved}`} label="删除行" color="red" />
                <MiniStat value={allFiles.length} label="文件数" />
              </div>
            </Section>

            {/* Modified files list */}
            {allFiles.length > 0 && (
              <Section title="修改文件">
                <div className="space-y-1">
                  {allFiles.map((f) => (
                    <div key={f} className="flex items-center gap-1.5 text-[10px] text-slate-400 py-1 px-2 bg-slate-800/50 rounded">
                      <IconFile /><span className="font-mono truncate">{f}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Related stages */}
            <Section title="关联需求阶段">
              <div className="flex flex-wrap gap-1">
                {requirement.stages.filter((s) => s.assignee.toLowerCase().includes(agent.name.toLowerCase())).map((s, i) => (
                  <span key={i} className={`text-[9px] px-1.5 py-0.5 rounded border flex items-center gap-1 ${stagePill[s.status]}`}>
                    <span className={`w-1 h-1 rounded-full ${stageDot[s.status]}`} />
                    {s.name}
                  </span>
                ))}
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

/* ================================================================
   Tiny reusable bits
   ================================================================ */

function TabBtn({ active, onClick, icon, label, count }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string; count?: number }) {
  return (
    <button onClick={onClick}
      className={`flex items-center gap-1 px-2.5 py-2 text-[10px] font-medium border-b-2 transition-colors ${
        active ? 'border-slate-900 text-slate-100' : 'border-transparent text-slate-400 hover:text-slate-400'
      }`}>
      {icon} {label}{count !== undefined ? ` (${count})` : ''}
    </button>
  );
}

function StatBadge({ value, color, label }: { value: string; color: 'emerald' | 'red' | 'slate'; label?: string }) {
  const tc = color === 'emerald' ? 'text-emerald-600' : color === 'red' ? 'text-red-500' : 'text-slate-600';
  return (
    <div className="text-center leading-tight">
      <div className={`text-xs font-bold ${tc}`}>{value}</div>
      {label && <div className="text-[9px] text-slate-400">{label}</div>}
    </div>
  );
}

function MiniStat({ value, label, color }: { value: string | number; label: string; color?: 'emerald' | 'red' }) {
  const bg = color === 'emerald' ? 'bg-emerald-50' : color === 'red' ? 'bg-red-50' : 'bg-slate-800/50';
  const tc = color === 'emerald' ? 'text-emerald-600' : color === 'red' ? 'text-red-500' : 'text-slate-600';
  return (
    <div className={`${bg} rounded-lg p-2 text-center`}>
      <div className={`text-xs font-bold ${tc}`}>{value}</div>
      <div className="text-[9px] text-slate-400">{label}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">{title}</h4>
      {children}
    </div>
  );
}

const typeLabels: Record<string, string> = {
  think: '思考', tool_call: '工具调用', code_gen: '代码生成',
  commit: '提交', test: '测试', error: '异常', wait: '等待中',
};

/* ================================================================
   Requirement Detail Panel
   ================================================================ */

interface RequirementDetailPanelProps {
  requirement: Requirement;
  agents: AgentInfo[];
  allDiffs: CodeDiff[];
  onClose: () => void;
}

export default function RequirementDetailPanel({ requirement, agents, allDiffs, onClose }: RequirementDetailPanelProps) {
  const swarmAgents = useMemo(() => getAgentsForReq(requirement, agents), [requirement, agents]);
  const humanAssignees = useMemo(() => getHumanAssignees(requirement, agents), [requirement, agents]);
  const allAssignees = useMemo(
    () => [...swarmAgents, ...humanAssignees.map((n) => ({ id: `human-${n}`, name: n, type: '人工', isHuman: true } as any))],
    [swarmAgents, humanAssignees],
  );

  const [selectedWorkerId, setSelectedWorkerId] = useState<string>(swarmAgents[0]?.id || `human-${humanAssignees[0]}` || '');
  const selectedAgent = swarmAgents.find((a) => a.id === selectedWorkerId) || null;

  const aiPct = requirement.aiCompletion;
  const totalStages = requirement.stages.length;
  const doneStages = requirement.stages.filter((s) => s.status === 'done').length;

  return (
    <div className="flex-1 bg-slate-800 rounded-xl border border-slate-700 flex flex-col min-h-0 overflow-hidden">
      {/* ── Requirement summary bar ── */}
      <div className="flex-shrink-0 px-4 py-2.5 border-b border-slate-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${priorityC[requirement.priority]}`}>{requirement.priority}</span>
            <span className="text-[10px] font-mono text-slate-400 flex-shrink-0">{requirement.id}</span>
            <h3 className="text-xs font-semibold text-slate-200 truncate">{requirement.title}</h3>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0 ${statusBg[requirement.status]}`}>{statusL[requirement.status]}</span>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0 ml-2">
            <span className="text-[10px] text-slate-400">PM {requirement.pm}</span>
            <span className="text-[10px] text-slate-600">|</span>
            <span className="text-[10px] text-slate-400">{doneStages}/{totalStages} Stage</span>
            {aiPct > 0 && (
              <span className="flex items-center gap-1 text-[10px]">
                <span className="text-slate-400">AI</span>
                <span className="font-medium text-emerald-600">{aiPct}%</span>
              </span>
            )}
            <button onClick={onClose} className="p-1 hover:bg-slate-700 rounded-md ml-1"><IconClose /></button>
          </div>
        </div>

        {/* Stage pills row */}
        <div className="flex flex-wrap items-center gap-1 mt-1.5">
          {requirement.stages.map((stage, i) => (
            <span key={i} className={`text-[9px] px-1.5 py-0.5 rounded border flex items-center gap-1 ${stagePill[stage.status]}`}>
              <span className={`w-1 h-1 rounded-full flex-shrink-0 ${stageDot[stage.status]}`} />
              {stage.name}
            </span>
          ))}
        </div>
      </div>

      {/* ── Agent selector grid ── */}
      <div className="flex-shrink-0 px-4 py-2 border-b border-slate-800 bg-slate-800/50/50">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">切换工作桌面</span>
          <span className="text-[10px] text-slate-400">{allAssignees.length} 位协作者</span>
        </div>
        <div className="grid grid-cols-4 gap-2">
          {swarmAgents.map((agent) => (
            <AgentDeskCard key={agent.id} agent={agent} isSelected={selectedWorkerId === agent.id} onClick={() => setSelectedWorkerId(agent.id)} />
          ))}
          {humanAssignees.map((name) => {
            const id = `human-${name}`;
            return (
              <button key={id} onClick={() => setSelectedWorkerId(id)}
                className={`text-left p-2.5 rounded-lg border transition-all ${
                  selectedWorkerId === id ? 'border-blue-400 ring-1 ring-blue-200 bg-blue-50' : 'border-blue-100 bg-blue-50/30 hover:border-blue-200 hover:bg-blue-50'
                }`}>
                <div className="flex items-center gap-1.5 mb-0.5">
                  <div className="w-4 h-4 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0"><IconUser /></div>
                  <span className="text-[11px] font-medium text-blue-700 truncate">{name}</span>
                </div>
                <div className="text-[9px] text-blue-400">人工开发</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Workspace ── */}
      {selectedAgent ? (
        <AgentWorkspace agent={selectedAgent} requirement={requirement} diffs={allDiffs} />
      ) : (
        <div className="flex-1 flex items-center justify-center text-[11px] text-slate-400">选择一个 Agent 查看工作桌面</div>
      )}
    </div>
  );
}
