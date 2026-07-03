'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import type { Requirement, Notification } from '@/lib/types';

// ── Helpers ──────────────────────────────────────────────────────────

function getTodayString(): string {
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const wd = weekdays[d.getDay()];
  return `${y}-${m}-${day} ${wd}`;
}

function getWeekStart(): Date {
  const d = new Date();
  const day = d.getDay();
  // Monday of current week
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  const monday = new Date(d.getFullYear(), d.getMonth(), diff);
  monday.setHours(0, 0, 0, 0);
  return monday;
}

// ── Component ────────────────────────────────────────────────────────

export default function WorkspacePage() {
  // ── Current user (hardcoded; swap with auth context when available) ─
  const currentUser = { name: '张三', role: '产品经理' };

  // ── State ──────────────────────────────────────────────────────────
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Fetch on mount ─────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    async function fetchData() {
      try {
        setLoading(true);
        setError(null);
        const [reqsRes, notifsRes] = await Promise.all([
          api.getRequirements({ limit: 200 }),
          api.getNotifications(),
        ]);
        if (!cancelled) {
          setRequirements(reqsRes.items);
          setNotifications(notifsRes.items);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '加载数据失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchData();
    return () => { cancelled = true; };
  }, []);

  // ── Derived data ───────────────────────────────────────────────────
  const myReqs = requirements.filter((r) => r.pm === currentUser.name);
  const today = getTodayString();
  const weekStart = getWeekStart();

  // Overview card stats
  const myRequirementsCount = myReqs.length;
  const pendingApprovals = myReqs.filter((r) => r.blocked).length;
  const overdueApprovals = myReqs.filter(
    (r) => r.blocked && r.slaDeadline && new Date(r.slaDeadline) < new Date()
  ).length;
  const requirementChanges = 0; // dedicated changes API not called on this page
  const unreadMessages = notifications.filter((n) => !n.read).length;

  // Weekly stats
  const reqsCreatedThisWeek = requirements.filter((r) => {
    if (!r.createdAt) return false;
    return new Date(r.createdAt) >= weekStart;
  }).length;

  const weeklyStats = {
    created: reqsCreatedThisWeek,
    approved: 0,
    avgApprovalTime: '--',
    teamAvgApprovalTime: '--',
    rejectRate: 0,
    teamRejectRate: 0,
    specCompleteness:
      myReqs.length > 0
        ? Math.round(
            myReqs.reduce((sum, r) => sum + (r.aiCompletion || 0), 0) /
              myReqs.length
          )
        : 0,
  };

  const statusLabels: Record<string, string> = {
    pool: '需求池',
    designing: '设计中',
    developing: '开发中',
    testing: '测试中',
    releasing: '待发布',
    done: '已上线',
  };

  // ── Loading state ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center h-64">
        <p className="text-sm text-slate-400">加载中...</p>
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="p-6 max-w-[1600px] mx-auto flex items-center justify-center h-64">
        <div className="text-center">
          <p className="text-sm text-red-500 mb-2">加载失败</p>
          <p className="text-xs text-slate-400">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-3 text-xs px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">我的工作台</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {currentUser.name} ({currentUser.role}) · {today}
          </p>
        </div>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        {[
          { label: '我的需求', value: myRequirementsCount, color: 'text-slate-800' },
          { label: '待审批', value: pendingApprovals, color: 'text-amber-600' },
          { label: '审批超时', value: overdueApprovals, color: 'text-red-600' },
          { label: '需求变更', value: requirementChanges, color: 'text-blue-600' },
          { label: '未读消息', value: unreadMessages, color: 'text-slate-800' },
        ].map((card) => (
          <div
            key={card.label}
            className="bg-white rounded-xl border border-slate-200 p-4 text-center"
          >
            <div className={`text-2xl font-bold ${card.color}`}>
              {card.value}
            </div>
            <div className="text-[10px] text-slate-400 mt-1">{card.label}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Priority Items */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-3">
            优先处理
          </h2>
          <div className="space-y-2">
            <div className="p-3 bg-red-50 rounded-xl border border-red-100">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                <span className="text-xs font-medium text-slate-800">
                  REQ-789 审批超时 45min
                </span>
              </div>
              <p className="text-[10px] text-slate-500">产品总监已介入</p>
              <button className="mt-2 text-[10px] px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50">
                立即审批
              </button>
            </div>
            <div className="p-3 bg-amber-50 rounded-xl border border-amber-100">
              <div className="flex items-center gap-2 mb-1">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                <span className="text-xs font-medium text-slate-800">
                  REQ-790 Spec 待审批
                </span>
              </div>
              <p className="text-[10px] text-slate-500">SLA 剩余: 1.5h</p>
              <button className="mt-2 text-[10px] px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50">
                立即审批
              </button>
            </div>
          </div>
        </div>

        {/* My Requirements */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-800">我的需求</h2>
            <button className="text-[10px] text-slate-400 hover:text-slate-600">
              + 新建
            </button>
          </div>
          {myReqs.length === 0 ? (
            <p className="text-xs text-slate-400 py-4 text-center">
              暂无需求
            </p>
          ) : (
            <div className="space-y-1">
              {myReqs.map((req) => (
                <div
                  key={req.id}
                  className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-slate-50 cursor-pointer"
                >
                  <span className="text-xs font-mono text-slate-400 w-20">
                    {req.id}
                  </span>
                  <span className="text-xs text-slate-700 truncate flex-1">
                    {req.title}
                  </span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                      req.status === 'done'
                        ? 'bg-emerald-100 text-emerald-600'
                        : req.status === 'designing'
                          ? 'bg-amber-100 text-amber-600'
                          : req.status === 'developing'
                            ? 'bg-blue-100 text-blue-600'
                            : req.status === 'testing'
                              ? 'bg-purple-100 text-purple-600'
                              : 'bg-slate-100 text-slate-500'
                    }`}
                  >
                    {statusLabels[req.status] || req.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent Notifications */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-800">
              最近通知
            </h2>
            <button className="text-[10px] text-slate-400 hover:text-slate-600">
              查看全部
            </button>
          </div>
          {notifications.length === 0 ? (
            <p className="text-xs text-slate-400 py-4 text-center">
              暂无通知
            </p>
          ) : (
            <div className="space-y-2">
              {notifications.slice(0, 4).map((n) => (
                <div key={n.id} className="flex items-start gap-2 py-1.5">
                  <span
                    className={`mt-0.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      n.level === 'critical'
                        ? 'bg-red-500'
                        : n.level === 'warning'
                          ? 'bg-amber-500'
                          : n.level === 'success'
                            ? 'bg-emerald-500'
                            : 'bg-blue-500'
                    }`}
                  />
                  <div className="min-w-0">
                    <p className="text-xs text-slate-700 truncate">{n.title}</p>
                    <p className="text-[10px] text-slate-400">{n.time}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Weekly Stats */}
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="text-sm font-semibold text-slate-800 mb-3">
            本周统计
          </h2>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: '需求创建', value: weeklyStats.created },
              { label: '需求审批', value: weeklyStats.approved },
              {
                label: '审批均长',
                value: weeklyStats.avgApprovalTime,
                sub: `团队: ${weeklyStats.teamAvgApprovalTime}`,
              },
              {
                label: '打回率',
                value: `${weeklyStats.rejectRate}%`,
                sub: `团队: ${weeklyStats.teamRejectRate}%`,
              },
              {
                label: 'Spec 完整度',
                value: `${weeklyStats.specCompleteness}%`,
              },
            ].map((stat) => (
              <div
                key={stat.label}
                className="bg-slate-50 rounded-xl p-3 text-center"
              >
                <div className="text-lg font-bold text-slate-800">
                  {stat.value}
                </div>
                <div className="text-[10px] text-slate-400">
                  {stat.label}
                </div>
                {stat.sub && (
                  <div className="text-[9px] text-slate-400 mt-0.5">
                    {stat.sub}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
