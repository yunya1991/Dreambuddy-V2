import { create } from "zustand";

interface UIState {
  sidebarOpen: boolean;
  rightPanelOpen: boolean;
  activeRightTab: "progress" | "reports" | "market" | "settings";
  settingsTab: "api" | "trading" | "strategy" | "channels" | "credits";
  theme: "dark" | "light";

  toggleSidebar: () => void;
  toggleRightPanel: () => void;
  setActiveRightTab: (tab: UIState["activeRightTab"]) => void;
  setSettingsTab: (tab: UIState["settingsTab"]) => void;
  setTheme: (theme: UIState["theme"]) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  rightPanelOpen: true,
  activeRightTab: "progress",
  settingsTab: "api",
  theme: "dark",

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  toggleRightPanel: () => set((s) => ({ rightPanelOpen: !s.rightPanelOpen })),
  setActiveRightTab: (tab) => set({ activeRightTab: tab }),
  setSettingsTab: (tab) => set({ settingsTab: tab }),
  setTheme: (theme) => set({ theme }),
}));
