'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { KnowledgeStatus } from '@/lib/types';

export default function KnowledgePage() {
  const [data, setData] = useState<KnowledgeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getKnowledge()
      .then((d) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-slate-400">加载知识库数据中...</p>
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
              api.getKnowledge()
                .then((d) => setData(d))
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

  if (!data) return null;

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      <h1 className="text-lg font-semibold text-slate-900 mb-6">知识库状态</h1>

      <div className="grid grid-cols-2 gap-4 mb-6">
        {/* Coverage */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-4">项目代码知识图谱覆盖</h2>
          <div className="space-y-3">
            {data.projects.map((proj) => (
              <div key={proj.name} className="flex items-center gap-3">
                <span className="text-xs text-slate-600 w-20 truncate">{proj.name}</span>
                <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${proj.coverage >= 90 ? 'bg-emerald-500' : proj.coverage >= 70 ? 'bg-amber-400' : 'bg-red-400'}`}
                    style={{ width: `${proj.coverage}%` }}
                  />
                </div>
                <span className={`text-xs font-medium ${proj.coverage >= 90 ? 'text-emerald-600' : proj.coverage >= 70 ? 'text-amber-600' : 'text-red-500'}`}>
                  {proj.coverage}%
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* API Stats */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-4">API 契约索引</h2>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: '已索引接口', value: data.apiStats.indexed, color: 'text-slate-800' },
              { label: '过期接口', value: data.apiStats.deprecated, color: 'text-amber-600' },
              { label: '未文档化接口', value: data.apiStats.undocumented, color: 'text-red-600' },
              { label: '契约冲突', value: data.apiStats.conflicts, color: 'text-amber-600' },
            ].map((stat) => (
              <div key={stat.label} className="bg-slate-50 rounded-xl p-3 text-center">
                <div className={`text-lg font-bold ${stat.color}`}>{stat.value}</div>
                <div className="text-[10px] text-slate-400">{stat.label}</div>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-slate-400 mt-3">最近更新: 2小时前</p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <h2 className="text-sm font-semibold text-slate-800 mb-3">知识库待办</h2>
        <div className="space-y-3">
          {[
            { level: 'critical', title: '支付系统代码图谱仅覆盖 67%', desc: '缺少退款模块的完整调用链。建议触发 Codebase Intelligence Agent 增量扫描。', btn: '触发增量扫描' },
            { level: 'warning', title: '12 个接口契约已过期', desc: '可能与实际代码不一致。建议触发 API Contract Agent 重新校验。', btn: '触发契约校验' },
            { level: 'warning', title: '3 个契约冲突待解决', desc: 'POST /api/order/create 请求体字段不一致', btn: '查看冲突详情' },
          ].map((todo, i) => (
            <div key={i} className={`flex items-start gap-3 p-3 rounded-xl ${todo.level === 'critical' ? 'bg-red-50' : 'bg-amber-50'}`}>
              <span className={`mt-0.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${todo.level === 'critical' ? 'bg-red-500' : 'bg-amber-400'}`} />
              <div className="flex-1 min-w-0">
                <h4 className="text-xs font-medium text-slate-800">{todo.title}</h4>
                <p className="text-[10px] text-slate-500 mt-0.5">{todo.desc}</p>
              </div>
              <button className="text-[10px] px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 flex-shrink-0">{todo.btn}</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}