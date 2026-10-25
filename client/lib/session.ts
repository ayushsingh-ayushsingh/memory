import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { auth, type Session } from "@/lib/auth";

/** Session for the current request, or null. Node runtime only. */
export async function getServerSession(): Promise<Session | null> {
  const session = await auth.api.getSession({ headers: await headers() });
  return session;
}

/** Use in server components/layouts and API routes. Redirects to /auth. */
export async function requireSession(callbackURL = "/dashboard") {
  const session = await getServerSession();
  if (!session) {
    redirect(`/auth?callbackURL=${encodeURIComponent(callbackURL)}`);
  }
  return session;
}
