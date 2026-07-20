"use client";

import { usePathname } from "next/navigation";
import { useAppStore } from "@/stores/appStore";
import { useNotificationStore } from "@/stores/notificationStore";
import { cn } from "@/lib/utils";

const viewTitles: Record<string, string> = {
  dashboard: "Dashboard",
  requirements: "������",
  agents: "Agent ����",
  testing: "���Թ���̨",
  approvals: "��������",
  releases: "�汾����",
  knowledge: "֪ʶ��",
  insights: "Ч���Ǳ���",
  "llm-calls": "LLM ���ü��",
  alerts: "�澯����",
};

export default function TopBar() {
  const pathname = usePathname();
  const { searchOpen, setSearchOpen, notificationPanelOpen, setNotificationPanelOpen } =
    useAppStore();
  const { unreadCount } = useNotificationStore();

  const segments = pathname.split("/").filter(Boolean);
  const currentView = segments[1] || "dashboard";
  const viewTitle = viewTitles[currentView] || currentView;

  return (
    <header className="fixed top-0 left-0 right-0 h-12 bg-slate-950/80 backdrop-blur border-b border-slate-800 flex items-center justify-between px-4 z-40">
      {/* ��ࣺ���м */}
      <div className="flex items-center gap-3">
        <span className="text-xs text-slate-400">AI Native</span>
        <span className="text-xs text-slate-400">/</span>
        <span className="text-xs font-medium text-slate-600">{viewTitle}</span>
      </div>

      {/* �Ҳࣺ������ */}
      <div className="flex items-center gap-1">
        {/* ���� */}
        <button
          onClick={() => setSearchOpen(!searchOpen)}
          className="flex items-center gap-2 px-3 py-1.5 text-xs text-slate-400 bg-slate-800/50 hover:bg-slate-700/50 rounded-lg border border-slate-700 transition-colors w-56"
        >
          <svg
            className="w-3.5 h-3.5 flex-shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <span>��������Agent��Bug...</span>
          <kbd className="ml-auto text-[10px] px-1.5 py-0.5 bg-slate-700 rounded text-slate-400">
            Ctrl+K
          </kbd>
        </button>

        {/* ֪ͨ */}
        <button
          onClick={() => setNotificationPanelOpen(!notificationPanelOpen)}
          className="relative p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 transition-colors"
          aria-label="֪ͨ"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
            />
          </svg>
          {unreadCount > 0 && (
            <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-[10px] font-medium rounded-full flex items-center justify-center">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </button>

        {/* �û�ͷ�� */}
        <button className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-slate-800/50 transition-colors ml-1">
          <div className="w-6 h-6 rounded-full bg-brand-500 text-white flex items-center justify-center text-[10px] font-medium">
            ��
          </div>
        </button>
      </div>
    </header>
  );
}
