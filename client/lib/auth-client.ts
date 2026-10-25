"use client";

import { createAuthClient } from "better-auth/react";
import { jwtClient } from "better-auth/client/plugins";

export const authClient = createAuthClient({
  baseURL: process.env.NEXT_PUBLIC_BETTER_AUTH_URL ?? "http://localhost:3000",
  plugins: [jwtClient()],
});

export const { signIn, signUp, signOut, useSession, getSession } = authClient;

/**
 * Fetch a short-lived JWT for the current session. Send it to the Python
 * backend as `Authorization: Bearer <token>`.
 */
export async function getBackendToken(): Promise<string | null> {
  try {
    const { data, error } = await authClient.token();
    if (error || !data?.token) return null;
    return data.token;
  } catch {
    return null;
  }
}
