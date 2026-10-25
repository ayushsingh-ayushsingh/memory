import { NextResponse } from "next/server";
import { and, asc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { conversation, notebook } from "@/db/schema";
import { getServerSession } from "@/lib/session";

type RouteContext = { params: Promise<{ id: string }> };

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

async function ownedConversation(conversationId: string, userId: string): Promise<boolean> {
  const rows = await getDb()
    .select({ id: conversation.id })
    .from(conversation)
    .where(and(eq(conversation.id, conversationId), eq(conversation.userId, userId)))
    .limit(1);
  return Boolean(rows[0]);
}

function toRecord(row: typeof notebook.$inferSelect) {
  return {
    id: row.id,
    conversationId: row.conversationId,
    codeHash: row.codeHash,
    ordinal: row.ordinal,
    title: row.title,
    autoTitle: row.autoTitle,
    hidden: row.hidden,
  };
}

// GET /api/conversations/[id]/notebooks — records for one owned conversation
// (including hidden ones, so the transcript can omit them).
export async function GET(_request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  if (!(await ownedConversation(id, session.user.id))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const rows = await getDb()
    .select()
    .from(notebook)
    .where(and(eq(notebook.conversationId, id), eq(notebook.userId, session.user.id)))
    .orderBy(asc(notebook.ordinal));

  return NextResponse.json({ notebooks: rows.map(toRecord) });
}

// POST /api/conversations/[id]/notebooks — sync the notebooks derived from
// the conversation's messages. Inserts missing rows (user renames are never
// overwritten; autoTitle refreshes while no custom title exists) and returns
// all records so the transcript can apply names/hidden flags.
export async function POST(request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  if (!(await ownedConversation(id, session.user.id))) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const body = (await request.json().catch(() => ({}))) as {
    notebooks?: unknown;
  };
  if (!Array.isArray(body.notebooks) || body.notebooks.length > 100) {
    return NextResponse.json(
      { error: "Body must be { notebooks: Array (max 100) }" },
      { status: 400 },
    );
  }

  const items: { codeHash: string; ordinal: number; autoTitle: string }[] = [];
  for (const entry of body.notebooks) {
    if (
      typeof entry !== "object" ||
      entry === null ||
      typeof (entry as { codeHash?: unknown }).codeHash !== "string" ||
      typeof (entry as { ordinal?: unknown }).ordinal !== "number" ||
      typeof (entry as { autoTitle?: unknown }).autoTitle !== "string"
    ) {
      return NextResponse.json(
        {
          error: "Each notebook must be { codeHash: string, ordinal: number, autoTitle: string }",
        },
        { status: 400 },
      );
    }
    const item = entry as {
      codeHash: string;
      ordinal: number;
      autoTitle: string;
    };
    if (
      item.codeHash.length === 0 ||
      item.codeHash.length > 32 ||
      !Number.isInteger(item.ordinal) ||
      item.ordinal < 0
    ) {
      return NextResponse.json({ error: "Invalid codeHash or ordinal" }, { status: 400 });
    }
    items.push({
      codeHash: item.codeHash,
      ordinal: item.ordinal,
      autoTitle: item.autoTitle.trim().slice(0, 120) || "Notebook",
    });
  }

  for (const item of items) {
    const existing = await getDb()
      .select()
      .from(notebook)
      .where(
        and(
          eq(notebook.conversationId, id),
          eq(notebook.userId, session.user.id),
          eq(notebook.codeHash, item.codeHash),
          eq(notebook.ordinal, item.ordinal),
        ),
      )
      .limit(1);
    if (existing[0]) {
      // Refresh the derived title only while the user hasn't renamed it.
      if (existing[0].title === null && existing[0].autoTitle !== item.autoTitle) {
        await getDb()
          .update(notebook)
          .set({ autoTitle: item.autoTitle, updatedAt: new Date() })
          .where(eq(notebook.id, existing[0].id));
      }
      continue;
    }
    const notebookId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;
    const now = new Date();
    await getDb().insert(notebook).values({
      id: notebookId,
      userId: session.user.id,
      conversationId: id,
      codeHash: item.codeHash,
      ordinal: item.ordinal,
      title: null,
      autoTitle: item.autoTitle,
      hidden: false,
      createdAt: now,
      updatedAt: now,
    });
  }

  const rows = await getDb()
    .select()
    .from(notebook)
    .where(and(eq(notebook.conversationId, id), eq(notebook.userId, session.user.id)))
    .orderBy(asc(notebook.ordinal));

  return NextResponse.json({ notebooks: rows.map(toRecord) });
}
