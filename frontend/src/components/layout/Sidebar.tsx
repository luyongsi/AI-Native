"use client";

import { usePathname, useRouter } from "next/navigation";
import { useAppStore } from "@/stores/appStore";
import { cn } from "@/lib/utils";

interface NavItem {
  id: string;
  label: string;
  href: string;
  iconPath: string;
}

const navItems: NavItem[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    href: "/app",
    iconPath:
      "M3 3h7v7H3V3zm11 0h7v7h-7V3zm0 11h7v7h-7v-7zM3 14h7v7H3v-7z",
  },
  {
    id: "requirements",
    label: "需求管理",
    href: "/app/requirements",
    iconPath:
      "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zM6 20V4h7v5h5v11H6zm4-6h4v2h-4v-2zm0-4h4v2h-4v-2z",
  },
  {
    id: "agents",
    label: "Agent 中心",
    href: "/app/agents",
    iconPath:
      "M9 2a1 1 0 011 1v1h4V3a1 1 0 112 0v1h1a2 2 0 012 2v1H3V6a2 2 0 012-2h1V3a1 1 0 011-1zM3 9h16v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9zm5 3h2v2H8v-2zm6 0h2v2h-2v-2z",
  },
  {
    id: "testing",
    label: "测试工作台",
    href: "/app/testing",
    iconPath:
      "M19.43 12.98c.04-.32.07-.64.07-.98 0-.34-.03-.66-.07-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.3-.61-.22l-2.49 1c-.52-.4-1.08-.73-1.69-.98l-.38-2.65A.488.488 0 0014 2h-4c-.25 0-.46.18-.49.42l-.38 2.65c-.61.25-1.17.59-1.69.98l-2.49-1c-.23-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64l2.11 1.65c-.04.32-.07.64-.07.98 0 .34.03.66.07.98l-2.11 1.65c-.19.15-.24.42-.12.64l2 3.46c.12.22.39.3.61.22l2.49-1c.52.4 1.08.73 1.69.98l.38 2.65c.03.24.24.42.49.42h4c.25 0 .46-.18.49-.42l.38-2.65c.61-.25 1.17-.59 1.69-.98l2.49 1c.23.09.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.65zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z",
  },
  {
    id: "approvals",
    label: "审批中心",
    href: "/app/approvals",
    iconPath:
      "M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z",
  },
  {
    id: "releases",
    label: "版本发布",
    href: "/app/releases",
    iconPath:
      "M13.415 1.252a1.524 1.524 0 00-2.83 0L5.32 11.09a1.644 1.644 0 00-.201.574L4.051 18.5a1.187 1.187 0 001.453 1.453l6.74-1.039c.261-.04.497-.148.708-.313l5.97-5.26a1.524 1.524 0 000-2.262l-5.506-5.827zM12.05 3.752l4.175 4.416-4.958 4.367-4.175-4.418 4.958-4.365zm-5.958 7.555l3.834 4.058-4.453.686-.004-.018.623-4.726zm5.957 6.505l-.014.002-4.034.622 8.688-7.653-.932-.986-3.708 8.015zM2 20h20v2H2v-2z",
  },
  {
    id: "knowledge",
    label: "知识库",
    href: "/app/knowledge",
    iconPath:
      "M4 6a2 2 0 012-2h3v2H6v12h12v-3h2v3a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm6 2h8a2 2 0 012 2v8a2 2 0 01-2 2h-8a2 2 0 01-2-2v-8a2 2 0 012-2zm0 2v8h8v-8h-8z",
  },
  {
    id: "insights",
    label: "效能仪表盘",
    href: "/app/insights",
    iconPath:
      "M18 20V10m-4 10V4m-4 16v-6m-4 6v-8m16 4h2M2 14h2m0-4h16M2 20h20",
  },
  {
    id: "llm-calls",
    label: "LLM 监控",
    href: "/app/llm-calls",
    iconPath:
      "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  },
  {
    id: "alerts",
    label: "告警中心",
    href: "/app/alerts",
    iconPath:
      "M12 2l9.66 16.5a1 1 0 01-.87 1.5H3.21a1 1 0 01-.87-1.5L12 2zm0 5v5m0 3h.01",
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { setView, sidebarCollapsed, toggleSidebar } = useAppStore();

  const navigateTo = (item: NavItem) => {
    setView(item.id as never);
    router.push(item.href);
  };

  const isActive = (item: NavItem) => {
    if (item.href === "/app") return pathname === "/app";
    return pathname.startsWith(item.href);
  };

  return (
    <aside aria-label="主导航"
      className={cn(
        "fixed left-0 top-12 bottom-6 bg-slate-950 border-r border-slate-800 z-30",
        "flex flex-col transition-all duration-200",
        sidebarCollapsed ? "w-16" : "w-56"
      )}
    >
      {/* 品牌标识 */}
      <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-slate-800">
        <div className="w-7 h-7 rounded-lg bg-brand-500 flex items-center justify-center flex-shrink-0">
          <svg
            className="w-3.5 h-3.5 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M13 10V3L4 14h7v7l9-11h-7z"
            />
          </svg>
        </div>
        {!sidebarCollapsed && (
          <div className="overflow-hidden">
            <p className="text-sm font-semibold text-slate-100 leading-tight">
              AI Native
            </p>
            <p className="text-[10px] text-slate-400 leading-tight">
              Mission Control
            </p>
          </div>
        )}
      </div>

      {/* 导航菜单 */}
      <nav className="flex-1 flex flex-col py-2 overflow-y-auto">
        {navItems.map((item) => {
          const active = isActive(item);
          return (
            <div key={item.id} className="relative group mx-2">
              <button
                onClick={() => navigateTo(item)} aria-label={item.label}
                className={cn(
                  "flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium",
                  "transition-all duration-150",
                  active
                    ? "bg-brand-500/10 text-brand-400 border-l-2 border-brand-500 rounded-l-none"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border-l-2 border-transparent rounded-l-none"
                )}
              >
                <svg
                  className="w-5 h-5 flex-shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={active ? 2 : 1.5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d={item.iconPath} />
                </svg>
                {!sidebarCollapsed && (
                  <span className="truncate text-left">{item.label}</span>
                )}
              </button>

              {/* 收起时 tooltip */}
              {sidebarCollapsed && (
                <div
                  className={cn(
                    "absolute left-full ml-2 top-1/2 -translate-y-1/2 px-2 py-1",
                    "bg-slate-800 text-slate-200 text-xs rounded-md whitespace-nowrap",
                    "opacity-0 invisible group-hover:opacity-100 group-hover:visible",
                    "transition-opacity duration-150 pointer-events-none z-50"
                  )}
                >
                  {item.label}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      {/* 收起按钮 */}
      <div className="p-2 border-t border-slate-800">
        <button
          onClick={toggleSidebar} aria-label={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
          className="flex items-center justify-center w-full p-2 rounded-lg
            text-slate-400 hover:text-slate-600 hover:bg-slate-800/50 transition-colors"
        >
          <svg
            className="w-4 h-4 transition-transform duration-200"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d={
                sidebarCollapsed
                  ? "M13 5l7 7-7 7M5 5l7 7-7 7"
                  : "M11 19l-7-7 7-7m8 14l-7-7 7-7"
              }
            />
          </svg>
        </button>
      </div>
    </aside>
  );
}