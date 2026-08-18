import { create } from 'zustand';

export interface ApiProfile {
  id: string;
  name: string;
  provider: string;
  baseUrl: string;
  apiKey: string;
  category: string;
  status: 'active' | 'inactive' | 'error';
  environment: 'dev' | 'staging' | 'prod';
}

interface ApiConfigState {
  profiles: ApiProfile[];
  isLoading: boolean;
  isSaving: boolean;

  loadProfiles: () => void;
  addProfile: (profile: Omit<ApiProfile, 'id'>) => void;
  updateProfile: (id: string, update: Partial<ApiProfile>) => void;
  deleteProfile: (id: string) => void;
  setLoading: (loading: boolean) => void;
  setSaving: (saving: boolean) => void;
}

export const useApiConfigStore = create<ApiConfigState>((set) => ({
  profiles: [], isLoading: false, isSaving: false,

  loadProfiles: () => set({ isLoading: true }),
  addProfile: (profile) => set(s => ({
    profiles: [...s.profiles, { ...profile, id: `api_${Date.now()}` }],
  })),
  updateProfile: (id, update) => set(s => ({
    profiles: s.profiles.map(p => p.id === id ? { ...p, ...update } : p),
  })),
  deleteProfile: (id) => set(s => ({
    profiles: s.profiles.filter(p => p.id !== id),
  })),
  setLoading: (loading) => set({ isLoading: loading }),
  setSaving: (saving) => set({ isSaving: saving }),
}));
