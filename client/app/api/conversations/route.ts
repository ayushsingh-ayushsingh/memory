import { NextResponse } from "next/server";
import { and, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { conversation } from "@/db/schema";
import { getServerSession } from "@/lib/session";

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

// GET /api/conversations — list the current user's conversations.
export async function GET() {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const rows = await getDb()
    .select({
      id: conversation.id,
      title: conversation.title,
      updatedAt: conversation.updatedAt,
    })
    .from(conversation)
    .where(eq(conversation.userId, session.user.id))
    .orderBy(desc(conversation.updatedAt));

  return NextResponse.json({ conversations: rows });
}

// POST /api/conversations — create a conversation for the current user.
export async function POST(request: Request) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const body = (await request.json().catch(() => ({}))) as {
    title?: unknown;
  };
  const title =
    typeof body.title === "string" && body.title.trim().length > 0
      ? body.title.trim().slice(0, 120)
      : "New chat";

  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;

  const now = new Date();
  await getDb().insert(conversation).values({
    id,
    userId: session.user.id,
    title,
    createdAt: now,
    updatedAt: now,
  });

  return NextResponse.json({ id, title }, { status: 201 });
}

// DELETE /api/conversations?id=... — delete one owned conversation.
export async function DELETE(request: Request) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const id = new URL(request.url).searchParams.get("id");
  if (!id) {
    return NextResponse.json({ error: "Missing id" }, { status: 400 });
  }

  await getDb()
    .delete(conversation)
    .where(and(eq(conversation.id, id), eq(conversation.userId, session.user.id)));

  return NextResponse.json({ deleted: true });
}
