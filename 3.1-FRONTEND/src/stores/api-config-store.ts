import { create } from 'zustand';
import type { UserProfileView } from '@/types';

interface ApiConfigState {
  profile: UserProfileView | null;
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;

  setProfile: (profile: UserProfileView) => void;
  setLoading: (loading: boolean) => void;
  setSaving: (saving: boolean) => void;
  setError: (error: string | null) => void;
  clearProfile: () => void;
}

export const useApiConfigStore = create<ApiConfigState>((set) => ({
  profile: null,
  isLoading: false,
  isSaving: false,
  error: null,

  setProfile: (profile) => set({ profile, isLoading: false, error: null }),
  setLoading: (loading) => set({ isLoading: loading }),
  setSaving: (saving) => set({ isSaving: saving }),
  setError: (error) => set({ error }),
  clearProfile: () => set({ profile: null, isLoading: false, error: null }),
}));
