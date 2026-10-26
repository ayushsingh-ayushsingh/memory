"use client";

import { DefaultChatTransport, UIDataTypes, UIMessage, UITools } from "ai";
import { useChat } from "@ai-sdk/react";
import { ChatContainerContent, ChatContainerRoot } from "@/components/prompt-kit/chat-container";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
} from "@/components/prompt-kit/message";
import {
  PromptInput,
  PromptInputAction,
  PromptInputActions,
  PromptInputTextarea,
} from "@/components/prompt-kit/prompt-input";
import { ScrollButton } from "@/components/prompt-kit/scroll-button";
import { Button, LayerCard, Loader, Sidebar, useKumoToastManager } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import {
  ArrowUpIcon,
  CopyIcon,
  DotsThreeIcon,
  MicrophoneIcon,
  PencilSimpleIcon,
  PlusIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getBackendToken } from "@/lib/auth-client";
import { useNotebookStore, type NotebookRecord } from "@/lib/notebook-store";
import { CodeBlockProvider } from "@/components/prompt-kit/code-block";
import { MarimoArtifactPanel } from "@/components/custom/marimo-artifact";
import { GeneratedUI } from "@/components/openui/generated-ui";
import { extractMarimoArtifacts, stripMarimoFences, type MarimoArtifact } from "@/lib/marimo";

const backendUrl = process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL ?? "http://localhost:8000";

export type ChatMessage = UIMessage<UIDataTypes, UITools, UITools>;

export interface PersistedChatMessage {
  id: string;
  role: string;
  content: string;
}

export function toUIMessage(item: PersistedChatMessage): ChatMessage {
  return {
    id: item.id,
    role: item.role as ChatMessage["role"],
    parts: [{ type: "text", text: item.content }],
  } as ChatMessage;
}

/** fetch wrapper that attaches the Better Auth JWT for the Python backend. */
async function authenticatedFetch(
  url: string | URL | Request,
  init?: RequestInit,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  try {
    const token = await getBackendToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  } catch {
    // No token: the backend will answer 401 and the UI surfaces the error.
  }
  return fetch(url, { ...init, headers, credentials: "include" });
}

function getMessageText(message: ChatMessage) {
  return message.parts
    .filter((part): part is Extract<typeof part, { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("");
}

/**
 * Live viewport width for the resizable notebook sidebar.
 * Null on the server / first render — `window` doesn't exist during SSR,
 * so reading it in render would crash prerendering and mismatch hydration.
 * The effect fills in the live width and tracks resize/orientation changes.
 */
function useViewportWidth(): number | null {
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const update = () => setWidth(window.innerWidth);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return width;
}

/**
 * One rendered chat message.
 *
 * Memoized on the message object identity. The chat hook only replaces the
 * streaming (last) message object on each chunk — completed messages keep
 * their identity — so during streaming only the active bubble re-renders
 * instead of the whole transcript (markdown re-parse, Shiki re-highlight,
 * tooltip/button trees for every message on every token).
 */
const ChatMessageRow = memo(function ChatMessageRow({
  message,
  isLastMessage,
  isStreaming,
  onCopy,
  onEdit,
  onDelete,
  onContinueConversation,
}: {
  message: ChatMessage;
  isLastMessage: boolean;
  isStreaming?: boolean;
  onCopy: (content: string) => void;
  onEdit: (messageId: string) => void;
  onDelete: (messageId: string) => void;
  onContinueConversation: (content: string) => void;
}) {
  const isAssistant = message.role === "assistant";
  const content = getMessageText(message);
  // Marimo fences render in the notebook panel; the chat column shows a
  // short placeholder instead (raw text, fences included, is kept for
  // copy/persist so artifacts survive refresh).
  const display = useMemo(
    () => (isAssistant ? stripMarimoFences(content) : content),
    [isAssistant, content],
  );

  return (
    <Message
      className={cn(
        "mx-auto flex w-full max-w-3xl min-w-0 flex-col gap-2 px-2",
        isAssistant ? "items-start" : "items-end",
      )}
    >
      {isAssistant ? (
        <div className="group flex w-full min-w-0 flex-col gap-0">
          <GeneratedUI
            content={display}
            isStreaming={isStreaming}
            onContinueConversation={onContinueConversation}
          />

          <MessageActions
            className={cn(
              "-ml-2.5 flex gap-0 group-hover:opacity-100",
              isLastMessage ? "opacity-100" : "opacity-0",
            )}
          >
            <MessageAction tooltip="Copy">
              <Button
                variant="ghost"
                size="sm"
                shape="square"
                icon={CopyIcon}
                aria-label="Copy message"
                title="Copy"
                onClick={() => onCopy(content)}
              />
            </MessageAction>

            <MessageAction tooltip="Upvote">
              <Button
                variant="ghost"
                size="sm"
                shape="square"
                icon={ThumbsUpIcon}
                aria-label="Upvote"
                title="Upvote"
              />
            </MessageAction>

            <MessageAction tooltip="Downvote">
              <Button
                variant="ghost"
                size="sm"
                shape="square"
                icon={ThumbsDownIcon}
                aria-label="Downvote"
                title="Downvote"
              />
            </MessageAction>
          </MessageActions>
        </div>
      ) : (
        <div className="group flex w-full min-w-0 flex-col items-end gap-1">
          <LayerCard className="max-w-full min-w-0 px-5 py-4">
            <MessageContent className="max-w-full text-kumo-default">{display}</MessageContent>
          </LayerCard>

          <MessageActions className="flex gap-0 opacity-0 group-hover:opacity-100">
            <MessageAction tooltip="Edit">
              <Button
                variant="ghost"
                size="sm"
                shape="square"
                icon={PencilSimpleIcon}
                aria-label="Edit message"
                title="Edit"
                onClick={() => onEdit(message.id)}
              />
            </MessageAction>

            <MessageAction tooltip="Delete">
              <Button
                variant="ghost"
                size="sm"
                shape="square"
                icon={TrashIcon}
                aria-label="Delete message"
                title="Delete"
                onClick={() => onDelete(message.id)}
              />
            </MessageAction>

            <MessageAction tooltip="Copy">
              <Button
                variant="ghost"
                size="sm"
                shape="square"
                icon={CopyIcon}
                aria-label="Copy message"
                title="Copy"
                onClick={() => onCopy(content)}
              />
            </MessageAction>
          </MessageActions>
        </div>
      )}
    </Message>
  );
});

/**
 * A single conversation transcript.
 *
 * History is loaded server-side and passed in as `initialMessages`, so
 * previous chats render deterministically — no client fetch competing with
 * the chat hook. The conversation name lives in the header breadcrumbs,
 * not in a duplicate in-page header.
 */
export function ChatTranscript({
  conversationId: initialConversationId,
  initialMessages,
  onConversationCreated,
}: {
  conversationId?: string | null;
  initialMessages: PersistedChatMessage[];
  /** Called with the id the backend mints for a brand-new chat. */
  onConversationCreated?: (id: string) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const toastManager = useKumoToastManager();

  // The backend returns the minted conversation id in the `X-Conversation-Id`
  // response header on the first message of a new chat; capture it here so the
  // page can put it in the URL once the turn finishes.
  const createdConversationIdRef = useRef<string | null>(null);

  // The backend owns history + persistence: each request carries only the
  // conversation id and the newest user message — never the full transcript.
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `${backendUrl}/chat`,
        fetch: async (input, init) => {
          const response = await authenticatedFetch(input, init);
          const minted = response.headers.get("X-Conversation-Id");
          if (minted) {
            createdConversationIdRef.current = minted;
          }
          return response;
        },
        prepareSendMessagesRequest: ({ id, messages, trigger }) => {
          const lastUserMessage = [...messages]
            .reverse()
            .find((message) => message.role === "user");
          return {
            body: {
              id: initialConversationId ?? id ?? "new",
              trigger,
              messages: lastUserMessage ? [lastUserMessage] : [],
            },
          };
        },
      }),
    [initialConversationId],
  );

  // Surface the minted id on ANY outcome (finish, abort, error): the backend
  // creates the conversation before the model runs, so even a rate-limited
  // turn leaves a real chat the user should land on and retry in — instead of
  // stranding them on /dashboard while orphan rows pile up.
  const surfaceMintedId = useCallback(() => {
    const minted = createdConversationIdRef.current;
    if (!initialConversationId && minted) {
      onConversationCreated?.(minted);
    }
  }, [initialConversationId, onConversationCreated]);

  const { messages, sendMessage, status, stop, setMessages } = useChat({
    id: initialConversationId ?? "new",
    messages: initialMessages.map(toUIMessage),
    // Coalesce the SSE firehose: without this, every model chunk (hundreds
    // per second on fast backends) triggers a full transcript re-render —
    // markdown re-lex, block diff, Shiki highlight — which janks the UI and
    // starves scroll input. 50ms still looks instant to the eye.
    throttle: 50,
    transport,
    onFinish: () => {
      surfaceMintedId();
    },
    onError: (error) => {
      console.error("Chat request failed:", error);
      toastManager.add({
        title: "Request failed",
        description: error.message || "The backend rejected the request. Sign in again?",
        variant: "error",
      });
      surfaceMintedId();
    },
  });

  // Stable alias of the prop for the rest of the component (notebook sync
  // below). Null for a brand-new chat on /dashboard until the backend mints an
  // id and the page navigates to /dashboard/chat/<id>.
  const conversationId = initialConversationId;

  const chatContainerRef = useRef<HTMLDivElement>(null);

  const isLoading = status === "submitted" || status === "streaming";

  const handleSubmit = async () => {
    const text = prompt.trim();

    if (isLoading) {
      await stop();
      return;
    }

    if (!text) return;

    setPrompt("");

    // The backend persists both sides of the turn and titles the conversation
    // from the first message; the client only needs to send the new prompt.
    try {
      await sendMessage({
        text,
      });
    } catch (error) {
      console.error("Failed to send message:", error);
      toastManager.add({
        title: "Failed to send message",
        description: "Please try again.",
        variant: "error",
      });
    }
  };

  // Copy follows the Kumo ClipboardText UX (see kumo/clipboard-text/AGENTS.md):
  // "Copy" tooltip on hover, "Copied!" toast on click, with a
  // textarea+execCommand fallback for contexts where navigator.clipboard
  // is unavailable (non-secure contexts, older browsers).
  // Stable identity so memoized rows don't re-render on every token.
  const handleCopy = useCallback(
    async (content: string) => {
      try {
        if (
          typeof navigator !== "undefined" &&
          navigator.clipboard &&
          typeof navigator.clipboard.writeText === "function"
        ) {
          await navigator.clipboard.writeText(content);
        } else if (typeof document !== "undefined") {
          const textarea = document.createElement("textarea");
          textarea.value = content;
          textarea.setAttribute("readonly", "");
          textarea.style.position = "absolute";
          textarea.style.left = "-9999px";
          document.body.appendChild(textarea);
          const selection = document.getSelection();
          const previousRange =
            selection?.rangeCount && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
          textarea.select();
          try {
            document.execCommand("copy");
          } finally {
            document.body.removeChild(textarea);
            if (previousRange) {
              selection?.removeAllRanges();
              selection?.addRange(previousRange);
            }
          }
        }
        toastManager.add({
          title: "Copied!",
          variant: "success",
        });
      } catch (error) {
        console.error("Failed to copy message:", error);
      }
    },
    [toastManager],
  );

  const handleDelete = useCallback(
    (messageId: string) => {
      setMessages((currentMessages) =>
        currentMessages.filter((message) => message.id !== messageId),
      );
    },
    [setMessages],
  );

  // Mirror of the message list for the stable edit handler below.
  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const handleEdit = useCallback(
    (messageId: string) => {
      const message = messagesRef.current.find((item) => item.id === messageId);

      if (!message || message.role !== "user") {
        return;
      }

      const text = getMessageText(message);

      setPrompt(text);

      setMessages((currentMessages) => currentMessages.filter((item) => item.id !== messageId));
    },
    [setMessages],
  );

  // A generated interface can send a follow-up turn (`@ToAssistant(...)`); the
  // click becomes an ordinary user message. The backend persists it.
  const handleContinueConversation = useCallback(
    (message: string) => {
      const text = message.trim();
      if (!text) return;

      void sendMessage({ text }).catch((error: unknown) => {
        console.error("Failed to continue conversation:", error);
        toastManager.add({
          title: "Failed to send message",
          description: "Please try again.",
          variant: "error",
        });
      });
    },
    [sendMessage, toastManager],
  );

  // Every ```python marimo fence in assistant messages becomes an artifact.
  // Ordinals count across the whole conversation so fallback titles number
  // globally (Notebook 1, 2, …) instead of restarting in every message.
  const artifacts: MarimoArtifact[] = useMemo(() => {
    const collected: MarimoArtifact[] = [];
    for (const message of messages) {
      if (message.role !== "assistant") continue;
      // startOrdinal = notebooks already collected: fallback titles number
      // globally across the conversation.
      const found = extractMarimoArtifacts(message.id, getMessageText(message), collected.length);
      collected.push(...found);
    }
    return collected;
  }, [messages]);

  // Selection + panel controls live above the records sync: refreshRecords
  // calls setSelectedArtifactKey/openPanel for sidebar deep links.
  const [selectedArtifactKey, setSelectedArtifactKey] = useState<string | null>(null);

  // Small screens: Chat/Notebook tabs (visible only when artifacts exist).
  const [mobileTab, setMobileTab] = useState<"chat" | "notebook">("chat");
  const [tabPinned, setTabPinned] = useState(false);

  // Artifact sidebar open state (controlled Kumo sidebar). Closing also
  // returns small screens to the chat tab.
  const [artifactOpen, setArtifactOpen] = useState(true);
  const openPanel = useCallback(() => {
    setArtifactOpen(true);
    setMobileTab("notebook");
    setTabPinned(true);
  }, []);

  // Persisted notebook records (renames + soft-deletes). Synced from the
  // finished artifacts below; matched by stable (codeHash, ordinal) identity.
  const [records, setRecords] = useState<NotebookRecord[]>([]);
  const syncConversation = useNotebookStore((state) => state.syncConversation);
  const syncSignatureRef = useRef<string | null>(null);
  // Deep-link target from the notebooks sidebar (?notebook=<record id>).
  // Consumed here (not in an effect) to keep set-state-in-effect happy.
  const deepLinkConsumedRef = useRef(false);
  const refreshRecords = useCallback(
    async (complete: MarimoArtifact[]) => {
      // No id yet (brand-new chat on /dashboard): skip notebook sync — the
      // records re-sync when the page navigates to /dashboard/chat/<id>.
      if (!conversationId || complete.length === 0) {
        setRecords([]);
        return;
      }
      const synced = await syncConversation(
        conversationId,
        complete.map((item) => ({
          codeHash: item.codeHash,
          ordinal: item.ordinal,
          autoTitle: item.title,
        })),
      );
      setRecords(synced);
      if (deepLinkConsumedRef.current || typeof window === "undefined") return;
      deepLinkConsumedRef.current = true;
      const target = new URLSearchParams(window.location.search).get("notebook");
      if (!target) return;
      window.history.replaceState(null, "", window.location.pathname);
      const record = synced.find((item) => item.id === target);
      if (!record || record.hidden) return;
      const match = complete.find(
        (item) => item.codeHash === record.codeHash && item.ordinal === record.ordinal,
      );
      if (match) {
        setSelectedArtifactKey(match.key);
        openPanel();
      }
    },
    [conversationId, syncConversation, openPanel],
  );
  useEffect(() => {
    const complete = artifacts.filter((item) => item.complete);
    const signature = complete
      .map((item) => `${item.ordinal}:${item.codeHash}:${item.title}`)
      .join("|");
    // Only hit the server when the finished set actually changed — never on
    // every streaming token.
    if (signature === syncSignatureRef.current) return;
    syncSignatureRef.current = signature;
    void refreshRecords(complete);
  }, [artifacts, refreshRecords]);

  const recordByIdentity = useMemo(() => {
    const map = new Map<string, NotebookRecord>();
    for (const record of records) {
      map.set(`${record.codeHash}:${record.ordinal}`, record);
    }
    return map;
  }, [records]);

  // Renamed titles win; soft-deleted notebooks disappear from the transcript.
  const displayArtifacts: MarimoArtifact[] = useMemo(
    () =>
      artifacts.flatMap((item) => {
        const record = recordByIdentity.get(`${item.codeHash}:${item.ordinal}`);
        if (record?.hidden) return [];
        if (record?.title) return [{ ...item, title: record.title }];
        return [item];
      }),
    [artifacts, recordByIdentity],
  );
  const hasArtifacts = displayArtifacts.length > 0;

  // Active notebook: explicit user selection wins, otherwise the latest.
  const activeArtifactKey =
    (selectedArtifactKey &&
      displayArtifacts.some((item) => item.key === selectedArtifactKey) &&
      selectedArtifactKey) ||
    displayArtifacts[displayArtifacts.length - 1]?.key ||
    null;

  // Derived, not effected: the notebook tab shows as soon as the first
  // artifact streams in, unless the user explicitly picked a tab.
  const effectiveMobileTab =
    !artifactOpen || !hasArtifacts ? "chat" : tabPinned ? mobileTab : "notebook";
  const handleMobileTab = (value: "chat" | "notebook") => {
    if (value === "notebook") {
      openPanel();
      return;
    }
    setMobileTab(value);
    setTabPinned(true);
  };

  const viewportWidth = useViewportWidth();
  // Pixel widths for the resizable notebook sidebar. Before hydration
  // (viewportWidth === null) fall back to constants so SSR and the first
  // paint agree. minWidth stays small and fixed so the panel can always
  // shrink on phones/tablets; maxWidth never exceeds the viewport, so the
  // fixed-pixel aside (plus its border) can't push the page wider than
  // the screen and cause horizontal scrolling.
  const sidebarDefaultWidth =
    viewportWidth == null
      ? 640
      : viewportWidth > 1024
        ? Math.round(viewportWidth / 2)
        : viewportWidth;
  const sidebarMinWidth = 280;
  const sidebarMaxWidth = viewportWidth ?? 1024;

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {hasArtifacts && (
        <div
          role="tablist"
          aria-label="Chat or notebook"
          className="flex shrink-0 items-center gap-2 border-b border-kumo-hairline bg-kumo-base p-2 lg:hidden"
        >
          {(["chat", "notebook"] as const).map((value) => (
            <Button
              key={value}
              size="sm"
              role="tab"
              aria-selected={effectiveMobileTab === value}
              type="button"
              onClick={() => handleMobileTab(value)}
              className={cn(
                "flex-1 rounded-sm px-3 py-1.5 text-sm font-medium text-kumo-subtle",
                effectiveMobileTab === value &&
                  "bg-kumo-recessed text-kumo-strong ring ring-kumo-line",
              )}
            >
              {value === "chat" ? "Chat" : `Notebook (${displayArtifacts.length})`}
            </Button>
          ))}
        </div>
      )}

      {/* One shared Shiki highlighter for chat + artifact code views (see
      the note in prompt-kit/markdown.tsx) — mounting a provider per message
      would init N highlighters and re-import grammars per message. It must
      wrap the artifact panel too: its Code tab renders CodeHighlighted. */}
      <CodeBlockProvider>
        {/* Nested right sidebar for notebooks: resizable, animated,
        click-to-expand/collapse, trigger in the panel header. `contained`
        keeps collapsed positioning scoped to the chat area;
        mobileBreakpoint={0} disables the mobile drawer (tabs own small
        screens); `open` is controlled so tabs, deep links, and the resize
        handle's auto-collapse stay in sync. Hovering never expands the
        panel — icon rail tooltips show titles, click selects/opens. */}
        <Sidebar.Provider
          contained
          resizable
          side="right"
          open={artifactOpen}
          mobileBreakpoint={0}
          onOpenChange={setArtifactOpen}
          maxWidth={sidebarMaxWidth}
          defaultWidth={sidebarDefaultWidth}
          minWidth={sidebarMinWidth}
          className="relative flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-x-clip lg:flex-row"
        >
          <div
            ref={chatContainerRef}
            className={cn(
              "relative min-h-0 min-w-0 flex-1",
              hasArtifacts && effectiveMobileTab !== "chat" && "hidden lg:block",
            )}
          >
            <ChatContainerRoot className="h-full">
              {/* Bottom padding reserves room for the floating input so the
              last messages can always scroll above it. */}
              <ChatContainerContent className="mx-auto w-full max-w-3xl space-y-0 px-5 pt-4 pb-48">
                {messages.map((message, index) => (
                  <ChatMessageRow
                    key={message.id}
                    message={message}
                    isLastMessage={index === messages.length - 1}
                    isStreaming={index === messages.length - 1 && isLoading}
                    onCopy={handleCopy}
                    onEdit={handleEdit}
                    onDelete={handleDelete}
                    onContinueConversation={handleContinueConversation}
                  />
                ))}
              </ChatContainerContent>

              <div className="absolute bottom-36 left-1/2 flex w-full max-w-3xl -translate-x-1/2 justify-end px-5">
                <ScrollButton />
              </div>
            </ChatContainerRoot>

            {/* Floating composer: overlays the transcript instead of pushing
            it up. The textarea caps and scrolls internally. */}
            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 px-3 pb-4 md:px-5">
              <div className="pointer-events-auto mx-auto max-w-3xl">
                <PromptInput
                  isLoading={isLoading}
                  value={prompt}
                  onValueChange={setPrompt}
                  onSubmit={handleSubmit}
                  maxHeight={160}
                  className="w-full bg-kumo-canvas/90 shadow-lg ring ring-kumo-line backdrop-blur-md"
                >
                  <div className="flex flex-col">
                    <PromptInputTextarea
                      placeholder="Ask anything"
                      aria-label="Ask anything"
                      className="max-h-40 min-h-12 overflow-y-auto p-1 text-sm leading-[1.3]"
                    />

                    <PromptInputActions className="mt-5 flex w-full items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <PromptInputAction tooltip="Add a new action">
                          <Button
                            variant="outline"
                            size="sm"
                            shape="circle"
                            icon={PlusIcon}
                            aria-label="Add a new action"
                            title="Add a new action"
                          />
                        </PromptInputAction>

                        <PromptInputAction tooltip="More actions">
                          <Button
                            variant="outline"
                            size="sm"
                            shape="circle"
                            icon={DotsThreeIcon}
                            aria-label="More actions"
                            title="More actions"
                          />
                        </PromptInputAction>
                      </div>

                      <div className="flex items-center gap-2">
                        <PromptInputAction tooltip="Voice input">
                          <Button
                            variant="outline"
                            size="sm"
                            shape="circle"
                            icon={MicrophoneIcon}
                            aria-label="Voice input"
                            title="Voice input"
                          />
                        </PromptInputAction>

                        {/* While a turn is in flight, swap the arrow for a
                        spinner. We render Loader as the icon instead of using
                        the Button `loading` prop: that prop also disables the
                        button, and here a click must still stop generation. */}
                        <Button
                          variant="primary"
                          size="sm"
                          shape="circle"
                          icon={isLoading ? <Loader size={14} /> : ArrowUpIcon}
                          aria-label={isLoading ? "Stop generating" : "Send message"}
                          title={isLoading ? "Stop generating" : "Send message"}
                          disabled={!prompt.trim() && !isLoading}
                          onClick={handleSubmit}
                        />
                      </div>
                    </PromptInputActions>
                  </div>
                </PromptInput>
              </div>
            </div>
          </div>

          {hasArtifacts && (
            <MarimoArtifactPanel
              artifacts={displayArtifacts}
              activeKey={activeArtifactKey}
              onSelect={setSelectedArtifactKey}
              className={cn(effectiveMobileTab !== "notebook" && "hidden lg:block")}
            />
          )}
        </Sidebar.Provider>
      </CodeBlockProvider>
    </main>
  );
}
