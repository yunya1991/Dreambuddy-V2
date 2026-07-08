import { create } from 'zustand';

interface AuthState {
  uid: string | null;
  email: string | null;
  role: 'admin' | 'user' | 'guest' | null;
  isVerified: boolean;
  isLoading: boolean;

  setAuth: (uid: string, email: string, role: 'admin' | 'user' | 'guest') => void;
  setVerified: (verified: boolean) => void;
  logout: () => void;
  setLoading: (loading: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  uid: null, email: null, role: null, isVerified: false, isLoading: false,

  setAuth: (uid, email, role) => set({ uid, email, role, isVerified: true }),
  setVerified: (verified) => set({ isVerified: verified }),
  logout: () => set({ uid: null, email: null, role: null, isVerified: false }),
  setLoading: (loading) => set({ isLoading: loading }),
}));
