import { create } from "zustand";

interface AuthState {
  isAuthenticated: boolean;
  uid: string | null;
  email: string | null;
  role: string | null;
  emailVerified: boolean;

  setAuth: (data: {
    uid: string;
    email: string;
    role: string;
    emailVerified: boolean;
  }) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  uid: null,
  email: null,
  role: null,
  emailVerified: false,

  setAuth: (data) =>
    set({
      isAuthenticated: true,
      uid: data.uid,
      email: data.email,
      role: data.role,
      emailVerified: data.emailVerified,
    }),

  clearAuth: () =>
    set({
      isAuthenticated: false,
      uid: null,
      email: null,
      role: null,
      emailVerified: false,
    }),
}));
