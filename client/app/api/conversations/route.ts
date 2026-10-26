import { NextResponse } from "next/server";
import { backendFetch, backendJson } from "@/lib/backend";
import { getServerSession } from "@/lib/session";

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

interface BackendConversation {
  id: string;
  title: string;
  updatedAt?: string;
}

// GET /api/conversations — list the current user's conversations (proxied to
// the Python backend, which owns Postgres storage).
export async function GET() {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const data = await backendJson<{ conversations: BackendConversation[] }>(
    "/conversations",
    {},
    { conversations: [] },
  );

  return NextResponse.json({ conversations: data.conversations });
}

// POST /api/conversations — create a conversation for the current user.
export async function POST(request: Request) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const body = (await request.json().catch(() => ({}))) as { title?: unknown };
  const title =
    typeof body.title === "string" && body.title.trim().length > 0
      ? body.title.trim().slice(0, 120)
      : "New chat";

  const response = await backendFetch("/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  if (!response || !response.ok) {
    return NextResponse.json({ error: "Failed to create" }, { status: 502 });
  }

  const data = (await response.json().catch(() => null)) as {
    conversation?: BackendConversation;
  } | null;
  const conversation = data?.conversation;
  if (!conversation) {
    return NextResponse.json({ error: "Malformed response" }, { status: 502 });
  }

  // The chat store expects the created conversation object directly.
  return NextResponse.json(
    { id: conversation.id, title: conversation.title, updatedAt: conversation.updatedAt },
    { status: 201 },
  );
}

// DELETE /api/conversations?id=... — delete one owned conversation.
export async function DELETE(request: Request) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const id = new URL(request.url).searchParams.get("id");
  if (!id) {
    return NextResponse.json({ error: "Missing id" }, { status: 400 });
  }

  const response = await backendFetch(`/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  return NextResponse.json({ deleted: response.ok });
}
