"use client";

import { create } from "zustand";

export interface NotebookRecord {
  id: string;
  conversationId: string;
  conversationTitle?: string;
  codeHash: string;
  ordinal: number;
  /** User rename (null = show autoTitle). */
  title: string | null;
  autoTitle: string;
  hidden: boolean;
}

export interface NotebookSyncItem {
  codeHash: string;
  ordinal: number;
  autoTitle: string;
}

export function displayTitle(record: Pick<NotebookRecord, "title" | "autoTitle">): string {
  return record.title ?? record.autoTitle;
}

interface NotebookStore {
  notebooks: NotebookRecord[];
  loaded: boolean;
  loading: boolean;
  error: string | null;
  /** Load all visible notebooks once (StrictMode-safe via flags). */
  fetchNotebooks: (force?: boolean) => Promise<void>;
  /** Rename a notebook. Returns false on failure. */
  renameNotebook: (id: string, title: string) => Promise<boolean>;
  /** Soft-delete a notebook. Returns false on failure. */
  deleteNotebook: (id: string) => Promise<boolean>;
  /**
   * Upsert a conversation's notebooks and refresh the sidebar list.
   * Returns the conversation's records (including hidden ones).
   */
  syncConversation: (
    conversationId: string,
    items: NotebookSyncItem[],
  ) => Promise<NotebookRecord[]>;
}

async function fetchJson(input: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as unknown;
}

export const useNotebookStore = create<NotebookStore>()((set, get) => ({
  notebooks: [],
  loaded: false,
  loading: false,
  error: null,

  fetchNotebooks: async (force = false) => {
    if ((!force && get().loaded) || get().loading) return;
    set({ loading: true, error: null });
    try {
      const data = (await fetchJson("/api/notebooks")) as {
        notebooks: NotebookRecord[];
      };
      set({ notebooks: data.notebooks, loaded: true });
    } catch {
      set({ notebooks: [], error: "Failed to load notebooks", loaded: true });
    } finally {
      set({ loading: false });
    }
  },

  renameNotebook: async (id, title) => {
    const trimmed = title.trim().slice(0, 120);
    const previous = get().notebooks;
    // Optimistic update; reconciled with the server below. An empty title
    // clears the custom name (falls back to the derived title).
    set((state) => ({
      notebooks: state.notebooks.map((item) =>
        item.id === id ? { ...item, title: trimmed.length > 0 ? trimmed : null } : item,
      ),
    }));
    try {
      const result = (await fetchJson(`/api/notebooks/${id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      })) as { title: string | null };
      set((state) => ({
        notebooks: state.notebooks.map((item) =>
          item.id === id ? { ...item, title: result.title } : item,
        ),
      }));
      return true;
    } catch {
      set({ notebooks: previous });
      return false;
    }
  },

  deleteNotebook: async (id) => {
    const previous = get().notebooks;
    set((state) => ({
      notebooks: state.notebooks.filter((item) => item.id !== id),
    }));
    try {
      await fetchJson(`/api/notebooks/${id}`, { method: "DELETE" });
      return true;
    } catch {
      set({ notebooks: previous });
      return false;
    }
  },

  syncConversation: async (conversationId, items) => {
    try {
      const data = (await fetchJson(`/api/conversations/${conversationId}/notebooks`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ notebooks: items }),
      })) as { notebooks: NotebookRecord[] };
      // Merge the conversation's records into the sidebar list (keep other
      // conversations' rows; drop rows hidden by this sync).
      const syncedIds = new Set(data.notebooks.map((item) => item.id));
      set((state) => ({
        notebooks: [
          ...data.notebooks.filter((item) => !item.hidden),
          ...state.notebooks.filter(
            (item) => item.conversationId !== conversationId && !syncedIds.has(item.id),
          ),
        ],
      }));
      return data.notebooks;
    } catch {
      return [];
    }
  },
}));
