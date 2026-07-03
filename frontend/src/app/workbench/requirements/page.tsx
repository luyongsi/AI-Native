'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { Requirement } from '@/lib/types';

const stageOrder = ['pool', 'designing', 'developing', 'testing', 'releasing', 'done'] as const;
const stageLabels: Record<string, string> = {
  pool: '需求池', designing: '设计中', developing: '开发中', testing: '测试中', releasing: '待发布', done: '已上线',
};
const stageColors: Record<string, string> = {
  pool: 'bg-slate-50 border-slate-200', designing: 'bg-amber-50 border-amber-200',
  developing: 'bg-blue-50 border-blue-200', testing: 'bg-purple-50 border-purple-200',
  releasing: 'bg-emerald-50 border-emerald-200', done: 'bg-green-50 border-green-200',
};
const priorityColors: Record<string, string> = {
  P0: 'bg-red-100 text-red-700', P1: 'bg-amber-100 text-amber-700',
  P2: 'bg-blue-100 text-blue-700', P3: 'bg-slate-100 text-slate-600',
};
const wipLimits: Record<string, number> = { pool: 20, designing: 3, developing: 4, testing: 3, releasing: 5, done: 100 };

export default function RequirementsPage() {
  const router = useRouter();
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedReq, setSelectedReq] = useState<Requirement | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'kanban' | 'list' | 'stream'>('kanban');

  // Create modal state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newPriority, setNewPriority] = useState('P2');
  const [creating, setCreating] = useState(false);

  const loadRequirements = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getRequirements({ limit: 200 });
      setRequirements(result.items);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRequirements();
  }, []);

  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  const handleCreate = async () => {
    if (!newTitle.trim()) {
      setToast('请输入需求标题');
      return;
    }
    setCreating(true);
    try {
      await api.createRequirement({
        title: newTitle.trim(),
        priority: newPriority,
        description: newDescription.trim(),
        source_type: 'manual',
      });
      setShowCreateModal(false);
      setNewTitle('');
      setNewDescription('');
      setNewPriority('P2');
      setToast('需求创建成功');
      loadRequirements();
    } catch (e: any) {
      setToast('创建失败: ' + (e.message || '未知错误'));
    } finally {
      setCreating(false);
    }
  };

  const requirementsByStage = stageOrder.reduce((acc, stage) => {
    acc[stage] = requirements.filter((r) => r.status === stage);
    return acc;
  }, {} as Record<string, Requirement[]>);

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex items-center justify-center">
        <div className="text-slate-500 text-sm">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-sm mb-3">加载失败: {error}</div>
          <button onClick={loadRequirements} className="px-4 py-2 bg-slate-900 text-white text-xs rounded-lg hover:bg-slate-800">
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1600px] mx-auto h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h1 className="text-lg font-semibold text-slate-900">需求流</h1>
        <div className="flex items-center gap-2">
          <div className="flex bg-slate-100 rounded-lg p-0.5">
            {(['kanban', 'list', 'stream'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setViewMode(m)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${viewMode === m ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
              >
                {{ kanban: '看板', list: '列表', stream: '价值流' }[m]}
              </button>
            ))}
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-800 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            新建需求
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-shrink-0">
        <select className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-600">
          <option>全部版本</option>
          <option>V2.3.0</option>
          <option>V2.2.0</option>
        </select>
        <select className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-600">
          <option>全部类型</option>
          <option>功能需求</option>
          <option>技术优化</option>
          <option>Bug修复</option>
        </select>
        <select className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-600">
          <option>全部优先级</option>
          <option>P0</option>
          <option>P1</option>
          <option>P2</option>
          <option>P3</option>
        </select>
        <input
          type="text"
          placeholder="搜索需求..."
          className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-600 flex-1 max-w-xs"
        />
        <div className="flex-1" />
        <span className="text-[10px] text-slate-400">共 {requirements.length} 个需求</span>
      </div>

      {/* Kanban View */}
      {viewMode === 'kanban' && (
        <div className="flex-1 flex gap-3 overflow-x-auto pb-4 min-h-0">
          {stageOrder.map((stage) => {
            const reqs = requirementsByStage[stage];
            const count = reqs.length;
            const limit = wipLimits[stage];
            const isOver = count > limit;

            return (
              <div key={stage} className="flex-shrink-0 w-[280px] flex flex-col">
                <div className={`flex items-center justify-between px-3 py-2 rounded-t-xl border ${isOver ? 'bg-red-50 border-red-200' : 'bg-slate-50 border-slate-200'}`}>
                  <div className="flex items-center gap-2">
                    <h3 className={`text-xs font-semibold ${isOver ? 'text-red-700' : 'text-slate-700'}`}>{stageLabels[stage]}</h3>
                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${isOver ? 'bg-red-100 text-red-600' : 'bg-slate-200 text-slate-500'}`}>{count}</span>
                  </div>
                  {isOver && <span className="text-[10px] text-red-500">WIP超限</span>}
                </div>

                <div className={`flex-1 overflow-y-auto p-2 border-x border-b rounded-b-xl ${stageColors[stage]} min-h-[200px]`}>
                  {reqs.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-[10px] text-slate-400">
                      拖拽需求到此列
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {reqs.map((req) => (
                        <button
                          key={req.id}
                          onClick={() => setSelectedReq(req)}
                          className={`w-full text-left p-3 bg-white rounded-xl border border-slate-200 hover:border-slate-300 hover:shadow-sm transition-all cursor-pointer ${selectedReq?.id === req.id ? 'ring-2 ring-slate-900 ring-offset-1' : ''}`}
                        >
                          <div className="flex items-center gap-1.5 mb-1.5">
                            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${priorityColors[req.priority]}`}>{req.priority}</span>
                            <span className="text-[10px] font-mono text-slate-400">{req.id?.slice(0, 8)}</span>
                            {req.blocked && (
                              <span className="flex items-center gap-0.5 text-[10px] text-red-500 ml-auto" title={req.blockReason}>
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m0 0v2m0-2h2m-2 0H10m9.364-7.364A9 9 0 1112 3a9 9 0 017.364 4.636z" />
                                </svg>
                                阻塞
                              </span>
                            )}
                          </div>
                          <p className="text-xs font-medium text-slate-800 mb-1.5 hover:text-blue-600 transition-colors" onClick={(e) => { e.stopPropagation(); router.push(`/requirements/${req.id}`); }}>{req.title}</p>
                          <div className="flex items-center gap-2 text-[10px] text-slate-400">
                            <span>PM: {req.pm || '-'}</span>
                            {req.aiCompletion > 0 && <span>AI: {req.aiCompletion}%</span>}
                          </div>
                          {req.stages && req.stages.filter((s: any) => s.status === 'in_progress' || s.status === 'waiting').length > 0 && (
                            <div className="mt-2 pt-2 border-t border-slate-100">
                              {req.stages
                                .filter((s: any) => s.status === 'in_progress' || s.status === 'waiting')
                                .map((s: any, i: number) => (
                                  <div key={i} className="flex items-center gap-1.5 text-[10px]">
                                    <span className={s.status === 'waiting' ? 'text-amber-500' : 'text-blue-500'}>
                                      {s.status === 'waiting' ? '⏳' : '🔄'}
                                    </span>
                                    <span className="text-slate-500">{s.name}</span>
                                    <span className="text-slate-400">{s.duration}</span>
                                  </div>
                                ))}
                            </div>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* List View */}
      {viewMode === 'list' && (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="py-2 px-3 font-medium">ID</th>
                <th className="py-2 px-3 font-medium">标题</th>
                <th className="py-2 px-3 font-medium">状态</th>
                <th className="py-2 px-3 font-medium">优先级</th>
                <th className="py-2 px-3 font-medium">版本</th>
                <th className="py-2 px-3 font-medium">PM</th>
                <th className="py-2 px-3 font-medium">AI完成度</th>
                <th className="py-2 px-3 font-medium">创建时间</th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((req) => (
                <tr key={req.id} className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={() => setSelectedReq(req)}>
                  <td className="py-2.5 px-3 font-mono text-slate-500">{req.id?.slice(0, 8)}</td>
                  <td className="py-2.5 px-3 text-slate-800">{req.title}</td>
                  <td className="py-2.5 px-3">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                      req.status === 'developing' ? 'bg-blue-100 text-blue-700' :
                      req.status === 'testing' ? 'bg-purple-100 text-purple-700' :
                      req.status === 'done' ? 'bg-green-100 text-green-700' :
                      'bg-slate-100 text-slate-600'
                    }`}>{stageLabels[req.status] || req.status}</span>
                  </td>
                  <td className="py-2.5 px-3"><span className={`text-[10px] px-1.5 py-0.5 rounded ${priorityColors[req.priority] || 'bg-slate-100 text-slate-600'}`}>{req.priority}</span></td>
                  <td className="py-2.5 px-3 text-slate-500">{req.version || '-'}</td>
                  <td className="py-2.5 px-3 text-slate-600">{req.pm || '-'}</td>
                  <td className="py-2.5 px-3">
                    <div className="flex items-center gap-1.5">
                      <div className="w-12 h-1 bg-slate-100 rounded-full overflow-hidden">
                        <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${req.aiCompletion || 0}%` }} />
                      </div>
                      <span className="text-slate-500">{req.aiCompletion || 0}%</span>
                    </div>
                  </td>
                  <td className="py-2.5 px-3 text-slate-400">{req.created_at || req.createdAt || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Value Stream View */}
      {viewMode === 'stream' && (
        <div className="flex-1 overflow-auto space-y-4">
          {requirements.slice(0, 6).map((req) => (
            <div key={req.id} className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center gap-2 mb-4">
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${priorityColors[req.priority] || 'bg-slate-100 text-slate-600'}`}>{req.priority}</span>
                <span className="text-sm font-semibold text-slate-800">{req.id?.slice(0, 8)}: {req.title}</span>
                {req.blocked && <span className="text-[10px] text-red-500 bg-red-50 px-1.5 py-0.5 rounded">阻塞: {req.blockReason}</span>}
              </div>
              {req.stages && (
                <div className="flex items-center gap-1">
                  {req.stages.map((s: any, i: number) => (
                    <div key={i} className="flex items-center gap-1 flex-1">
                      {i > 0 && <div className={`h-px flex-1 ${s.status === 'pending' ? 'bg-slate-200' : 'bg-slate-400'}`} />}
                      <div className={`flex flex-col items-center ${s.status === 'pending' ? 'opacity-30' : ''}`}>
                        <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] border-2 ${
                          s.status === 'done' ? 'bg-emerald-500 border-emerald-500 text-white' :
                          s.status === 'in_progress' ? 'bg-blue-500 border-blue-500 text-white' :
                          s.status === 'waiting' ? 'bg-amber-100 border-amber-400 text-amber-700' :
                          'bg-white border-slate-300 text-slate-300'
                        }`}>
                          {s.status === 'done' ? '✓' : s.status === 'waiting' ? '⏳' : i + 1}
                        </span>
                        <span className="text-[10px] text-slate-500 mt-1 whitespace-nowrap">{s.name}</span>
                        <span className="text-[9px] text-slate-400">{s.duration}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-4 mt-4 pt-3 border-t border-slate-100 text-[10px] text-slate-400">
                <span>AI完成度: {req.aiCompletion || 0}%</span>
                <span>人工介入: {req.humanInterventions || 0}次</span>
                <span>参与: {req.assignees?.join(', ') || '-'}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Detail Drawer */}
      {selectedReq && (
        <>
          <div className="fixed inset-0 bg-black/20 z-40" onClick={() => setSelectedReq(null)} />
          <div className="fixed right-0 top-12 bottom-8 w-[420px] bg-white border-l border-slate-200 z-50 shadow-xl overflow-y-auto">
            <div className="p-5">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-slate-800">{selectedReq.id?.slice(0, 8)}</h2>
                <button onClick={() => setSelectedReq(null)} className="p-1 hover:bg-slate-100 rounded-lg">
                  <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <h3 className="text-lg font-semibold text-slate-900 mb-2">{selectedReq.title}</h3>
              <p className="text-sm text-slate-500 mb-4">{selectedReq.description || '暂无描述'}</p>

              <div className="flex gap-2 mb-4">
                <span className={`text-[10px] font-medium px-2 py-0.5 rounded ${priorityColors[selectedReq.priority] || 'bg-slate-100'}`}>{selectedReq.priority}</span>
                <span className="text-[10px] text-slate-400 bg-slate-100 px-2 py-0.5 rounded">{selectedReq.version || '-'}</span>
                <span className="text-[10px] text-slate-400 bg-slate-100 px-2 py-0.5 rounded">PM: {selectedReq.pm || '-'}</span>
              </div>

              {selectedReq.stages && selectedReq.stages.filter((s: any) => s.status !== 'pending').length > 0 && (
                <div className="mb-4">
                  <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">进度时间轴</h4>
                  <div className="space-y-1.5">
                    {selectedReq.stages.filter((s: any) => s.status !== 'pending').map((s: any, i: number) => (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                          s.status === 'done' ? 'bg-emerald-500' : s.status === 'in_progress' ? 'bg-blue-500' : 'bg-amber-400'
                        }`} />
                        <span className="text-slate-600">{s.name}</span>
                        <span className="text-slate-400 ml-auto">{s.duration}</span>
                        <span className="text-[10px] text-slate-300">基线: {s.baseline}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-2 mb-4">
                <div className="bg-slate-50 rounded-lg p-3 text-center">
                  <div className="text-lg font-bold text-slate-800">{selectedReq.aiCompletion || 0}%</div>
                  <div className="text-[10px] text-slate-400">AI 完成度</div>
                </div>
                <div className="bg-slate-50 rounded-lg p-3 text-center">
                  <div className="text-lg font-bold text-slate-800">{selectedReq.humanInterventions || 0}</div>
                  <div className="text-[10px] text-slate-400">人工介入次数</div>
                </div>
              </div>

              {selectedReq.specSections && selectedReq.specSections.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">Spec 章节</h4>
                  <div className="space-y-1.5">
                    {selectedReq.specSections.map((s: any) => (
                      <div key={s.id} className="flex items-center gap-2 text-xs py-1.5 px-2 rounded hover:bg-slate-50">
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                          s.status === 'done' ? 'bg-emerald-500' : s.status === 'generating' ? 'bg-blue-500 animate-pulse' : s.status === 'editing' ? 'bg-amber-400' : 'bg-slate-300'
                        }`} />
                        <span className="text-slate-700">{s.title}</span>
                        <span className="text-[10px] text-slate-400 ml-auto">{
                          s.status === 'done' ? '已完成' : s.status === 'generating' ? '生成中' : s.status === 'editing' ? '编辑中' : '待定'
                        }</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedReq.relatedIds && selectedReq.relatedIds.length > 0 && (
                <div className="mt-4 pt-4 border-t border-slate-100">
                  <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">关联需求</h4>
                  {selectedReq.relatedIds.map((id: string) => (
                    <span key={id} className="inline-block text-[10px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded mr-1">{id}</span>
                  ))}
                </div>
              )}

              <button onClick={() => { setSelectedReq(null); router.push(`/requirements/${selectedReq?.id}`); }} className="w-full mt-4 py-2.5 bg-slate-900 text-white text-xs font-medium rounded-xl hover:bg-slate-800 transition-colors">
                进入需求工作台
              </button>
            </div>
          </div>
        </>
      )}

      {/* Create Requirement Modal */}
      {showCreateModal && (
        <>
          <div className="fixed inset-0 bg-black/30 z-50" onClick={() => !creating && setShowCreateModal(false)} />
          <div className="fixed inset-0 flex items-center justify-center z-50 pointer-events-none">
            <div className="bg-white rounded-2xl shadow-2xl p-6 w-[480px] max-w-[90vw] pointer-events-auto">
              <div className="flex items-center justify-between mb-5">
                <h2 className="text-base font-semibold text-slate-900">新建需求</h2>
                <button
                  onClick={() => !creating && setShowCreateModal(false)}
                  className="p-1 hover:bg-slate-100 rounded-lg"
                  disabled={creating}
                >
                  <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1.5">需求标题 <span className="text-red-400">*</span></label>
                  <input
                    type="text"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="请输入需求标题"
                    className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:border-slate-400 focus:ring-1 focus:ring-slate-400 transition-colors"
                    autoFocus
                    onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                    disabled={creating}
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1.5">描述</label>
                  <textarea
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder="请输入需求描述（可选）"
                    rows={3}
                    className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:border-slate-400 focus:ring-1 focus:ring-slate-400 transition-colors resize-none"
                    disabled={creating}
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1.5">优先级</label>
                  <div className="flex gap-2">
                    {(['P0', 'P1', 'P2', 'P3'] as const).map((p) => (
                      <button
                        key={p}
                        onClick={() => setNewPriority(p)}
                        disabled={creating}
                        className={`px-4 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                          newPriority === p
                            ? 'bg-slate-900 text-white border-slate-900'
                            : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300'
                        }`}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex gap-2 pt-2">
                  <button
                    onClick={() => !creating && setShowCreateModal(false)}
                    className="flex-1 py-2 text-xs font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors"
                    disabled={creating}
                  >
                    取消
                  </button>
                  <button
                    onClick={handleCreate}
                    disabled={creating || !newTitle.trim()}
                    className="flex-1 py-2 text-xs font-medium text-white bg-slate-900 rounded-lg hover:bg-slate-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {creating ? '创建中...' : '创建需求'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-16 left-1/2 -translate-x-1/2 bg-slate-900 text-white text-xs px-5 py-3 rounded-xl shadow-lg z-50">
          {toast}
          <button onClick={() => setToast(null)} className="ml-3 text-slate-400 hover:text-white">&times;</button>
        </div>
      )}
    </div>
  );
}
