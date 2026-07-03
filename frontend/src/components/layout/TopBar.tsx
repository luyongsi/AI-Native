
  'use client';

  import { usePathname, useRouter } from 'next/navigation';
import { useAppStore } from '@/stores/appStore';
  import { useNotificationStore } from '@/stores/notificationStore';

  export default function TopBar() {
    const pathname = usePathname();
  const router = useRouter();
  const { searchOpen, setSearchOpen, notificationPanelOpen, setNotificationPanelOpen, isDark, toggleDark, currentView } = useAppStore();
  const isMC = pathname.startsWith('/mc');
    const { unreadCount } = useNotificationStore();

    const viewTitles: Record<string, string> = {
      dashboard: '首页 Dashboard',
      requirements: '需求流',
      agents: 'Agent 中心',
      approvals: '审批中心',
      releases: '版本发布',
      insights: '效能仪表盘',
      alerts: '告警中心',
      workspace: '我的工作台',
      knowledge: '知识库',
    };

    return (
      <header className="fixed top-0 left-0 right-0 h-12 bg-white border-b border-slate-200 flex items-center justify-between px-4 z-40">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-slate-900" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <span className="font-semibold text-slate-900 text-sm">AI Native MC</span>
          </div>
          <a href="/mc" className="text-[10px] px-2 py-0.5 rounded-md font-medium ">MC</a>
        <a href="/workbench" className="text-[10px] px-2 py-0.5 rounded-md font-medium text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors">Workbench</a>
        <span className="text-xs text-slate-300">/</span>
          <span className="text-xs text-slate-500">{viewTitles[currentView] || ''}</span>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => setSearchOpen(!searchOpen)}
            className="flex items-center gap-2 px-3 py-1.5 text-xs text-slate-400 bg-slate-50 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors w-56"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span>搜索需求、Agent、Bug...</span>
            <kbd className="ml-auto text-[10px] px-1.5 py-0.5 bg-slate-200 rounded">Ctrl+K</kbd>
          </button>

          {searchOpen && <SearchPanel onClose={() => setSearchOpen(false)} />}

          <button
            onClick={() => setNotificationPanelOpen(!notificationPanelOpen)}
            className="relative p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214
  1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
            {unreadCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[10px] font-medium rounded-full flex items-center justify-center">
                {unreadCount}
              </span>
            )}
          </button>

          {notificationPanelOpen && <NotificationPanel onClose={() => setNotificationPanelOpen(false)} />}

          <button
            onClick={toggleDark}
            className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              {isDark ? (
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4
  4 0 018 0z" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              )}
            </svg>
          </button>

          <button className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-slate-100 transition-colors ml-1">
            <div className="w-6 h-6 bg-slate-800 text-white rounded-full flex items-center justify-center text-[10px] font-medium">
              张
            </div>
            <span className="text-xs text-slate-600">张三</span>
          </button>
        </div>
      </header>
    );
  }

  function SearchPanel({ onClose }: { onClose: () => void }) {
    return (
      <>
        <div className="fixed inset-0 z-50" onClick={onClose} />
        <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 w-[480px] bg-white rounded-xl shadow-2xl border border-slate-200 z-50 overflow-hidden">
          <div className="p-3 border-b border-slate-100">
            <input
              type="text"
              placeholder="搜索需求、Agent、Bug、文档..."
              className="w-full text-sm outline-none bg-transparent"
              autoFocus
            />
          </div>
          <div className="max-h-80 overflow-y-auto p-2">
            <div className="text-[10px] font-medium text-slate-400 uppercase tracking-wider px-2 py-1">需求</div>
            {[
              { id: 'REQ-789', title: '订单批量导出功能', status: '设计中' },
              { id: 'REQ-785', title: '地址管理优化', status: '开发中' },
              { id: 'REQ-777', title: '支付流程优化', status: '待发布' },
            ].map((req) => (
              <button key={req.id} className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-50 text-sm flex items-center gap-3">
                <span className="text-slate-400 font-mono text-xs">{req.id}</span>
                <span className="text-slate-700">{req.title}</span>
                <span className="ml-auto text-xs text-slate-400">{req.status}</span>
              </button>
            ))}
            <div className="text-[10px] font-medium text-slate-400 uppercase tracking-wider px-2 py-1 mt-2">Agent</div>
            {[
              { agent: 'DevAgent-3', task: '修改 OrderDetail.tsx', time: '17:05' },
              { agent: 'CIAgent-1', task: '构建失败 - 依赖冲突', time: '16:57' },
            ].map((a, i) => (
              <button key={i} className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-50 text-sm flex items-center gap-3">
                <span className="text-slate-500 text-xs">{a.agent}</span>
                <span className="text-slate-700 truncate">{a.task}</span>
                <span className="ml-auto text-xs text-slate-400">{a.time}</span>
              </button>
            ))}
          </div>
          <div className="border-t border-slate-100 px-3 py-2 flex gap-2 text-[10px] text-slate-400">
            <span className="px-1.5 py-0.5 bg-slate-50 rounded">@agent</span>
            <span className="px-1.5 py-0.5 bg-slate-50 rounded">#bug</span>
            <span className="px-1.5 py-0.5 bg-slate-50 rounded">/req</span>
            <span>快捷搜索</span>
          </div>
        </div>
      </>
    );
  }

  function NotificationPanel({ onClose }: { onClose: () => void }) {
    const { notifications, markRead, markAllRead } = useNotificationStore();

    return (
      <>
        <div className="fixed inset-0 z-50" onClick={onClose} />
        <div className="absolute top-full right-12 mt-2 w-96 bg-white rounded-xl shadow-2xl border border-slate-200 z-50 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <span className="text-sm font-semibold text-slate-900">通知中心</span>
            <div className="flex gap-2">
              <button onClick={markAllRead} className="text-xs text-slate-400 hover:text-slate-600">全部已读</button>
              <button className="text-xs text-slate-400 hover:text-slate-600">设置</button>
            </div>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {notifications.slice(0, 6).map((n) => (
              <button
                key={n.id}
                onClick={() => markRead(n.id)}
                className={`w-full text-left px-4 py-3 hover:bg-slate-50 border-b border-slate-50 transition-colors ${!n.read ? 'bg-blue-50/30' : ''}`}
              >
                <div className="flex items-start gap-2">
                  <span className={`mt-0.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                    n.level === 'critical' ? 'bg-red-500' : n.level === 'warning' ? 'bg-amber-500' : n.level === 'success' ? 'bg-emerald-500' : 'bg-blue-500'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-slate-800 truncate">{n.title}</p>
                    <p className="text-xs text-slate-500 mt-0.5 truncate">{n.description}</p>
                    <p className="text-[10px] text-slate-400 mt-1">{n.time}</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
          <button className="w-full px-4 py-2.5 text-xs text-slate-500 hover:bg-slate-50 border-t border-slate-100">
            查看全部通知
          </button>
        </div>
      </>
    );
  }