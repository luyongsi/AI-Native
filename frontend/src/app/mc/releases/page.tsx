'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { Release } from '@/lib/types';

export default function ReleasesPage() {
  const [release, setRelease] = useState<Release | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getReleases()
      .then((res) => {
        const first = res.items?.[0] ?? null;
        setRelease(first);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : '获取版本信息失败');
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center min-h-[300px]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-slate-200 border-t-slate-600 rounded-full animate-spin" />
          <span className="text-xs text-slate-400">加载版本信息中…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center min-h-[300px]">
        <div className="flex flex-col items-center gap-3">
          <svg className="w-8 h-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          </svg>
          <span className="text-xs text-slate-500">{error}</span>
          <button
            onClick={() => {
              setLoading(true);
              setError(null);
              api
                .getReleases()
                .then((res) => {
                  setRelease(res.items?.[0] ?? null);
                })
                .catch((err) => {
                  setError(err instanceof Error ? err.message : '获取版本信息失败');
                })
                .finally(() => setLoading(false));
            }}
            className="px-3 py-1.5 text-xs text-slate-500 bg-white border border-slate-200 rounded-lg hover:bg-slate-50"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  if (!release) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center min-h-[300px]">
        <span className="text-xs text-slate-400">暂无版本信息</span>
      </div>
    );
  }

  const progress = (release.completedReqs / release.totalReqs) * 100;

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">版本发布 — {release.version}</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            发布窗口: {release.releaseWindow} · 剩余: 15天
          </p>
        </div>
        <span className={`text-xs px-3 py-1.5 rounded-full font-medium ${
          release.status === 'developing' ? 'bg-amber-100 text-amber-700' :
          release.status === 'released' ? 'bg-emerald-100 text-emerald-600' :
          'bg-slate-100 text-slate-600'
        }`}>
          {{ planning: '规划中', developing: '开发中', testing: '测试中', releasing: '发布中', released: '已发布' }[release.status]}
        </span>
      </div>

      {/* Progress */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 mb-4">
        <h2 className="text-sm font-semibold text-slate-800 mb-4">版本进度</h2>
        <div className="flex items-center gap-4 mb-4">
          <div className="flex-1 h-3 bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 rounded-full transition-all" style={{ width: `${progress}%` }} />
          </div>
          <span className="text-sm font-bold text-slate-800">{Math.round(progress)}%</span>
        </div>
        <div className="grid grid-cols-5 gap-4 text-center text-xs">
          {[
            { label: '需求录入', pct: 100 },
            { label: '设计评审', pct: 60 },
            { label: '开发阶段', pct: 20 },
            { label: '测试阶段', pct: 0 },
            { label: '发布', pct: 0 },
          ].map((s) => (
            <div key={s.label}>
              <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden mb-1.5">
                <div className={`h-full rounded-full ${s.pct > 0 ? 'bg-blue-500' : 'bg-transparent'}`} style={{ width: `${s.pct}%` }} />
              </div>
              <span className="text-[10px] text-slate-400">{s.label}</span>
              <span className="text-[10px] text-slate-500 ml-1">{s.pct}%</span>
            </div>
          ))}
        </div>
        <div className="flex gap-4 mt-4 text-[10px] text-slate-500">
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />正常: 12</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" />风险: 2</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-500" />阻塞: 1</span>
        </div>
      </div>

      {/* Requirements List */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 mb-4">
        <h2 className="text-sm font-semibold text-slate-800 mb-3">关联需求 ({release.requirements?.length ?? 0}/{release.totalReqs})</h2>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-100 text-left text-slate-400">
              <th className="py-2 font-medium">ID</th>
              <th className="py-2 font-medium">标题</th>
              <th className="py-2 font-medium">状态</th>
              <th className="py-2 font-medium">PM</th>
            </tr>
          </thead>
          <tbody>
            {release.requirements?.map((req) => (
              <tr key={req.id} className="border-b border-slate-50 hover:bg-slate-50/50">
                <td className="py-2 font-mono text-slate-500">{req.id}</td>
                <td className="py-2 text-slate-700">{req.title}</td>
                <td className="py-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                    req.status.includes('阻塞') ? 'bg-red-50 text-red-600' :
                    req.status.includes('中') ? 'bg-blue-50 text-blue-600' :
                    'bg-slate-100 text-slate-500'
                  }`}>{req.status}</span>
                </td>
                <td className="py-2 text-slate-500">{req.pm}</td>
              </tr>
            ))}
            {(!release.requirements || release.requirements.length === 0) && (
              <tr>
                <td colSpan={4} className="py-6 text-center text-slate-400">暂无关联需求</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Risk Alerts */}
      {release.risks && release.risks.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-3">风险预警</h2>
          <div className="space-y-2">
            {release.risks.map((risk, i) => (
              <div key={i} className={`p-3 rounded-xl flex items-start gap-3 ${
                risk.level === 'critical' ? 'bg-red-50 border border-red-100' : 'bg-amber-50 border border-amber-100'
              }`}>
                <span className={`mt-0.5 w-1.5 h-1.5 rounded-full ${risk.level === 'critical' ? 'bg-red-500' : 'bg-amber-400'}`} />
                <div className="flex-1">
                  <p className="text-xs font-medium text-slate-800">{risk.reqId}: {risk.description}</p>
                  {risk.level === 'critical' && (
                    <p className="text-[10px] text-red-500 mt-0.5">可能影响发布窗口，建议升级处理</p>
                  )}
                  {risk.level === 'warning' && (
                    <p className="text-[10px] text-amber-500 mt-0.5">已自动升级给相关责任人</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
