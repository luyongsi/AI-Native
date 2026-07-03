'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { Release } from '@/lib/types';

export default function ReleasesPage() {
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getReleases()
      .then((res) => setReleases(res.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-slate-400">加载版本数据中...</p>
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
              api.getReleases()
                .then((res) => setReleases(res.items))
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

  // Use the first release, or show empty state
  const currentRelease = releases[0];

  if (!currentRelease) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto">
        <h1 className="text-lg font-semibold text-slate-900 mb-6">版本发布</h1>
        <p className="text-xs text-slate-400">暂无版本数据</p>
      </div>
    );
  }

  const progress = currentRelease.totalReqs > 0
    ? (currentRelease.completedReqs / currentRelease.totalReqs) * 100
    : currentRelease.progress || 0;

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">版本发布 — {currentRelease.version}</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            发布窗口: {currentRelease.releaseWindow} · 剩余: 15天
          </p>
        </div>
        <span className={`text-xs px-3 py-1.5 rounded-full font-medium ${
          currentRelease.status === 'developing' ? 'bg-amber-100 text-amber-700' :
          currentRelease.status === 'released' ? 'bg-emerald-100 text-emerald-600' :
          'bg-slate-100 text-slate-600'
        }`}>
          {{ planning: '规划中', developing: '开发中', testing: '测试中', releasing: '发布中', released: '已发布' }[currentRelease.status] || currentRelease.status}
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
        <h2 className="text-sm font-semibold text-slate-800 mb-3">关联需求 ({(currentRelease.requirements || []).length}/{currentRelease.totalReqs})</h2>
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
            {(currentRelease.requirements || []).map((req) => (
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
          </tbody>
        </table>
      </div>

      {/* Risk Alerts */}
      {currentRelease.risks && currentRelease.risks.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-3">风险预警</h2>
          <div className="space-y-2">
            {currentRelease.risks.map((risk, i) => (
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