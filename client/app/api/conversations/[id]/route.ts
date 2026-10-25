import { NextResponse } from "next/server";
import { and, asc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { conversation, message } from "@/db/schema";
import { getServerSession } from "@/lib/session";

type RouteContext = { params: Promise<{ id: string }> };

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

async function ownedConversation(userId: string, id: string) {
  const rows = await getDb()
    .select()
    .from(conversation)
    .where(and(eq(conversation.id, id), eq(conversation.userId, userId)))
    .limit(1);
  return rows[0] ?? null;
}

// GET /api/conversations/[id] — conversation with its messages.
export async function GET(_request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const convo = await ownedConversation(session.user.id, id);
  if (!convo) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const messages = await getDb()
    .select({
      id: message.id,
      role: message.role,
      content: message.content,
      createdAt: message.createdAt,
    })
    .from(message)
    .where(eq(message.conversationId, id))
    .orderBy(asc(message.createdAt));

  return NextResponse.json({
    id: convo.id,
    title: convo.title,
    messages,
  });
}

// PATCH /api/conversations/[id] — rename an owned conversation.
// The URL stays stable (/dashboard/chat/<id>); only the display name changes,
// so duplicate titles are fine.
export async function PATCH(request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const convo = await ownedConversation(session.user.id, id);
  if (!convo) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const body = (await request.json().catch(() => ({}))) as {
    title?: unknown;
  };
  if (typeof body.title !== "string" || body.title.trim().length === 0) {
    return NextResponse.json({ error: "Missing title" }, { status: 400 });
  }

  const title = body.title.trim().slice(0, 120);

  await getDb()
    .update(conversation)
    .set({ title, updatedAt: new Date() })
    .where(eq(conversation.id, id));

  return NextResponse.json({ updated: true, id, title });
}

// DELETE /api/conversations/[id] — delete one owned conversation.
export async function DELETE(_request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const convo = await ownedConversation(session.user.id, id);
  if (!convo) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  await getDb()
    .delete(conversation)
    .where(and(eq(conversation.id, id), eq(conversation.userId, session.user.id)));

  return NextResponse.json({ deleted: true });
}
