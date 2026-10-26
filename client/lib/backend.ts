import { headers } from "next/headers";
import { auth } from "@/lib/auth";

const backendUrl = process.env.PYTHON_BACKEND_URL || "http://localhost:8000";

/**
 * Mint a short-lived backend JWT for the current session, server-side.
 * The Python backend verifies it independently (see backend/src/auth.py).
 */
export async function getBackendJwt(): Promise<string | null> {
  try {
    const result = await auth.api.getToken({ headers: await headers() });
    return result?.token ?? null;
  } catch {
    return null;
  }
}

/**
 * Call the Python backend on behalf of the signed-in user. Forwards the
 * minted JWT as `Authorization: Bearer <jwt>`. Returns the raw upstream
 * Response so callers can choose JSON vs. streaming passthrough.
 */
export async function backendFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response | null> {
  const token = await getBackendJwt();
  if (!token) return null;

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  return fetch(`${backendUrl}${path}`, { ...init, headers });
}

/** Call the backend and parse JSON, returning `fallback` on any failure. */
export async function backendJson<T>(
  path: string,
  init: RequestInit = {},
  fallback: T,
): Promise<T> {
  const response = await backendFetch(path, init);
  if (!response || !response.ok) return fallback;
  try {
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}
