import { NextResponse } from "next/server";
import { backendFetch, backendJson } from "@/lib/backend";
import { getServerSession } from "@/lib/session";

type RouteContext = { params: Promise<{ id: string }> };

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

interface BackendMessage {
  id: string;
  role: string;
  content: string;
  createdAt?: string;
}

interface BackendConversationDetail {
  conversation: { id: string; title: string; updatedAt?: string };
  messages: BackendMessage[];
}

// GET /api/conversations/[id] — conversation with its messages.
export async function GET(_request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const data = await backendJson<BackendConversationDetail | null>(
    `/conversations/${encodeURIComponent(id)}`,
    {},
    null,
  );
  if (!data) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return NextResponse.json({
    id: data.conversation.id,
    title: data.conversation.title,
    messages: data.messages,
  });
}

// PATCH /api/conversations/[id] — rename an owned conversation.
export async function PATCH(request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const body = (await request.json().catch(() => ({}))) as { title?: unknown };
  if (typeof body.title !== "string" || body.title.trim().length === 0) {
    return NextResponse.json({ error: "Missing title" }, { status: 400 });
  }
  const title = body.title.trim().slice(0, 120);

  const response = await backendFetch(`/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  if (!response || !response.ok) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  // The chat store reconciles its optimistic title with `title` in the response.
  return NextResponse.json({ updated: true, id, title });
}

// DELETE /api/conversations/[id]?forgetMemory=true — delete one owned
// conversation, optionally also forgetting what the agent learned from it.
export async function DELETE(request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const forgetMemory =
    new URL(request.url).searchParams.get("forgetMemory") === "true";

  const response = await backendFetch(
    `/conversations/${encodeURIComponent(id)}?forget_memory=${forgetMemory}`,
    { method: "DELETE" },
  );
  if (!response) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  return NextResponse.json({ deleted: response.ok });
}
