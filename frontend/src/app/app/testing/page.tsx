'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { Requirement } from '@/lib/types';

// ============================================================
// Local types (testing-specific, not in @/lib/types)
// ============================================================
type TestReadinessStatus = 'not_started' | 'in_review' | 'approved' | 'rejected';

const readinessLabel: Record<string, string> = {
  not_started: '未开始',
  in_review: '待审核',
  approved: '已通过',
  rejected: '已打回',
};

const readinessColor: Record<string, string> = {
  not_started: 'bg-slate-700 text-slate-400',
  in_review: 'bg-amber-100 text-amber-600',
  approved: 'bg-emerald-100 text-emerald-600',
  rejected: 'bg-red-100 text-red-600',
};

export default function TestingIndexPage() {
  const router = useRouter();

  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getRequirements({ limit: 200 })
      .then((res) => setRequirements(res.items || []))
      .catch((err) =>
        setError(err instanceof Error ? err.message : '加载需求列表失败')
      )
      .finally(() => setLoading(false));
  }, []);

  // Only show requirements that are in testing phase or later (with test cases)
  const testableReqs = requirements.filter(
    (r) => r.status === 'testing' || r.status === 'releasing' || r.status === 'done' || r.status === 'developing'
  );

  // Readiness defaults to 'not_started' since there is no direct readiness API
  const readinessMap: Record<string, TestReadinessStatus> = {};
  for (const req of testableReqs) {
    readinessMap[req.id] = 'not_started';
  }

  // ---- Loading State ----
  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-slate-700 border-t-slate-600 rounded-full animate-spin" />
          <p className="text-sm text-slate-400">加载需求列表...</p>
        </div>
      </div>
    );
  }

  // ---- Error State ----
  if (error) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center max-w-md">
          <p className="text-sm font-medium text-red-700 mb-2">加载失败</p>
          <p className="text-xs text-red-500">{error}</p>
          <button
            onClick={() => {
              setLoading(true);
              setError(null);
              api
                .getRequirements({ limit: 200 })
                .then((res) => setRequirements(res.items || []))
                .catch((err) =>
                  setError(err instanceof Error ? err.message : '加载需求列表失败')
                )
                .finally(() => setLoading(false));
            }}
            className="mt-3 text-xs px-4 py-1.5 bg-slate-800 border border-red-200 rounded-lg text-red-600 hover:bg-red-50"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  // ---- Empty State ----
  if (testableReqs.length === 0) {
    return (
      <div className="p-6">
        {/* Page Header */}
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-slate-100">测试工作台</h1>
          <p className="text-xs text-slate-400 mt-1">选择一个需求，进入测试工作台进行用例编写与执行</p>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { label: '待测试需求', value: 0, color: 'text-purple-600' },
            { label: '测试用例总数', value: '10', color: 'text-blue-600' },
            { label: '今日通过率', value: '87%', color: 'text-emerald-600' },
            { label: 'AI 生成占比', value: '60%', color: 'text-amber-600' },
          ].map((stat) => (
            <div key={stat.label} className="bg-slate-800 rounded-xl border border-slate-700 p-4">
              <p className="text-[10px] text-slate-400 uppercase tracking-wider">{stat.label}</p>
              <p className={`text-2xl font-bold mt-1 ${stat.color}`}>{stat.value}</p>
            </div>
          ))}
        </div>

        {/* Empty Requirements List */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <h2 className="text-xs font-semibold text-slate-200">可测需求列表</h2>
            <div className="flex items-center gap-2">
              <input
                placeholder="搜索需求..."
                className="text-xs border border-slate-700 rounded-lg px-3 py-1.5 outline-none focus:border-slate-400 w-48"
              />
            </div>
          </div>
          <div className="flex flex-col items-center justify-center py-16 text-slate-400 gap-2">
            <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-[10px]">暂无处于测试阶段的需求</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Page Header */}
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-slate-100">测试工作台</h1>
        <p className="text-xs text-slate-400 mt-1">选择一个需求，进入测试工作台进行用例编写与执行</p>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: '待测试需求', value: testableReqs.filter(r => r.status === 'testing').length, color: 'text-purple-600' },
          { label: '测试用例总数', value: '10', color: 'text-blue-600' },
          { label: '今日通过率', value: '87%', color: 'text-emerald-600' },
          { label: 'AI 生成占比', value: '60%', color: 'text-amber-600' },
        ].map((stat) => (
          <div key={stat.label} className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <p className="text-[10px] text-slate-400 uppercase tracking-wider">{stat.label}</p>
            <p className={`text-2xl font-bold mt-1 ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Requirements List */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h2 className="text-xs font-semibold text-slate-200">可测需求列表</h2>
          <div className="flex items-center gap-2">
            <input
              placeholder="搜索需求..."
              className="text-xs border border-slate-700 rounded-lg px-3 py-1.5 outline-none focus:border-slate-400 w-48"
            />
          </div>
        </div>

        <div className="divide-y divide-slate-800">
          {testableReqs.map((req) => {
            const readiness = readinessMap[req.id] || 'not_started';

            return (
              <button
                key={req.id}
                onClick={() => router.push(`/app/testing/${req.id}`)}
                className="w-full text-left px-4 py-3 hover:bg-slate-800/50 transition-colors flex items-center justify-between group"
              >
                <div className="flex items-center gap-3">
                  {/* Requirement badge */}
                  <span className="text-[10px] font-mono text-slate-400 bg-slate-800/50 px-1.5 py-0.5 rounded">
                    {req.id}
                  </span>
                  <div>
                    <h3 className="text-sm font-medium text-slate-200 group-hover:text-slate-100">
                      {req.title}
                    </h3>
                    <p className="text-[10px] text-slate-400 mt-0.5">
                      PM: {req.pm}  状态: {req.status === 'testing' ? '测试中' : req.status === 'developing' ? '开发中' : req.status === 'releasing' ? '待发布' : '已上线'}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  {/* Priority */}
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                    req.priority === 'P0' ? 'bg-red-50 text-red-600' :
                    req.priority === 'P1' ? 'bg-amber-50 text-amber-600' :
                    'bg-slate-700 text-slate-400'
                  }`}>
                    {req.priority}
                  </span>

                  {/* Readiness status */}
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${readinessColor[readiness]}`}>
                    测试就绪: {readinessLabel[readiness]}
                  </span>

                  {/* Arrow */}
                  <svg className="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}