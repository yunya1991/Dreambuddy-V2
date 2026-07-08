import { create } from 'zustand';

export interface Notification {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  timestamp: number;
  read: boolean;
}

interface UIState {
  sidebarCollapsed: boolean;
  theme: 'dark' | 'light';
  locale: 'zh' | 'en';
  commandPaletteOpen: boolean;
  notifications: Notification[];
  activeTab: string;

  toggleSidebar: () => void;
  setTheme: (theme: 'dark' | 'light') => void;
  setLocale: (locale: 'zh' | 'en') => void;
  setCommandPaletteOpen: (open: boolean) => void;
  addNotification: (n: Omit<Notification, 'id' | 'timestamp' | 'read'>) => void;
  markNotificationRead: (id: string) => void;
  setActiveTab: (tab: string) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false, theme: 'dark', locale: 'zh',
  commandPaletteOpen: false, notifications: [], activeTab: 'dashboard',

  toggleSidebar: () => set(s => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setTheme: (theme) => set({ theme }),
  setLocale: (locale) => set({ locale }),
  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
  addNotification: (n) => set(s => ({
    notifications: [{ ...n, id: `notif_${Date.now()}`, timestamp: Date.now(), read: false }, ...s.notifications],
  })),
  markNotificationRead: (id) => set(s => ({
    notifications: s.notifications.map(n => n.id === id ? { ...n, read: true } : n),
  })),
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
