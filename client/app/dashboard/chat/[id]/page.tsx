import Link from "next/link";
import { Text } from "@cloudflare/kumo";
import { ChatTranscript } from "@/components/custom/chat-transcript";
import { backendJson } from "@/lib/backend";
import { requireSession } from "@/lib/session";

type PageProps = { params: Promise<{ id: string }> };

interface BackendMessage {
  id: string;
  role: string;
  content: string;
}

interface ConversationDetail {
  conversation: { id: string; title: string };
  messages: BackendMessage[];
}

/**
 * A single chat at /dashboard/chat/<id>.
 *
 * Conversations and messages live in the backend's Postgres store; history is
 * loaded server-side (ownership-scoped to the signed-in user) so a chat always
 * renders on refresh or bookmark. Unknown ids show a friendly empty state.
 */
export default async function ChatByIdPage({ params }: PageProps) {
  const { id } = await params;
  // Redirects to /auth when there is no session.
  await requireSession(`/dashboard/chat/${id}`);

  const detail = await backendJson<ConversationDetail | null>(
    `/conversations/${encodeURIComponent(id)}`,
    {},
    null,
  );

  if (!detail) {
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

  return (
    <ChatTranscript
      key={detail.conversation.id}
      conversationId={detail.conversation.id}
      initialMessages={detail.messages}
    />
  );
}
