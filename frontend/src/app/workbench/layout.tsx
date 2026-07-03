'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useAppStore } from '@/stores/appStore';

const wbNavItems = [
  { href: '/workbench', id: 'workspace', label: '我的工作台', icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z' },
  { href: '/workbench/requirements', id: 'requirements', label: '需求流', icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01' },
  { href: '/workbench/knowledge', id: 'knowledge', label: '知识库', icon: 'M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253' },
  { href: '/workbench/tasks', id: 'tasks', label: '我的任务', icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01' },
  { href: '/workbench/testing', id: 'testing', label: '测试工作台', icon: 'M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z' },
];

export default function WorkbenchLayout({ children }: { children: React.ReactNode }) {
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
            <svg className="w-4 h-4 text-blue-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
            {!sidebarCollapsed && <span className="text-xs font-semibold text-slate-800 whitespace-nowrap">研发工作台</span>}
          </div>
          {!sidebarCollapsed && <p className="text-[9px] text-slate-400 mt-0.5">产品/开发视角</p>}
        </div>

        <nav className="flex flex-col py-2">
          {wbNavItems.map((item) => {
            const isActive = item.href === '/workbench'
              ? pathname === '/workbench'
              : pathname.startsWith(item.href);
            return (
              <button
                key={item.id}
                onClick={() => { setView(item.id); router.push(item.href); }}
                className={`flex items-center gap-2.5 px-3 py-2 mx-1.5 rounded-lg text-xs font-medium transition-colors ${
                  isActive ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-blue-50 hover:text-blue-700'
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
