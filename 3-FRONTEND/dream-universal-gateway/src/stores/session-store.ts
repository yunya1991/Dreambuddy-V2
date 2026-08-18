import { create } from "zustand";
import type { ChatSession } from "@/types";

interface SessionState {
  sessions: ChatSession[];
  currentSessionId: string | null;

  setSessions: (sessions: ChatSession[]) => void;
  setCurrentSession: (id: string | null) => void;
  addSession: (session: ChatSession) => void;
  removeSession: (id: string) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  currentSessionId: null,

  setSessions: (sessions) => set({ sessions }),

  setCurrentSession: (id) => set({ currentSessionId: id }),

  addSession: (session) =>
    set((state) => ({
      sessions: [session, ...state.sessions],
      currentSessionId: session.id,
    })),

  removeSession: (id) =>
    set((state) => ({
      sessions: state.sessions.filter((s) => s.id !== id),
      currentSessionId:
        state.currentSessionId === id ? null : state.currentSessionId,
    })),
}));
