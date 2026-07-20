import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/** 应用页面标识 */
export type PageView =
  | 'dashboard'
  | 'requirements'
  | 'agents'
  | 'approvals'
  | 'releases'
  | 'insights'
  | 'alerts'
  | 'llm-calls'
  | 'testing'
  | 'knowledge';

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

export const useAppStore = create<AppStore>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      currentView: 'dashboard',
      isDark: true, // 默认暗色主题
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setView: (view) => set({ currentView: view }),
      toggleDark: () => set((s) => ({ isDark: !s.isDark })),
      searchOpen: false,
      setSearchOpen: (open) => set({ searchOpen: open }),
      notificationPanelOpen: false,
      setNotificationPanelOpen: (open) => set({ notificationPanelOpen: open }),
    }),
    {
      name: 'ai-native-app-store',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        isDark: state.isDark,
      }),
    }
  )
);
