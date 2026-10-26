"use client";

import {
  Button,
  Dialog,
  Input,
  Sidebar,
  useKumoToastManager,
} from "@cloudflare/kumo";
import {
  ChatIcon,
  CheckIcon,
  PencilSimpleIcon,
  PlusIcon,
  TrashIcon,
  XIcon,
} from "@phosphor-icons/react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useChatStore } from "@/lib/chat-store";

/** Extract the chat id from a dashboard pathname, if present. */
function idFromPathname(pathname: string | null): string | undefined {
  const segments = (pathname ?? "").split("/").filter(Boolean);
  return segments[0] === "dashboard" && segments[1] === "chat"
    ? segments[2]
    : undefined;
}

function ConversationRow({
  id,
  title,
  active,
}: {
  id: string;
  title: string;
  active: boolean;
}) {
  const router = useRouter();
  const toastManager = useKumoToastManager();
  const renameConversation = useChatStore((state) => state.renameConversation);
  const deleteConversation = useChatStore((state) => state.deleteConversation);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  // Note: the draft is (re)set from the latest title every time editing
  // starts (see the rename button below), so no sync effect is needed.

  const open = () => {
    if (editing) return;
    router.push(`/dashboard/chat/${id}`);
  };

  const saveRename = async () => {
    const trimmed = draft.trim();
    if (!trimmed) {
      setDraft(title);
      setEditing(false);
      return;
    }
    if (trimmed === title) {
      setEditing(false);
      return;
    }
    setBusy(true);
    const ok = await renameConversation(id, trimmed);
    setBusy(false);
    setEditing(false);
    if (!ok) {
      toastManager.add({
        title: "Rename failed",
        description: "Please try again.",
        variant: "error",
      });
    }
    // The URL carries the stable id, so no navigation is needed — the
    // sidebar and breadcrumbs pick up the new name from the store.
  };

  const confirmDelete = async (forgetMemory: boolean) => {
    setBusy(true);
    const ok = await deleteConversation(id, forgetMemory);
    setBusy(false);
    setConfirmingDelete(false);
    if (!ok) {
      toastManager.add({
        title: "Delete failed",
        description: "Please try again.",
        variant: "error",
      });
      return;
    }
    if (active) {
      router.push("/dashboard");
    }
  };

  if (editing) {
    return (
      <Sidebar.MenuSubItem>
        <div className="flex items-center gap-1 px-1 py-0.5">
          <Input
            value={draft}
            autoFocus
            disabled={busy}
            aria-label="Rename chat"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void saveRename();
              if (event.key === "Escape") {
                setDraft(title);
                setEditing(false);
              }
            }}
            onBlur={() => void saveRename()}
            className="h-8 min-w-0 flex-1 text-sm"
          />
          <Button
            variant="outline"
            size="sm"
            shape="square"
            icon={CheckIcon}
            aria-label="Save name"
            title="Save"
            disabled={busy}
            onClick={() => void saveRename()}
          />
          <Button
            size="sm"
            variant="outline"
            shape="square"
            icon={XIcon}
            aria-label="Cancel rename"
            title="Cancel"
            disabled={busy}
            onClick={() => {
              setDraft(title);
              setEditing(false);
            }}
          />
        </div>
      </Sidebar.MenuSubItem>
    );
  }

  return (
    <>
      <Sidebar.MenuSubItem className="hover:border-kumo-hairline border border-transparent rounded-lg hover:bg-kumo-fill-hover">
        <div className="group flex items-center gap-1 pr-1">
          <Sidebar.MenuSubButton
            active={active}
            onClick={open}
            title={title}
            className="min-w-0 flex-1"
          >
            <span className="block truncate">{title}</span>
          </Sidebar.MenuSubButton>
          <span className="hidden shrink-0 group-hover:inline-flex group-focus-within:inline-flex gap-1">
            <Button
              variant="outline"
              shape="square"
              size="sm"
              icon={PencilSimpleIcon}
              aria-label={`Rename ${title}`}
              title="Rename"
              onClick={() => {
                setDraft(title);
                setEditing(true);
              }}
            />
            <Button
              variant="secondary-destructive"
              size="sm"
              shape="square"
              icon={TrashIcon}
              aria-label={`Delete ${title}`}
              title="Delete"
              onClick={() => setConfirmingDelete(true)}
            />
          </span>
        </div>
      </Sidebar.MenuSubItem>

      <Dialog.Root open={confirmingDelete} onOpenChange={setConfirmingDelete}>
        <Dialog className="p-6">
          <Dialog.Title className="text-lg font-semibold">
            Delete this chat?
          </Dialog.Title>
          <Dialog.Description className="mt-1.5 text-sm text-kumo-subtle">
            Do you want to delete only this chat? Or do you also want to erase
            what the assistant learned from this chat?
          </Dialog.Description>
          <div className="mt-8 flex flex-col-reverse gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => setConfirmingDelete(false)}
            >
              Cancel
            </Button>
            <Button
              variant="secondary-destructive"
              disabled={busy}
              onClick={() => void confirmDelete(false)}
            >
              Delete chat
            </Button>
            <Button
              variant="destructive"
              loading={busy}
              disabled={busy}
              onClick={() => void confirmDelete(true)}
            >
              Erase Memory
            </Button>
          </div>
        </Dialog>
      </Dialog.Root>
    </>
  );
}

export function ChatSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const conversations = useChatStore((state) => state.conversations);
  const fetchConversations = useChatStore((state) => state.fetchConversations);
  const [query, setQuery] = useState("");

  useEffect(() => {
    void fetchConversations();
  }, [fetchConversations]);

  const activeId = idFromPathname(pathname);

  const needle = query.trim().toLowerCase();
  const visible =
    needle.length === 0
      ? conversations
      : conversations.filter((conversationItem) =>
          needle
            .split(/\s+/)
            .every((word) =>
              conversationItem.title.toLowerCase().includes(word),
            ),
        );

  // New chats start on /dashboard with no id in the URL; the backend mints
  // the conversation when the user asks the first question.
  const handleNewChat = () => {
    router.push("/dashboard");
  };

  return (
    <Sidebar.Group>
      <Sidebar.Menu>
        <Sidebar.MenuItem>
          <Sidebar.Collapsible defaultOpen>
            <Sidebar.CollapsibleTrigger
              render={
                <Sidebar.MenuButton icon={ChatIcon} tooltip="Joy Chat">
                  Joy Chat <Sidebar.MenuChevron />
                </Sidebar.MenuButton>
              }
            />
            <Sidebar.CollapsibleContent>
              <Sidebar.MenuSub>
                <Sidebar.MenuSubButton
                  active={!activeId}
                  onClick={() => void handleNewChat()}
                  className="border border-kumo-hairline border-dashed"
                >
                  <span className="flex items-center gap-1.5">
                    <PlusIcon aria-hidden />
                    New chat
                  </span>
                </Sidebar.MenuSubButton>
                <Sidebar.MenuSubItem>
                  <div className="flex items-center gap-1.5 px-1 py-0.5">
                    <Input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Search chats"
                      aria-label="Search chats"
                      className="h-8 min-w-0 flex-1 text-sm rounded-md"
                    />
                    {query && (
                      <Button
                        variant="outline"
                        size="sm"
                        shape="square"
                        icon={XIcon}
                        aria-label="Clear search"
                        title="Clear search"
                        onClick={() => setQuery("")}
                      />
                    )}
                  </div>
                </Sidebar.MenuSubItem>
                {visible.map((conversationItem) => (
                  <ConversationRow
                    key={conversationItem.id}
                    id={conversationItem.id}
                    title={conversationItem.title}
                    active={activeId === conversationItem.id}
                  />
                ))}
                {visible.length === 0 && needle.length > 0 && (
                  <Sidebar.MenuSubItem>
                    <span className="block px-2 py-1 text-sm text-kumo-subtle">
                      No chats match.
                    </span>
                  </Sidebar.MenuSubItem>
                )}
              </Sidebar.MenuSub>
            </Sidebar.CollapsibleContent>
          </Sidebar.Collapsible>
        </Sidebar.MenuItem>
      </Sidebar.Menu>
    </Sidebar.Group>
  );
}
