"use client";

import { create } from "zustand";

export interface ChatConversation {
  id: string;
  title: string;
  updatedAt?: string;
}

interface ChatStore {
  conversations: ChatConversation[];
  loaded: boolean;
  loading: boolean;
  error: string | null;
  /** Load the user's conversations once (StrictMode-safe via flags). */
  fetchConversations: () => Promise<void>;
  /** Create a chat and prepend it. Returns null when unauthenticated. */
  createConversation: (title?: string) => Promise<ChatConversation | null>;
  /** Rename an owned chat. Returns false on failure. */
  renameConversation: (id: string, title: string) => Promise<boolean>;
  /** Delete an owned chat. Returns false on failure. */
  deleteConversation: (id: string) => Promise<boolean>;
}

async function fetchJson(input: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as unknown;
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  conversations: [],
  loaded: false,
  loading: false,
  error: null,

  fetchConversations: async () => {
    if (get().loaded || get().loading) return;
    set({ loading: true, error: null });
    try {
      const data = (await fetchJson("/api/conversations")) as {
        conversations: ChatConversation[];
      };
      set({ conversations: data.conversations, loaded: true });
    } catch {
      // Unauthenticated or offline: sidebar renders empty; AuthGuard
      // redirects first anyway.
      set({ conversations: [], error: "Failed to load chats", loaded: true });
    } finally {
      set({ loading: false });
    }
  },

  createConversation: async (title = "New chat") => {
    try {
      const created = (await fetchJson("/api/conversations", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title }),
      })) as ChatConversation;
      set((state) => ({
        conversations: [created, ...state.conversations],
      }));
      return created;
    } catch {
      return null;
    }
  },

  renameConversation: async (id, title) => {
    const trimmed = title.trim().slice(0, 120);
    if (!trimmed) return false;
    const previous = get().conversations;
    // Optimistic title update; reconciled with the server below.
    set((state) => ({
      conversations: state.conversations.map((item) =>
        item.id === id ? { ...item, title: trimmed } : item,
      ),
    }));
    try {
      const result = (await fetchJson(`/api/conversations/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      })) as { title: string };
      set((state) => ({
        conversations: state.conversations.map((item) =>
          item.id === id ? { ...item, title: result.title } : item,
        ),
      }));
      return true;
    } catch {
      // Restore on failure so the UI doesn't lie.
      set({ conversations: previous });
      return false;
    }
  },

  deleteConversation: async (id) => {
    const previous = get().conversations;
    set((state) => ({
      conversations: state.conversations.filter((item) => item.id !== id),
    }));
    try {
      await fetchJson(`/api/conversations/${id}`, { method: "DELETE" });
      return true;
    } catch {
      // Restore on failure so the UI doesn't lie.
      set({ conversations: previous });
      return false;
    }
  },
}));

/** Find a conversation by its id. */
export function selectConversationById(
  conversations: ChatConversation[],
  id: string | undefined,
): ChatConversation | undefined {
  if (!id) return undefined;
  return conversations.find((item) => item.id === id);
}
