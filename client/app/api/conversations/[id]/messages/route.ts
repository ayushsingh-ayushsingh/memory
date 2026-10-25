import { NextResponse } from "next/server";
import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { conversation, message } from "@/db/schema";
import { getServerSession } from "@/lib/session";

type RouteContext = { params: Promise<{ id: string }> };

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

// POST /api/conversations/[id]/messages — append one message to an owned
// conversation. This is the endpoint the chat UI persists to.
export async function POST(request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const rows = await getDb()
    .select({ id: conversation.id })
    .from(conversation)
    .where(and(eq(conversation.id, id), eq(conversation.userId, session.user.id)))
    .limit(1);
  if (!rows[0]) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const body = (await request.json().catch(() => ({}))) as {
    role?: unknown;
    content?: unknown;
  };
  if (
    (body.role !== "user" && body.role !== "assistant") ||
    typeof body.content !== "string" ||
    body.content.length === 0
  ) {
    return NextResponse.json(
      { error: "Body must be { role: 'user' | 'assistant', content: string }" },
      { status: 400 },
    );
  }

  const messageId =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;

  await getDb()
    .insert(message)
    .values({
      id: messageId,
      conversationId: id,
      userId: session.user.id,
      role: body.role,
      content: body.content.slice(0, 200_000),
      createdAt: new Date(),
    });
  await getDb().update(conversation).set({ updatedAt: new Date() }).where(eq(conversation.id, id));

  return NextResponse.json({ id: messageId }, { status: 201 });
}
