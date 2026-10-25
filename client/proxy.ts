import { NextRequest, NextResponse } from "next/server";
import { getSessionCookie } from "better-auth/cookies";

// Edge-safe: only reads the session cookie, no database access.
// Real enforcement happens server-side in layouts and API routes.
export function proxy(request: NextRequest) {
  const sessionCookie = getSessionCookie(request);
  const { pathname } = request.nextUrl;

  const isAuthPage = pathname === "/auth";
  const isProtected = pathname === "/dashboard" || pathname.startsWith("/dashboard/");

  if (isProtected && !sessionCookie) {
    const url = request.nextUrl.clone();
    url.pathname = "/auth";
    url.searchParams.set("callbackURL", pathname);
    return NextResponse.redirect(url);
  }

  if (isAuthPage && sessionCookie) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/auth"],
};
