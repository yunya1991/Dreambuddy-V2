import { create } from "zustand";
import type { UserProfileView } from "@/types";

interface ConfigState {
  profile: UserProfileView | null;
  isLoading: boolean;

  setProfile: (profile: UserProfileView) => void;
  setLoading: (loading: boolean) => void;
  clearProfile: () => void;
}

export const useConfigStore = create<ConfigState>((set) => ({
  profile: null,
  isLoading: false,

  setProfile: (profile) => set({ profile, isLoading: false }),
  setLoading: (loading) => set({ isLoading: loading }),
  clearProfile: () => set({ profile: null, isLoading: false }),
}));
