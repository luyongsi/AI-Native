'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { Gate0Approval } from '@/lib/types';

const gateColors: Record<number, string> = {
  0: 'bg-violet-100 text-violet-700',
  1: 'bg-amber-100 text-amber-700',
  2: 'bg-blue-100 text-blue-700',
  3: 'bg-purple-100 text-purple-700',
};

const gateLabels: Record<number, string> = {
  0: 'Gate0',
  1: 'Gate1',
  2: 'Gate2',
  3: 'Gate3',
};

export default function ApprovalsPage() {
  const router = useRouter();
  const [approvals, setApprovals] = useState<Gate0Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'pending' | 'decided'>('all');

  useEffect(() => {
    api.getApprovals({ gate_level: 0, limit: 200 })
      .then((res) => setApprovals(res.items as Gate0Approval[]))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = filter === 'all'
    ? approvals
    : approvals.filter((a) => a.status === filter);

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-slate-400">加载审批数据中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-red-500 mb-3">加载失败: {error}</p>
          <button
            onClick={() => {
              setError(null);
              setLoading(true);
              api.getApprovals({ limit: 200 })
                .then((res) => setApprovals(res.items as Gate0Approval[]))
                .catch((e) => setError(e.message))
                .finally(() => setLoading(false));
            }}
            className="px-4 py-2 bg-slate-900 text-white text-xs rounded-lg hover:bg-slate-800"
          >
            重试
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
          {(['all', 'pending', 'decided'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                filter === f ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'
              }`}
            >
              {{ all: '全部', pending: '待审批', decided: '已决策' }[f]}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-4">
        {/* Approval List */}
        <div className="flex-1 space-y-3">
          {filtered.length === 0 && (
            <div className="text-center py-12 text-xs text-slate-400">暂无审批记录</div>
          )}
          {filtered.map((approval) => {
            const isPending = approval.status === 'pending';
            const isPass = approval.decision === 'pass';

            return (
              <div
                key={approval.id}
                className={`bg-white rounded-xl border p-4 transition-all cursor-pointer hover:border-slate-300 ${
                  isPending ? 'border-amber-200' :
                  isPass ? 'border-emerald-200' :
                  'border-slate-200'
                }`}
                onClick={() => router.push(`/approvals/${approval.id}`)}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-medium px-2 py-0.5 rounded ${
                      gateColors[approval.gate_level] || 'bg-slate-100 text-slate-500'
                    }`}>
                      {gateLabels[approval.gate_level] || `Gate${approval.gate_level}`}
                    </span>
                    <span className={`text-[10px] px-2 py-0.5 rounded ${
                      isPending ? 'bg-amber-50 text-amber-600' :
                      isPass ? 'bg-emerald-50 text-emerald-600' :
                      'bg-red-50 text-red-600'
                    }`}>
                      {isPending ? '待审批' : isPass ? '已通过' : '已拒绝'}
                    </span>
                  </div>
                  <span className="text-[10px] text-slate-400">
                    {approval.created_at ? new Date(approval.created_at).toLocaleString('zh-CN') : '-'}
                  </span>
                </div>

                <h3 className="text-sm font-semibold text-slate-900 mb-1.5">
                  {approval.req_title || approval.req_id}
                </h3>
                <p className="text-xs text-slate-500 mb-3">
                  {approval.req_id} · Cycle: {approval.cycle}
                  {approval.reviewer_name && ` · 审批人: ${approval.reviewer_name}`}
                </p>

                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400">
                    {approval.reviewed_at
                      ? `审批时间: ${new Date(approval.reviewed_at).toLocaleString('zh-CN')}`
                      : approval.gate_meta?.description || ''}
                  </span>
                  <button
                    className="px-3 py-1.5 bg-slate-900 text-white text-[10px] font-medium rounded-lg hover:bg-slate-800"
                    onClick={(e) => {
                      e.stopPropagation();
                      router.push(`/approvals/${approval.id}`);
                    }}
                  >
                    {isPending ? '去审批' : '查看详情'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
