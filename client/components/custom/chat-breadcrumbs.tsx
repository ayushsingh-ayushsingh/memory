"use client";

import { Breadcrumbs } from "@cloudflare/kumo";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { selectConversationById, useChatStore } from "@/lib/chat-store";

/**
 * Header breadcrumbs driven by the URL.
 *
 * - `/dashboard` → Dashboard
 * - `/dashboard/chat/<id>` → Dashboard / <chat name>
 *
 * The URL carries the stable conversation id; the name is resolved from the
 * chat store (sidebar shows the same name). Unknown ids fall back to "Chat".
 */
export function ChatBreadcrumbs() {
  const pathname = usePathname();
  const conversations = useChatStore((state) => state.conversations);
  const loaded = useChatStore((state) => state.loaded);
  const fetchConversations = useChatStore((state) => state.fetchConversations);

  useEffect(() => {
    void fetchConversations();
  }, [fetchConversations]);

  const segments = (pathname ?? "/dashboard").split("/").filter(Boolean);
  // segments[0] is "dashboard" for every page in this layout.
  const chatId =
    segments[0] === "dashboard" && segments[1] === "chat"
      ? segments[2]
      : undefined;

  if (!chatId) {
    return (
      <Breadcrumbs size="sm">
        <Breadcrumbs.Current>Dashboard</Breadcrumbs.Current>
      </Breadcrumbs>
    );
  }

  const conversation = selectConversationById(conversations, chatId);
  const title = conversation?.title ?? "Chat";

  return (
    <Breadcrumbs size="sm">
      <Breadcrumbs.Link href="/dashboard">Dashboard</Breadcrumbs.Link>
      <Breadcrumbs.Separator />
      <Breadcrumbs.Current loading={!loaded && !conversation}>
        {title}
      </Breadcrumbs.Current>
    </Breadcrumbs>
  );
}
