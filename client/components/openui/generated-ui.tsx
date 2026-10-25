"use client";

import { type LibraryActionEvent, type ParseResult, Renderer } from "@openuidev/react-lang";
import { Text } from "@cloudflare/kumo";
import { Component, type ReactNode, useCallback, useMemo, useState } from "react";

import { MessageContent } from "@/components/prompt-kit/message";
import { library } from "@/lib/openui/library";

/**
 * Renders one assistant reply: OpenUI Lang responses become live interfaces,
 * everything else (plain prose, marimo notebooks, a reply the parser cannot
 * read) keeps the transcript's markdown renderer.
 *
 * The split is deliberately two-signalled. While a reply streams, a cheap
 * statement-shape check picks what to mount, so a prose answer never flashes an
 * empty UI shell. Once the stream ends the parser's own verdict wins: no `root`
 * means the text was not a program, and markdown takes over.
 */
const OPENUI_STATEMENT = /^\$?[A-Za-z_][\w$]*\s*=/;

export function looksLikeOpenUI(text: string): boolean {
  return text.split("\n").some((line) => OPENUI_STATEMENT.test(line.trimStart()));
}

/**
 * A program may arrive wrapped in a ```openui-lang fence. Strip the fence lines
 * rather than matching a complete fence, so a half-streamed wrapper is still a
 * valid program on every chunk.
 */
function unwrapFence(text: string): string {
  return text.replace(/^\s*```[a-zA-Z-]*\s*\n/, "").replace(/\n?```\s*$/, "");
}

/**
 * Last line of defence so the OpenUI integration can never hard-crash the
 * transcript. OpenUI's own `ElementErrorBoundary` catches a throw from a
 * single component and shows that component's last good state; this boundary
 * sits around the *whole* reply, so if the interface tree still throws (a
 * component bug, or props the schema allowed but the renderer can't draw) the
 * message degrades to the transcript's markdown renderer instead of blanking
 * the conversation. Remounted on the streaming→settled edge via `key`, so a
 * transient mid-stream throw never latches — the finished program gets a
 * fresh attempt.
 */
class OpenUIErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.error("[openui] interface crashed — falling back to markdown:", error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function GeneratedUI({
  content,
  isStreaming,
  onContinueConversation,
}: {
  content: string;
  isStreaming?: boolean;
  onContinueConversation?: (message: string) => void;
}) {
  const response = useMemo(() => unwrapFence(content), [content]);
  const [parseState, setParseState] = useState<"rooted" | "empty" | null>(null);

  const handleParseResult = useCallback((result: ParseResult | null) => {
    setParseState(result?.root ? "rooted" : "empty");
  }, []);

  // `@ToAssistant` turns a generated button into the next user turn;
  // `@OpenUrl` opens a generated link. Both keep the interface usable without
  // adding app-specific wiring to the library.
  const handleAction = useCallback(
    (event: LibraryActionEvent<typeof library>) => {
      const params = (event.params ?? {}) as Record<string, unknown>;

      if (event.type === "continue_conversation") {
        const message =
          typeof params.message === "string" ? params.message : event.humanFriendlyMessage;
        if (message) {
          onContinueConversation?.(message);
        }
        return;
      }

      if (event.type === "open_url" && typeof params.url === "string") {
        window.open(params.url, "_blank", "noopener,noreferrer");
      }
    },
    [onContinueConversation],
  );

  const isProgram = looksLikeOpenUI(response);
  const parserRejected = !isStreaming && parseState === "empty";

  const markdownFallback = (
    <MessageContent
      className="max-w-full flex-1 bg-transparent p-0 text-kumo-default"
      isStreaming={isStreaming}
      markdown
    >
      {content}
    </MessageContent>
  );

  if (!response.trim() || !isProgram || parserRejected) {
    return markdownFallback;
  }

  return (
    <div className="w-full min-w-0">
      {isStreaming && parseState !== "rooted" ? (
        <div className="mb-2">
          <Text size="sm" variant="secondary">
            Building interface…
          </Text>
        </div>
      ) : null}
      <OpenUIErrorBoundary key={isStreaming ? "streaming" : "settled"} fallback={markdownFallback}>
        <Renderer
          isStreaming={isStreaming}
          library={library}
          onAction={handleAction}
          onError={(errors) => {
            // Without this the Renderer only `console.warn`s, and the only
            // other visibility is the dev-only OpenUI Inspect widget — neither
            // helps diagnose a broken program in a real session. Structured
            // parser/library errors land in the console with their source+code.
            if (errors.length > 0) {
              console.error("[openui] interface errors:", errors);
            }
          }}
          onParseResult={handleParseResult}
          publishObservability={false}
          response={response}
        />
      </OpenUIErrorBoundary>
    </div>
  );
}
