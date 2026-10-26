import { NextResponse } from "next/server";
import { and, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { notebook } from "@/db/schema";
import { backendJson } from "@/lib/backend";
import { getServerSession } from "@/lib/session";

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

interface BackendConversation {
  id: string;
  title: string;
}

// GET /api/notebooks — list the current user's visible notebooks (newest
// first) with their conversation titles, for the sidebar. Soft-deleted rows
// stay in the table (transcripts must keep hiding them) but are omitted here.
// Conversation ids/titles come from the backend (Postgres); notebook rows
// live in SQLite keyed by that id.
export async function GET() {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const rows = await getDb()
    .select({
      id: notebook.id,
      conversationId: notebook.conversationId,
      codeHash: notebook.codeHash,
      ordinal: notebook.ordinal,
      title: notebook.title,
      autoTitle: notebook.autoTitle,
      updatedAt: notebook.updatedAt,
    })
    .from(notebook)
    .where(and(eq(notebook.userId, session.user.id), eq(notebook.hidden, false)))
    .orderBy(desc(notebook.updatedAt));

  const data = await backendJson<{ conversations: BackendConversation[] }>(
    "/conversations",
    {},
    { conversations: [] },
  );
  const titleById = new Map(data.conversations.map((item) => [item.id, item.title]));

  return NextResponse.json({
    notebooks: rows.map((row) => ({
      ...row,
      conversationTitle: titleById.get(row.conversationId) ?? "Chat",
    })),
  });
}
