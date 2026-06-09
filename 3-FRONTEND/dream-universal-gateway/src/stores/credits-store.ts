import { create } from "zustand";

interface CreditsState {
  balance: number;
  totalEarned: number;
  totalSpent: number;
  isLoading: boolean;

  setBalance: (balance: number, totalEarned: number, totalSpent: number) => void;
  deduct: (amount: number) => void;
  add: (amount: number) => void;
  setLoading: (loading: boolean) => void;
}

export const useCreditsStore = create<CreditsState>((set) => ({
  balance: 0,
  totalEarned: 0,
  totalSpent: 0,
  isLoading: false,

  setBalance: (balance, totalEarned, totalSpent) =>
    set({ balance, totalEarned, totalSpent, isLoading: false }),

  deduct: (amount) =>
    set((state) => ({
      balance: state.balance - amount,
      totalSpent: state.totalSpent + amount,
    })),

  add: (amount) =>
    set((state) => ({
      balance: state.balance + amount,
      totalEarned: state.totalEarned + amount,
    })),

  setLoading: (loading) => set({ isLoading: loading }),
}));
