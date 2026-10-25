"use client";

import { Button, Text } from "@cloudflare/kumo";
import { PlusIcon } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useChatStore } from "@/lib/chat-store";

/**
 * Dashboard landing page — shown when no chat is selected.
 * Chats live at /dashboard/chat/<id>; this page just offers a way in.
 */
export default function DashboardLandingPage() {
  const router = useRouter();
  const conversations = useChatStore((state) => state.conversations);
  const loaded = useChatStore((state) => state.loaded);
  const fetchConversations = useChatStore((state) => state.fetchConversations);
  const createConversation = useChatStore((state) => state.createConversation);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    void fetchConversations();
  }, [fetchConversations]);

  const handleNewChat = async () => {
    if (creating) return;
    setCreating(true);
    const created = await createConversation();
    setCreating(false);
    if (created) {
      router.push(`/dashboard/chat/${created.id}`);
    }
  };

  return (
    <main className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 px-5">
      <Text as="h2" variant="heading">
        {loaded && conversations.length > 0 ? "Pick up where you left off" : "Start a new chat"}
      </Text>
      <Text variant="secondary">
        {loaded && conversations.length > 0
          ? "Choose a conversation from the sidebar or start a fresh one."
          : "Ask anything — your conversations are saved in the sidebar."}
      </Text>
      <Button
        variant="primary"
        icon={PlusIcon}
        disabled={creating}
        onClick={() => void handleNewChat()}
      >
        New chat
      </Button>
    </main>
  );
}
