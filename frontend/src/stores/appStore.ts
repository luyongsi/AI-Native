import { create } from 'zustand';

type PageView = 'dashboard' | 'requirements' | 'agents' | 'approvals' | 'releases' | 'insights' | 'alerts' | 'llm-calls' | 'workspace' | 'knowledge' | string;

interface AppStore {
  sidebarCollapsed: boolean;
  currentView: PageView;
  isDark: boolean;
  toggleSidebar: () => void;
  setView: (view: PageView) => void;
  toggleDark: () => void;
  searchOpen: boolean;
  setSearchOpen: (open: boolean) => void;
  notificationPanelOpen: boolean;
  setNotificationPanelOpen: (open: boolean) => void;
}

export const useAppStore = create<AppStore>((set) => ({
  sidebarCollapsed: false,
  currentView: 'dashboard',
  isDark: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setView: (view) => set({ currentView: view }),
  toggleDark: () => set((s) => ({ isDark: !s.isDark })),
  searchOpen: false,
  setSearchOpen: (open) => set({ searchOpen: open }),
  notificationPanelOpen: false,
  setNotificationPanelOpen: (open) => set({ notificationPanelOpen: open }),
}));
