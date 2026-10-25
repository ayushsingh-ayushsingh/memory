import { NextResponse } from "next/server";
import { and, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { conversation, notebook } from "@/db/schema";
import { getServerSession } from "@/lib/session";

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

// GET /api/notebooks — list the current user's visible notebooks (newest
// first) with their conversation titles, for the sidebar. Soft-deleted rows
// stay in the table (transcripts must keep hiding them) but are omitted here.
export async function GET() {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const rows = await getDb()
    .select({
      id: notebook.id,
      conversationId: notebook.conversationId,
      conversationTitle: conversation.title,
      codeHash: notebook.codeHash,
      ordinal: notebook.ordinal,
      title: notebook.title,
      autoTitle: notebook.autoTitle,
      updatedAt: notebook.updatedAt,
    })
    .from(notebook)
    .innerJoin(conversation, eq(notebook.conversationId, conversation.id))
    .where(and(eq(notebook.userId, session.user.id), eq(notebook.hidden, false)))
    .orderBy(desc(notebook.updatedAt));

  return NextResponse.json({ notebooks: rows });
}
