import { create } from 'zustand';
import { api } from '@/lib/api';
import type { Notification } from '@/lib/types';

interface NotificationStore {
  notifications: Notification[];
  unreadCount: number;
  markRead: (id: string) => void;
  markAllRead: () => void;
  loadNotifications: () => Promise<void>;
  setNotifications: (notifications: Notification[]) => void;
  hydrate: (data: Notification[]) => void;
}

export const useNotificationStore = create<NotificationStore>((set) => ({
  notifications: [],
  unreadCount: 0,

  markRead: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, read: true } : n
      ),
      unreadCount: Math.max(0, state.unreadCount - 1),
    })),

  markAllRead: () =>
    set((state) => ({
      notifications: state.notifications.map((n) => ({ ...n, read: true })),
      unreadCount: 0,
    })),

  loadNotifications: async () => {
    try {
      const data = await api.getNotifications();
      const items: Notification[] = data.items || (data as unknown as Notification[]);
      set({
        notifications: items,
        unreadCount: items.filter((n) => !n.read).length,
      });
    } catch {
      // Silently fail — components can read the empty state to show a fallback
    }
  },

  setNotifications: (notifications) =>
    set({
      notifications,
      unreadCount: notifications.filter((n) => !n.read).length,
    }),

  hydrate: (data) =>
    set({
      notifications: data,
      unreadCount: data.filter((n) => !n.read).length,
    }),
}));
