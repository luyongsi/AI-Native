import { create } from 'zustand';
import type { Notification } from '@/lib/types';

interface NotificationStore {
  notifications: Notification[];
  unreadCount: number;
  isLoading: boolean;
  /** 从 API 加载通知 */
  loadNotifications: (apiFn: () => Promise<Notification[]>) => Promise<void>;
  /** 标记单条已读 */
  markRead: (id: string) => void;
  /** 全部标记已读 */
  markAllRead: () => void;
}

export const useNotificationStore = create<NotificationStore>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  isLoading: false,

  loadNotifications: async (apiFn) => {
    set({ isLoading: true });
    try {
      const items = await apiFn();
      const unread = items.filter((n) => !n.read).length;
      set({ notifications: items, unreadCount: unread, isLoading: false });
    } catch (err) {
      console.error('Failed to load notifications:', err);
      set({ isLoading: false });
    }
  },

  markRead: (id) => {
    const notifications = get().notifications.map((n) =>
      n.id === id ? { ...n, read: true } : n
    );
    const unreadCount = notifications.filter((n) => !n.read).length;
    set({ notifications, unreadCount });
  },

  markAllRead: () => {
    const notifications = get().notifications.map((n) => ({ ...n, read: true }));
    set({ notifications, unreadCount: 0 });
  },
}));
