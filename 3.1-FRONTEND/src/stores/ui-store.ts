import { create } from 'zustand';

export interface Notification {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  duration?: number;
  createdAt: string;
}

interface UIState {
  // 布局
  sidebarCollapsed: boolean;
  rightPanelCollapsed: boolean;
  activeRightTab: 'analysis' | 'market' | 'reports' | 'settings';
  // 主题
  theme: 'dark' | 'light';
  // 语言
  locale: 'zh-CN' | 'en-US';
  // Command Palette
  commandPaletteOpen: boolean;
  // 通知
  notifications: Notification[];

  toggleSidebar: () => void;
  toggleRightPanel: () => void;
  setRightTab: (tab: UIState['activeRightTab']) => void;
  setTheme: (theme: 'dark' | 'light') => void;
  setLocale: (locale: UIState['locale']) => void;
  toggleCommandPalette: () => void;
  addNotification: (n: Notification) => void;
  removeNotification: (id: string) => void;
  clearNotifications: () => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false,
  rightPanelCollapsed: false,
  activeRightTab: 'analysis',
  theme: 'dark',
  locale: 'zh-CN',
  commandPaletteOpen: false,
  notifications: [],

  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  toggleRightPanel: () => set((s) => ({ rightPanelCollapsed: !s.rightPanelCollapsed })),
  setRightTab: (tab) => set({ activeRightTab: tab }),
  setTheme: (theme) => set({ theme }),
  setLocale: (locale) => set({ locale }),
  toggleCommandPalette: () => set((s) => ({ commandPaletteOpen: !s.commandPaletteOpen })),
  addNotification: (n) => set((s) => ({
    notifications: [n, ...s.notifications].slice(0, 50),
  })),
  removeNotification: (id) => set((s) => ({
    notifications: s.notifications.filter(n => n.id !== id),
  })),
  clearNotifications: () => set({ notifications: [] }),
}));
