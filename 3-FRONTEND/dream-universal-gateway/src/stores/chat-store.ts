import { create } from "zustand";
import type { ChatMessage } from "@/types";

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  currentStreamContent: string;

  addMessage: (message: ChatMessage) => void;
  appendStreamContent: (chunk: string) => void;
  startStreaming: () => void;
  stopStreaming: () => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isStreaming: false,
  currentStreamContent: "",

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  appendStreamContent: (chunk) =>
    set((state) => ({
      currentStreamContent: state.currentStreamContent + chunk,
    })),

  startStreaming: () => set({ isStreaming: true, currentStreamContent: "" }),

  stopStreaming: () =>
    set((state) => {
      if (state.currentStreamContent) {
        const assistantMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: state.currentStreamContent,
          timestamp: Date.now(),
        };
        return {
          isStreaming: false,
          currentStreamContent: "",
          messages: [...state.messages, assistantMsg],
        };
      }
      return { isStreaming: false, currentStreamContent: "" };
    }),

  clearMessages: () => set({ messages: [], currentStreamContent: "" }),
}));
