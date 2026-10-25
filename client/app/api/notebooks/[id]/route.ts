import { NextResponse } from "next/server";
import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { notebook } from "@/db/schema";
import { getServerSession } from "@/lib/session";

type RouteContext = { params: Promise<{ id: string }> };

function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

// PATCH /api/notebooks/[id] — rename an owned notebook. An empty title
// clears the custom name (the derived title shows again).
export async function PATCH(request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const body = (await request.json().catch(() => ({}))) as {
    title?: unknown;
  };
  if (typeof body.title !== "string") {
    return NextResponse.json({ error: "Body must be { title: string }" }, { status: 400 });
  }
  const trimmed = body.title.trim().slice(0, 120);
  const title = trimmed.length > 0 ? trimmed : null;

  const updated = await getDb()
    .update(notebook)
    .set({ title, updatedAt: new Date() })
    .where(and(eq(notebook.id, id), eq(notebook.userId, session.user.id)))
    .returning({ id: notebook.id, title: notebook.title });

  if (!updated[0]) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  return NextResponse.json({ id: updated[0].id, title: updated[0].title });
}

// DELETE /api/notebooks/[id] — soft-delete an owned notebook. The row is
// kept (hidden) so transcripts that contained it keep hiding it.
export async function DELETE(_request: Request, context: RouteContext) {
  const session = await getServerSession();
  if (!session) return unauthorized();

  const { id } = await context.params;
  const updated = await getDb()
    .update(notebook)
    .set({ hidden: true, updatedAt: new Date() })
    .where(and(eq(notebook.id, id), eq(notebook.userId, session.user.id)))
    .returning({ id: notebook.id });

  if (!updated[0]) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  return NextResponse.json({ deleted: true });
}
