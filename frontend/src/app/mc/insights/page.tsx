'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { InsightsData } from '@/lib/types';

export default function InsightsPage() {
  const [data, setData] = useState<InsightsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const result = await api.getInsights();
        if (!cancelled) {
          setData(result);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || '获取效能数据失败');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  // --- Derived display values with field mapping ---
  const cycleTime = data?.cycle_time_days ?? 0;
  const cycleTimeTrend = data?.trends?.cycle_time_trend ?? 0;
  const throughput = data?.throughput ?? 0;
  const throughputTrend = data?.trends?.throughput_trend ?? 0;
  const aiContribution = data?.ai_contribution_pct ?? 0;
  const aiContributionTrend = data?.trends?.ai_contribution_trend ?? 0;
  const codeQuality = data?.code_quality_score ?? 0;
  const codeQualityTrend = data?.trends?.code_quality_trend ?? 0;
  const bugEscapeRate = data?.bug_escape_rate_pct ?? 0;
  const bugEscapeRateTrend = data?.trends?.bug_escape_rate_trend ?? 0;
  const cycleTimeHistory: { week: string; value: number }[] =
    data?.trends?.cycle_time_history ?? [];
  const bottleneckDistribution = data?.bottleneck_distribution ?? [];
  const aiVsHumanStages = data?.ai_vs_human ?? [];

  // --- Loading state ---
  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-slate-500">正在加载效能数据...</span>
        </div>
      </div>
    );
  }

  // --- Error state ---
  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
            <span className="text-red-500 text-lg font-bold">!</span>
          </div>
          <p className="text-sm text-slate-700 font-medium">加载失败</p>
          <p className="text-xs text-slate-400 max-w-xs">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-2 text-xs text-blue-600 hover:text-blue-700 border border-blue-200 rounded-lg px-3 py-1.5 hover:bg-blue-50 transition-colors"
          >
            重新加载
          </button>
        </div>
      </div>
    );
  }

  // --- Empty state (data is null but no error) ---
  if (!data) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center min-h-[400px]">
        <p className="text-sm text-slate-400">暂无效能数据</p>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-semibold text-slate-900">效能仪表盘</h1>
        <select className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-600">
          <option>最近 2 周</option>
          <option>最近 1 个月</option>
          <option>最近 3 个月</option>
        </select>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        {[
          { label: '周期时间', value: `${cycleTime}天`, trend: cycleTimeTrend, unit: '' },
          { label: '吞吐量', value: `${throughput}个/周`, trend: throughputTrend, unit: '' },
          { label: 'AI 贡献度', value: `${aiContribution}%`, trend: aiContributionTrend, unit: '' },
          { label: '代码质量', value: `${codeQuality}分`, trend: codeQualityTrend, unit: '' },
          { label: 'Bug 逃逸率', value: `${bugEscapeRate}%`, trend: bugEscapeRateTrend, unit: '' },
        ].map((kpi) => (
          <div key={kpi.label} className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="text-xs text-slate-400 mb-2">{kpi.label}</div>
            <div className="text-xl font-bold text-slate-800">{kpi.value}</div>
            <div className={`flex items-center gap-0.5 text-[10px] mt-1 ${kpi.trend < 0 ? 'text-emerald-600' : 'text-red-500'}`}>
              <span>{kpi.trend > 0 ? '▲' : '▼'}</span>
              <span>{Math.abs(kpi.trend)}%</span>
              <span className="text-slate-400 ml-1">比上月</span>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 mb-6">
        {/* Cycle Time Chart */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-4">周期时间趋势 (天)</h2>
          <CycleTimeChart data={cycleTimeHistory} />
        </div>

        {/* Bottleneck Distribution */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-4">瓶颈分布</h2>
          <div className="space-y-3">
            {bottleneckDistribution.map((item) => (
              <div key={item.name} className="flex items-center gap-3">
                <span className="text-[10px] text-slate-500 w-24 truncate">{item.name}</span>
                <div className="flex-1 h-4 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-amber-400 to-red-400 rounded-full flex items-center justify-end pr-2" style={{ width: `${item.percentage}%` }}>
                    <span className="text-[9px] text-white font-medium">{item.percentage}%</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* AI vs Human */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-4">AI vs 人工贡献</h2>
          <div className="space-y-3">
            {aiVsHumanStages.map((stage) => (
              <div key={stage.name}>
                <div className="flex items-center justify-between text-[10px] mb-1">
                  <span className="text-slate-500">{stage.name}</span>
                  <span className="text-slate-400">AI: {stage.ai}%</span>
                </div>
                <div className="h-3 bg-slate-100 rounded-full overflow-hidden flex">
                  <div className="h-full bg-blue-500 transition-all" style={{ width: `${stage.ai}%` }} />
                  <div className="h-full bg-slate-300 transition-all" style={{ width: `${stage.human}%` }} />
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-4 mt-3 text-[10px] text-slate-400">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-blue-500" />AI</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-slate-300" />人工</span>
          </div>
        </div>

        {/* Summary */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-4">关键洞察</h2>
          <div className="space-y-3 text-xs">
            <div className="p-3 bg-emerald-50 rounded-xl border border-emerald-100">
              <p className="text-emerald-700">周期时间持续下降，从 5.2 天降至 2.3 天，降幅 56%。AI Agent 在编码和部署环节贡献显著。</p>
            </div>
            <div className="p-3 bg-amber-50 rounded-xl border border-amber-100">
              <p className="text-amber-700">设计评审等待占整体耗时的 35%，是最主要的瓶颈。建议优化审批流程或设置更严格的 SLA。</p>
            </div>
            <div className="p-3 bg-blue-50 rounded-xl border border-blue-100">
              <p className="text-blue-700">AI 编码贡献度达到 75%，但代码审查环节 AI 仅占 30%，仍有提升空间。</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* Simple SVG line chart for cycle time */
function CycleTimeChart({ data }: { data: { week: string; value: number }[] }) {
  const maxVal = 6;
  const minVal = 0;
  const w = 600;
  const h = 180;
  const pad = { top: 20, right: 30, bottom: 30, left: 40 };
  const chartW = w - pad.left - pad.right;
  const chartH = h - pad.top - pad.bottom;

  const points = data.map((d, i) => ({
    x: pad.left + (i / (data.length - 1)) * chartW,
    y: pad.top + chartH - ((d.value - minVal) / (maxVal - minVal)) * chartH,
  }));

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  const areaPath = linePath + ` L ${points[points.length - 1].x} ${pad.top + chartH} L ${points[0].x} ${pad.top + chartH} Z`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full">
      {/* Grid */}
      {[0, 2, 4, 6].map((v) => (
        <g key={v}>
          <line x1={pad.left} y1={pad.top + chartH - (v / maxVal) * chartH} x2={pad.left + chartW} y2={pad.top + chartH - (v / maxVal) * chartH} stroke="#f1f5f9" strokeWidth="1" />
          <text x={pad.left - 8} y={pad.top + chartH - (v / maxVal) * chartH + 3} textAnchor="end" className="text-[8px] fill-slate-400">{v}</text>
        </g>
      ))}
      {/* Target line */}
      <line x1={pad.left} y1={pad.top + chartH - (3 / maxVal) * chartH} x2={pad.left + chartW} y2={pad.top + chartH - (3 / maxVal) * chartH} stroke="#f59e0b" strokeWidth="1" strokeDasharray="4,4" />
      <text x={pad.left + chartW + 2} y={pad.top + chartH - (3 / maxVal) * chartH + 3} className="text-[8px] fill-amber-500">目标线 3天</text>
      {/* Area */}
      <path d={areaPath} fill="url(#gradient)" opacity="0.3" />
      <defs>
        <linearGradient id="gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* Line */}
      <path d={linePath} fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {/* Dots */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="3" fill="white" stroke="#3b82f6" strokeWidth="2" />
      ))}
      {/* Labels */}
      {data.filter((_, i) => i % 3 === 0 || i === data.length - 1).map((d, i) => {
        const idx = data.indexOf(d);
        return (
          <text key={i} x={pad.left + (idx / (data.length - 1)) * chartW} y={pad.top + chartH + 18} textAnchor="middle" className="text-[9px] fill-slate-400">{d.week}</text>
        );
      })}
    </svg>
  );
}
