'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { ApprovalItem, Requirement } from '@/lib/types';

const gateColors: Record<string, string> = {
  Gate1: 'bg-amber-100 text-amber-700',
  Gate2: 'bg-blue-100 text-blue-700',
  Gate3: 'bg-purple-100 text-purple-700',
};

export default function ApprovalsPage() {
  const [filter, setFilter] = useState<'all' | 'pending' | 'overdue' | 'done'>('all');
  const [selectedApproval, setSelectedApproval] = useState<string | null>(null);

  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const [approvalsRes, requirementsRes] = await Promise.all([
          api.getApprovals(),
          api.getRequirements(),
        ]);
        if (!cancelled) {
          setApprovals(approvalsRes.items);
          setRequirements(requirementsRes.items);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || '加载审批数据失败');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    fetchData();
    return () => { cancelled = true; };
  }, []);

  const filtered = filter === 'all'
    ? approvals
    : filter === 'done'
      ? approvals.filter((a) => a.status === 'approved')
      : approvals.filter((a) => a.status === filter);

  // --- Loading state ---
  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-lg font-semibold text-slate-900">审批中心</h1>
        </div>
        <div className="flex items-center justify-center py-20 text-sm text-slate-400">
          加载中...
        </div>
      </div>
    );
  }

  // --- Error state ---
  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-lg font-semibold text-slate-900">审批中心</h1>
        </div>
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <p className="text-sm text-red-500">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 text-xs font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200"
          >
            重新加载
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-semibold text-slate-900">审批中心</h1>
        <div className="flex gap-1 bg-slate-100 rounded-lg p-0.5">
          {(['all', 'pending', 'overdue', 'done'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${filter === f ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}
            >
              {{ all: '全部', pending: '待审批', overdue: '已超时', done: '已完成' }[f]}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-4">
        {/* Approval List */}
        <div className="flex-1 space-y-3">
          {filtered.length === 0 ? (
            <div className="flex items-center justify-center py-16 text-xs text-slate-400">
              暂无审批数据
            </div>
          ) : (
            filtered.map((approval) => {
              const req = requirements.find((r) => r.id === approval.requirementId);
              const isSelected = selectedApproval === approval.id;
              const isOverdue = approval.status === 'overdue';

              return (
                <div
                  key={approval.id}
                  className={`bg-white rounded-xl border p-4 transition-all cursor-pointer ${
                    isSelected ? 'border-slate-900 ring-2 ring-slate-900/10' :
                    isOverdue ? 'border-red-200 bg-red-50/30' :
                    'border-slate-200 hover:border-slate-300'
                  }`}
                  onClick={() => setSelectedApproval(approval.id)}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-medium px-2 py-0.5 rounded ${gateColors[approval.gate]}`}>
                        {approval.gate}
                      </span>
                      <span className={`text-[10px] px-2 py-0.5 rounded ${
                        approval.priority === 'high' ? 'bg-red-50 text-red-600' :
                        approval.priority === 'medium' ? 'bg-amber-50 text-amber-600' :
                        'bg-slate-100 text-slate-500'
                      }`}>
                        优先级: {approval.priority === 'high' ? '高' : approval.priority === 'medium' ? '中' : '低'}
                      </span>
                      {isOverdue && <span className="text-[10px] bg-red-100 text-red-600 px-2 py-0.5 rounded">已超时</span>}
                    </div>
                    <span className="text-[10px] text-slate-400">{approval.createdAt}</span>
                  </div>

                  <h3 className="text-sm font-semibold text-slate-900 mb-1.5">{approval.requirementTitle}</h3>
                  <p className="text-xs text-slate-500 mb-3">{approval.requirementId} · 提交者: {approval.submitter}</p>

                  {/* Agent Review Summary */}
                  {approval.agentReviews.length > 0 && (
                    <div className="flex gap-2 mb-3">
                      {approval.agentReviews.map((r, i) => (
                        <span key={i} className={`text-[10px] px-2 py-1 rounded-full ${
                          r.verdict === 'pass' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'
                        }`}>
                          {r.agent}: {r.verdict === 'pass' ? '通过' : '建议'}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-slate-400">
                      SLA 截止: {approval.slaDeadline}
                    </span>
                    <div className="flex gap-2">
                      <button className="px-3 py-1.5 bg-emerald-600 text-white text-[10px] font-medium rounded-lg hover:bg-emerald-700">
                        通过
                      </button>
                      <button className="px-3 py-1.5 bg-white border border-red-200 text-red-600 text-[10px] font-medium rounded-lg hover:bg-red-50">
                        打回
                      </button>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Detail Panel */}
        {selectedApproval ? (
          <div className="w-96 bg-white rounded-xl border border-slate-200 p-5 flex-shrink-0">
            {(() => {
              const approval = approvals.find((a) => a.id === selectedApproval) as (ApprovalItem & { submitterRole?: string }) | undefined;
              if (!approval) return null;

              return (
                <>
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-slate-900">审批详情</h3>
                    <button onClick={() => setSelectedApproval(null)} className="p-1 hover:bg-slate-100 rounded-lg">
                      <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>

                  <h4 className="font-medium text-slate-800 text-sm mb-1">{approval.requirementTitle}</h4>
                  <p className="text-xs text-slate-500 mb-4">{approval.requirementId} · {approval.gate}</p>

                  <div className="bg-slate-50 rounded-xl p-3 mb-4">
                    <div className="text-[10px] text-slate-400 mb-1">提交者</div>
                    <div className="text-xs text-slate-700">{approval.submitter} ({approval.submitterRole})</div>
                    <div className="text-[10px] text-slate-400 mt-2 mb-1">SLA 截止时间</div>
                    <div className={`text-xs ${approval.status === 'overdue' ? 'text-red-600 font-medium' : 'text-slate-700'}`}>
                      {approval.slaDeadline}
                    </div>
                  </div>

                  {approval.agentReviews.length > 0 && (
                    <div className="mb-4">
                      <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">Agent 自评</h4>
                      <div className="space-y-2">
                        {approval.agentReviews.map((r, i) => (
                          <div key={i} className={`p-3 rounded-xl text-xs ${
                            r.verdict === 'pass' ? 'bg-emerald-50 border border-emerald-100' : 'bg-amber-50 border border-amber-100'
                          }`}>
                            <div className="flex items-center gap-1.5 mb-1">
                              <span className={`w-1.5 h-1.5 rounded-full ${r.verdict === 'pass' ? 'bg-emerald-500' : 'bg-amber-400'}`} />
                              <span className="font-medium text-slate-700">{r.agent}</span>
                            </div>
                            <p className="text-[11px] text-slate-500">{r.comment}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <textarea
                    placeholder="输入审批意见..."
                    className="w-full text-xs border border-slate-200 rounded-xl p-3 outline-none focus:border-slate-400 resize-none h-20 mb-3"
                  />

                  <div className="space-y-2">
                    <button className="w-full py-2.5 bg-emerald-600 text-white text-xs font-medium rounded-xl hover:bg-emerald-700">
                      通过审批
                    </button>
                    <button className="w-full py-2.5 bg-white border border-red-200 text-red-600 text-xs font-medium rounded-xl hover:bg-red-50">
                      打回修订
                    </button>
                    <button className="w-full py-2.5 bg-white border border-slate-200 text-slate-500 text-xs font-medium rounded-xl hover:bg-slate-50">
                      带批注通过
                    </button>
                  </div>
                </>
              );
            })()}
          </div>
        ) : (
          <div className="w-96 flex items-center justify-center text-xs text-slate-400">
            选择左侧审批项查看详情
          </div>
        )}
      </div>
    </div>
  );
}
