"use client";

import { useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ChatTranscript } from "@/components/custom/chat-transcript";
import { useChatStore } from "@/lib/chat-store";

/**
 * Dashboard landing page — a fresh chat with no id in the URL.
 *
 * The first message mints a conversation in the backend; once it finishes we
 * push /dashboard/chat/<id> so the URL (and the sidebar) pick up the new id.
 */
export default function DashboardLandingPage() {
  const router = useRouter();
  const fetchConversations = useChatStore((state) => state.fetchConversations);
  const refreshConversations = useChatStore((state) => state.refreshConversations);

  useEffect(() => {
    void fetchConversations();
  }, [fetchConversations]);

  const handleConversationCreated = useCallback(
    (id: string) => {
      void refreshConversations();
      router.push(`/dashboard/chat/${id}`);
    },
    [refreshConversations, router],
  );

  return (
    <ChatTranscript
      conversationId={null}
      initialMessages={[]}
      onConversationCreated={handleConversationCreated}
    />
  );
}
