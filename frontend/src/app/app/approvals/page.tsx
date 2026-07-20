'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { Gate0Approval, Requirement } from '@/lib/types';

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
  const [filter, setFilter] = useState<'all' | 'pending' | 'decided'>('all');

  const [approvals, setApprovals] = useState<Gate0Approval[]>([]);
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
          api.getApprovals({ gate_level: 0, limit: 200 }),
          api.getRequirements(),
        ]);
        if (!cancelled) {
          setApprovals(approvalsRes.items as Gate0Approval[]);
          setRequirements(requirementsRes.items);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || '鍔犺浇瀹℃壒鏁版嵁澶辫触');
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
    : approvals.filter((a) => a.status === filter);

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-lg font-semibold text-slate-100">瀹℃壒涓績</h1>
        </div>
        <div className="flex items-center justify-center py-20 text-sm text-slate-400">
          鍔犺浇涓?..
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-lg font-semibold text-slate-100">瀹℃壒涓績</h1>
        </div>
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <p className="text-sm text-red-500">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 text-xs font-medium text-slate-400 bg-slate-700 rounded-lg hover:bg-slate-600"
          >
            閲嶆柊鍔犺浇
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-semibold text-slate-100">瀹℃壒涓績</h1>
        <div className="flex gap-1 bg-slate-700 rounded-lg p-0.5">
          {(['all', 'pending', 'decided'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                filter === f ? 'bg-slate-800 text-slate-100 shadow-sm' : 'text-slate-400'
              }`}
            >
              {{ all: '全部', pending: '待审批', decided: '已决定' }[f]}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-4">
        {/* Approval List */}
        <div className="flex-1 space-y-3">
          {filtered.length === 0 ? (
            <div className="flex items-center justify-center py-16 text-xs text-slate-400">
              鏆傛棤瀹℃壒鏁版嵁
            </div>
          ) : (
            filtered.map((approval) => {
              const req = requirements.find((r) => r.id === approval.req_id);
              const isPending = approval.status === 'pending';
              const isPass = approval.decision === 'pass';

              return (
                <div
                  key={approval.id}
                  className={`bg-slate-800 rounded-xl border p-4 transition-all cursor-pointer hover:border-slate-500 ${
                    isPending ? 'border-amber-200' :
                    isPass ? 'border-emerald-200' :
                    'border-slate-700'
                  }`}
                  onClick={() => router.push(`/app/approvals/${approval.id}`)}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-medium px-2 py-0.5 rounded ${
                        gateColors[approval.gate_level] || 'bg-slate-700 text-slate-400'
                      }`}>
                        {gateLabels[approval.gate_level] || `Gate${approval.gate_level}`}
                      </span>
                      <span className={`text-[10px] px-2 py-0.5 rounded ${
                        approval.status === 'pending' ? 'bg-amber-50 text-amber-600' :
                        isPass ? 'bg-emerald-50 text-emerald-600' :
                        'bg-red-50 text-red-600'
                      }`}>
                {approval.status === 'pending' ? '待审批' : isPass ? '已通过' : '已拒绝'}
                      </span>
                    </div>
                    <span className="text-[10px] text-slate-400">
                      {approval.created_at ? new Date(approval.created_at).toLocaleString('zh-CN') : '-'}
                    </span>
                  </div>

                  <h3 className="text-sm font-semibold text-slate-100 mb-1.5">
                    {approval.req_title || req?.title || approval.req_id}
                  </h3>
                  <p className="text-xs text-slate-400 mb-3">
                    {approval.req_id} 路 Cycle: {approval.cycle}
                    {approval.reviewer_name && ` 路 瀹℃壒浜? ${approval.reviewer_name}`}
                  </p>

                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-slate-400">
                      {approval.reviewed_at
                        ? `瀹℃壒鏃堕棿: ${new Date(approval.reviewed_at).toLocaleString('zh-CN')}`
                        : approval.gate_meta?.description || ''}
                    </span>
                    <button
                      className="px-3 py-1.5 bg-slate-900 text-white text-[10px] font-medium rounded-lg hover:bg-slate-800"
                      onClick={(e) => {
                        e.stopPropagation();
                        router.push(`/app/approvals/${approval.id}`);
                      }}
                    >
                      {isPending ? '去审批' : '查看详情'}
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
