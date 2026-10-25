import { useCallback, useEffect, useState } from "react";

/** All page state is persisted in localStorage under this namespace. */
export const STORAGE_PREFIX = "kumo.demo";

export const THEME_STORAGE_KEY = "kumo.theme";

export function storageKey(component: string, name: string): string {
  return `${STORAGE_PREFIX}.${component}.${name}`;
}

export function readStorage<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (raw == null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeStorage<T>(key: string, value: T): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage may be full or unavailable; state still works in memory.
  }
}

export function removeStorage(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Private mode may throw; ephemeral state still resets in memory.
  }
}

/** True only after the component has mounted on the client. */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    // Hydration-safe mount flag: syncing React state with the client-only
    // mounted state is an intentional external-system sync.
    // oxlint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
  }, []);
  return mounted;
}

/** Narrow an unknown persisted value; return false to fall back to initial. */
export type StorageValidator<T> = (value: unknown) => value is T;

/** Build a validator for a fixed set of string literals. */
export function isOneOf<T extends string>(allowed: readonly T[]) {
  return (value: unknown): value is T =>
    typeof value === "string" && (allowed as readonly string[]).includes(value);
}

export interface UseLocalStorageOptions<T> {
  validate?: StorageValidator<T>;
}

/**
 * State that is kept in sync with localStorage. Returns `[value, setValue, reset]`
 * where `reset` writes the initial value back and restores it in memory.
 *
 * Minimal hydration-safe fix: the first render (SSR + initial client render)
 * always uses `initialValue` so they match. Stored state is applied in a
 * post-mount effect, optionally gated by `validate` to discard corrupt shapes.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T,
  options?: UseLocalStorageOptions<T>,
) {
  const [value, setValue] = useState<T>(initialValue);
  const validate = options?.validate;

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw == null) return;
      const parsed = JSON.parse(raw) as unknown;
      if (validate && !validate(parsed)) return;
      // Post-mount hydration from localStorage (external system) — intentional
      // so SSR and the first client render match on `initialValue`.
      // oxlint-disable-next-line react-hooks/set-state-in-effect
      setValue(parsed as T);
    } catch {
      // Corrupt JSON or unavailable storage: keep initial value.
    }
    // Validate fn is expected to be stable (module-scope `isOneOf(...)`).
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? (next as (prev: T) => T)(prev) : next;
        writeStorage(key, resolved);
        return resolved;
      });
    },
    [key],
  );

  const reset = useCallback(() => {
    writeStorage(key, initialValue);
    setValue(initialValue);
  }, [key, initialValue]);

  return [value, set, reset] as const;
}

/** Observe `data-mode` on <html> so charts can match light/dark tokens. */
export function useIsDarkMode(): boolean {
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    const sync = () => setIsDark(root.dataset.mode === "dark");
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(root, { attributes: true, attributeFilter: ["data-mode"] });
    return () => observer.disconnect();
  }, []);
  return isDark;
}

/** Collision-resistant id for user-created rows/tags/history entries. */
export function newStorageId(prefix = "id"): string {
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
    }
  } catch {
    // Fall through to timestamp fallback.
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
}
