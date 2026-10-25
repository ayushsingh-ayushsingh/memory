import Link from "next/link";
import { and, asc, eq } from "drizzle-orm";
import { Text } from "@cloudflare/kumo";
import { ChatTranscript } from "@/components/custom/chat-transcript";
import { getDb } from "@/db";
import { conversation, message } from "@/db/schema";
import { requireSession } from "@/lib/session";

type PageProps = { params: Promise<{ id: string }> };

/**
 * A single chat at /dashboard/chat/<id>.
 *
 * The URL carries the stable conversation id (duplicate titles are fine);
 * the display name lives in the sidebar and header breadcrumbs. History is
 * loaded server-side (ownership-checked) so previously saved conversations
 * always render — including on refresh or bookmark. Unknown ids show a
 * friendly empty state instead of a 404 page.
 */
export default async function ChatByIdPage({ params }: PageProps) {
  const { id } = await params;
  const session = await requireSession(`/dashboard/chat/${id}`);

  const rows = await getDb()
    .select()
    .from(conversation)
    .where(and(eq(conversation.id, id), eq(conversation.userId, session.user.id)))
    .limit(1);
  const convo = rows[0] ?? null;

  if (!convo) {
    return (
      <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-5">
        <Text as="h2" variant="heading">
          Chat not found
        </Text>
        <Text variant="secondary">
          This chat doesn’t exist, was deleted, or belongs to another account.
        </Text>
        <Link href="/dashboard" className="text-sm text-kumo-link">
          Back to chats
        </Link>
      </main>
    );
  }

  const messages = await getDb()
    .select({
      id: message.id,
      role: message.role,
      content: message.content,
    })
    .from(message)
    .where(eq(message.conversationId, convo.id))
    .orderBy(asc(message.createdAt));

  return <ChatTranscript key={convo.id} conversationId={convo.id} initialMessages={messages} />;
}
