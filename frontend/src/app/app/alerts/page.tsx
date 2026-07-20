'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { Alert } from '@/lib/types';

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'critical' | 'warning'>('all');
  const [expandedAlert, setExpandedAlert] = useState<string | null>(null);

  useEffect(() => {
    api
      .getAlerts()
      .then((res) => {
        setAlerts(res.items ?? []);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : '获取告警信息失败');
      })
      .finally(() => setLoading(false));
  }, []);

  const handleAcknowledge = (alertId: string) => {
    api
      .acknowledgeAlert(alertId)
      .then(() => {
        setAlerts((prev) =>
          prev.map((a) => (a.id === alertId ? { ...a, acknowledged: true } : a))
        );
      })
      .catch((err) => {
        // silently fail — could surface a toast in production
        console.error('确认告警失败:', err);
      });
  };

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center min-h-[300px]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-slate-700 border-t-slate-600 rounded-full animate-spin" />
          <span className="text-xs text-slate-400">加载告警信息中…</span>
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
          <span className="text-xs text-slate-400">{error}</span>
          <button
            onClick={() => {
              setLoading(true);
              setError(null);
              api
                .getAlerts()
                .then((res) => {
                  setAlerts(res.items ?? []);
                })
                .catch((err) => {
                  setError(err instanceof Error ? err.message : '获取告警信息失败');
                })
                .finally(() => setLoading(false));
            }}
            className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800 border border-slate-700 rounded-lg hover:bg-slate-800/50"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  const filtered = filter === 'all' ? alerts : alerts.filter((a) => a.level === filter);
  const activeAlerts = alerts.filter((a) => !a.acknowledged).length;

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">告警中心</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            活跃告警: {activeAlerts} · 今天已解决: 5 · 7天内: 23
          </p>
        </div>
        <button className="px-4 py-2 bg-slate-800 border border-slate-700 text-xs font-medium text-slate-400 rounded-lg hover:bg-slate-800/50">
          配置告警规则
        </button>
      </div>

      {/* Filter */}
      <div className="flex gap-1 mb-4">
        {(['all', 'critical', 'warning'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-[10px] px-3 py-1.5 rounded-lg transition-colors ${
              filter === f ? 'bg-slate-900 text-white' : 'text-slate-400 bg-slate-800 border border-slate-700 hover:bg-slate-800/50'
            }`}
          >
            {{ all: '全部', critical: '严重', warning: '警告' }[f]}
          </button>
        ))}
      </div>

      {/* Alert Cards */}
      <div className="space-y-4">
        {filtered.length === 0 ? (
          <div className="text-center py-12">
            <span className="text-xs text-slate-400">暂无告警</span>
          </div>
        ) : (
          filtered.map((alert) => {
            const isExpanded = expandedAlert === alert.id;
            const isCritical = alert.level === 'critical';

            return (
              <div
                key={alert.id}
                className={`bg-slate-800 rounded-xl border overflow-hidden transition-all ${
                  isCritical ? 'border-red-200' : 'border-amber-200'
                }`}
              >
                {/* Alert Header */}
                <button
                  onClick={() => setExpandedAlert(isExpanded ? null : alert.id)}
                  className={`w-full flex items-start gap-3 p-4 text-left hover:bg-slate-800/50 transition-colors ${
                    !alert.acknowledged && isCritical ? 'bg-red-50/30' : ''
                  }`}
                >
                  <span className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${
                    isCritical ? 'bg-red-500 animate-pulse' : 'bg-amber-400'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                        isCritical ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                      }`}>
                        {isCritical ? '严重' : '警告'}
                      </span>
                      <span className="text-[10px] text-slate-400">{alert.time}</span>
                      {alert.acknowledged && <span className="text-[10px] text-slate-400">已确认</span>}
                    </div>
                    <h3 className="text-sm font-semibold text-slate-100">{alert.title}</h3>
                    <p className="text-xs text-slate-400 mt-0.5">{alert.description}</p>
                    <p className="text-[10px] text-slate-400 mt-1">影响: {alert.affected}</p>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      className="p-1.5 hover:bg-slate-600 rounded-lg text-slate-400"
                      title="确认"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleAcknowledge(alert.id);
                      }}
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    </button>
                    <button className="p-1.5 hover:bg-slate-600 rounded-lg text-slate-400" title="静默">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15.536 8.464a5 5 0 010 7.072M17.95 6.05a8 8 0 010 11.9M6.5 8.788l3.606 3.606M10.106 12.394l-3.606 3.606" />
                      </svg>
                    </button>
                    <svg className={`w-3 h-3 text-slate-600 transition-transform ${isExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </button>

                {/* Expanded Detail */}
                {isExpanded && (
                  <div className="border-t border-slate-800 px-4 py-4 bg-slate-800/50/50">
                    <div className="grid grid-cols-2 gap-4 mb-4">
                      <div>
                        <div className="text-[10px] text-slate-400 mb-1">根因分析</div>
                        <div className="text-xs text-slate-600 font-mono bg-slate-800 border border-slate-800 rounded-lg p-2.5">
                          {alert.rootCause}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-slate-400 mb-1">AI 建议</div>
                        <div className="text-xs text-slate-600 bg-slate-800 border border-slate-800 rounded-lg p-2.5">
                          {alert.aiSuggestion || (alert as any).suggestion}
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button className="px-3 py-1.5 bg-slate-800 border border-slate-700 text-xs text-slate-400 rounded-lg hover:bg-slate-800/50">
                        查看详细日志
                      </button>
                      <button className="px-3 py-1.5 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-800">
                        AI 自动修复
                      </button>
                      <button className="px-3 py-1.5 bg-slate-800 border border-slate-700 text-xs text-slate-400 rounded-lg hover:bg-slate-800/50">
                        通知负责人
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Alert Rules Section */}
      <div className="mt-8">
        <h2 className="text-sm font-semibold text-slate-100 mb-4">告警规则配置</h2>
        <div className="grid grid-cols-2 gap-4">
          <RuleCategory title="Agent 相关" rules={[
            { name: 'Agent 任务失败', level: '严重', enabled: true },
            { name: 'Agent 连续 3 次工具调用失败', level: '严重', enabled: true },
            { name: 'Agent 同一状态持续超过 5 分钟', level: '警告', enabled: true },
            { name: 'Agent 单步操作耗时超过 3x 历史平均', level: '警告', enabled: false },
          ]} />
          <RuleCategory title="审批相关" rules={[
            { name: 'Gate 审批超时', level: '警告', enabled: true },
            { name: '审批 SLA 预警 (超时前 30min)', level: '提醒', enabled: true },
            { name: '同一 Gate 被打回 3 次以上', level: '警告', enabled: false },
          ]} />
          <RuleCategory title="版本相关" rules={[
            { name: '版本进度落后超过 15%', level: '警告', enabled: true },
            { name: '需求阻塞超过 24 小时', level: '警告', enabled: true },
            { name: 'P0 需求未在 4 小时内启动', level: '严重', enabled: false },
          ]} />
          <RuleCategory title="系统健康" rules={[
            { name: 'Event Bus 消息积压超过 1000 条', level: '严重', enabled: true },
            { name: 'Worker 节点离线', level: '严重', enabled: true },
            { name: 'API 响应时间超过 3s', level: '警告', enabled: false },
          ]} />
        </div>
      </div>
    </div>
  );
}

function RuleCategory({ title, rules }: { title: string; rules: { name: string; level: string; enabled: boolean }[] }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
      <h3 className="text-xs font-semibold text-slate-200 mb-3">{title}</h3>
      <div className="space-y-2">
        {rules.map((rule, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className={`w-3.5 h-3.5 rounded border-2 flex items-center justify-center flex-shrink-0 ${
              rule.enabled ? 'bg-slate-900 border-slate-900' : 'border-slate-300'
            }`}>
              {rule.enabled && (
                <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              )}
            </span>
            <span className="text-slate-600 flex-1">{rule.name}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${
              rule.level === '严重' ? 'bg-red-50 text-red-600' :
              rule.level === '警告' ? 'bg-amber-50 text-amber-600' :
              'bg-blue-50 text-blue-600'
            }`}>{rule.level}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
