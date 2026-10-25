import { NextResponse } from "next/server";
import { getServerSession } from "@/lib/session";

const backendUrl = process.env.PYTHON_BACKEND_URL || "http://localhost:8000";

if (!backendUrl) {
  throw new Error("PYTHON_BACKEND_URL is not configured");
}

// Authenticated proxy to the Python backend. The browser session cookie is
// verified here; the Python backend independently verifies the forwarded
// `Authorization: Bearer <jwt>` token (see backend/src/auth.py).
export async function POST(request: Request): Promise<Response> {
  const session = await getServerSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const upstream = await fetch(`${backendUrl}/chat`, {
    method: "POST",
    headers: request.headers,
    body: request.body,
    signal: request.signal,
  });

  const headers = new Headers(upstream.headers);

  headers.set("cache-control", "no-cache, no-transform");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });
}
