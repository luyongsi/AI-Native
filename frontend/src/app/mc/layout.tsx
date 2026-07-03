'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useAppStore } from '@/stores/appStore';

const mcNavItems = [
  { href: '/mc', id: 'dashboard', label: '首页 Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
  { href: '/mc/requirements', id: 'requirements', label: '需求流总览', icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01' },
  { href: '/mc/agents', id: 'agents', label: 'Agent 中心', icon: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
  { href: '/mc/approvals', id: 'approvals', label: '审批中心', icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' },
  { href: '/mc/releases', id: 'releases', label: '版本发布', icon: 'M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4' },
  { href: '/mc/insights', id: 'insights', label: '效能仪表盘', icon: 'M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z' },
  { href: '/mc/alerts', id: 'alerts', label: '告警中心', icon: 'M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9' },
];

export default function MCLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { sidebarCollapsed, setView } = useAppStore();

  return (
    <div className="flex">
      <aside className={`fixed left-0 top-12 bottom-8 bg-white border-r border-slate-200 z-30 transition-all duration-200 ${
        sidebarCollapsed ? 'w-14' : 'w-52'
      }`}>
        <div className="px-3 py-3 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-slate-900 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            {!sidebarCollapsed && <span className="text-xs font-semibold text-slate-800 whitespace-nowrap">Mission Control</span>}
          </div>
          {!sidebarCollapsed && <p className="text-[9px] text-slate-400 mt-0.5">管理者视角</p>}
        </div>

        <nav className="flex flex-col py-2">
          {mcNavItems.map((item) => {
            const isActive = item.href === '/mc'
              ? pathname === '/mc'
              : pathname.startsWith(item.href);
            return (
              <button
                key={item.id}
                onClick={() => { setView(item.id); router.push(item.href); }}
                className={`flex items-center gap-2.5 px-3 py-2 mx-1.5 rounded-lg text-xs font-medium transition-colors ${
                  isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d={item.icon} />
                </svg>
                {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
              </button>
            );
          })}
        </nav>

        <div className="absolute bottom-0 left-0 right-0 p-1.5 border-t border-slate-200">
          <button
            onClick={() => useAppStore.getState().toggleSidebar()}
            className="flex items-center justify-center w-full p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d={sidebarCollapsed ? 'M13 5l7 7-7 7M5 5l7 7-7 7' : 'M11 19l-7-7 7-7m8 14l-7-7 7-7'} />
            </svg>
          </button>
        </div>
      </aside>

      <main className={`flex-1 min-h-[calc(100vh-5rem)] transition-all duration-200 ${
        sidebarCollapsed ? 'ml-14' : 'ml-52'
      }`}>
        {children}
      </main>
    </div>
  );
}
