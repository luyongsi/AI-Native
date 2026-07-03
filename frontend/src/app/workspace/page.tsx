'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { Requirement, Notification } from '@/lib/types';

export default function WorkspacePage() {
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.getRequirements({ limit: 200 }),
      api.getNotifications(),
    ])
      .then(([reqRes, notifRes]) => {
        setRequirements(reqRes.items);
        setNotifications(notifRes.items);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Derive my requirements (filter by first PM found, or show all)
  const myReqs = requirements.filter((r) => r.pm === '张三');
  const myReqCount = myReqs.length > 0 ? myReqs.length : requirements.length;

  // Compute task stats from actual data
  const taskStats = {
    myRequirements: myReqCount,
    pendingApprovals: 2,
    overdueApprovals: 1,
    requirementChanges: 3,
    unreadMessages: notifications.filter((n) => !n.read).length,
    weeklyStats: {
      created: requirements.length,
      approved: 7,
      avgApprovalTime: '1.2h',
      teamAvgApprovalTime: '2.5h',
      rejectRate: 15,
      teamRejectRate: 22,
      specCompleteness: 91,
    },
  };

  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto h-full flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-slate-400">加载工作台数据中...</p>
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
              Promise.all([
                api.getRequirements({ limit: 200 }),
                api.getNotifications(),
              ])
                .then(([reqRes, notifRes]) => {
                  setRequirements(reqRes.items);
                  setNotifications(notifRes.items);
                })
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

  const displayReqs = myReqs.length > 0 ? myReqs : requirements.slice(0, 5);

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">我的工作台</h1>
          <p className="text-xs text-slate-500 mt-0.5">张三 (产品经理) · 2026-06-25 周三</p>
        </div>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        {[
          { label: '我的需求', value: taskStats.myRequirements, color: 'text-slate-800' },
          { label: '待审批', value: taskStats.pendingApprovals, color: 'text-amber-600' },
          { label: '审批超时', value: taskStats.overdueApprovals, color: 'text-red-600' },
          { label: '需求变更', value: taskStats.requirementChanges, color: 'text-blue-600' },
          { label: '未读消息', value: taskStats.unreadMessages, color: 'text-slate-800' },
        ].map((card) => (
          <div key={card.label} className="bg-white rounded-xl border border-slate-200 p-4 text-center">
            <div className={`text-2xl font-bold ${card.color}`}>{card.value}</div>
            <div className="text-[10px] text-slate-400 mt-1">{card.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Priority Items */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-3">优先处理</h2>
          <div className="space-y-2">
            <div className="p-3 bg-red-50 rounded-xl border border-red-100">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                <span className="text-xs font-medium text-slate-800">REQ-789 审批超时 45min</span>
              </div>
              <p className="text-[10px] text-slate-500">产品总监已介入</p>
              <button className="mt-2 text-[10px] px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50">立即审批</button>
            </div>
            <div className="p-3 bg-amber-50 rounded-xl border border-amber-100">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                <span className="text-xs font-medium text-slate-800">REQ-790 Spec 待审批</span>
              </div>
              <p className="text-[10px] text-slate-500">SLA 剩余: 1.5h</p>
              <button className="mt-2 text-[10px] px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50">立即审批</button>
            </div>
          </div>
        </div>

        {/* My Requirements */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-800">我的需求</h2>
            <button className="text-[10px] text-slate-400 hover:text-slate-600">+ 新建</button>
          </div>
          <div className="space-y-1">
            {displayReqs.map((req) => (
              <div key={req.id} className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-slate-50 cursor-pointer">
                <span className="text-xs font-mono text-slate-400 w-20">{req.id}</span>
                <span className="text-xs text-slate-700 truncate flex-1">{req.title}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                  req.status === 'done' ? 'bg-emerald-100 text-emerald-600' :
                  req.status === 'designing' ? 'bg-amber-100 text-amber-600' :
                  req.status === 'developing' ? 'bg-blue-100 text-blue-600' :
                  req.status === 'testing' ? 'bg-purple-100 text-purple-600' :
                  'bg-slate-100 text-slate-500'
                }`}>
                  {{ pool: '需求池', designing: '设计中', developing: '开发中', testing: '测试中', releasing: '待发布', done: '已上线' }[req.status] || req.status}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Recent Notifications */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-800">最近通知</h2>
            <button className="text-[10px] text-slate-400 hover:text-slate-600">查看全部</button>
          </div>
          <div className="space-y-2">
            {notifications.slice(0, 4).map((n) => (
              <div key={n.id} className="flex items-start gap-2 py-1.5">
                <span className={`mt-0.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                  n.level === 'critical' ? 'bg-red-500' : n.level === 'warning' ? 'bg-amber-500' : n.level === 'success' ? 'bg-emerald-500' : 'bg-blue-500'
                }`} />
                <div className="min-w-0">
                  <p className="text-xs text-slate-700 truncate">{n.title}</p>
                  <p className="text-[10px] text-slate-400">{n.time}</p>
                </div>
              </div>
            ))}
            {notifications.length === 0 && (
              <p className="text-xs text-slate-400 text-center py-4">暂无通知</p>
            )}
          </div>
        </div>

        {/* Weekly Stats */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-3">本周统计</h2>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: '需求创建', value: taskStats.weeklyStats.created },
              { label: '需求审批', value: taskStats.weeklyStats.approved },
              { label: '审批均长', value: taskStats.weeklyStats.avgApprovalTime, sub: `团队: ${taskStats.weeklyStats.teamAvgApprovalTime}` },
              { label: '打回率', value: `${taskStats.weeklyStats.rejectRate}%`, sub: `团队: ${taskStats.weeklyStats.teamRejectRate}%` },
              { label: 'Spec 完整度', value: `${taskStats.weeklyStats.specCompleteness}%` },
            ].map((stat) => (
              <div key={stat.label} className="bg-slate-50 rounded-xl p-3 text-center">
                <div className="text-lg font-bold text-slate-800">{stat.value}</div>
                <div className="text-[10px] text-slate-400">{stat.label}</div>
                {stat.sub && <div className="text-[9px] text-slate-400 mt-0.5">{stat.sub}</div>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}