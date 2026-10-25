"use client";

import { Button, Tooltip } from "@cloudflare/kumo";
import { CodeHighlighted, ShikiProvider, type LanguageInput } from "@cloudflare/kumo/code";
import { CheckIcon, CopyIcon } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

/**
 * Languages pre-loaded for chat markdown code fences.
 * Must cover every `lang` passed to `CodeHighlighted`.
 * See `kumo/codehighlighted/AGENTS.md` – only these canonical names
 * (plus their aliases like `js`, `ts`, `sh`) are bundled by Kumo.
 */
export const CODE_BLOCK_LANGUAGES: LanguageInput[] = [
  "tsx",
  "typescript",
  "javascript",
  "jsx",
  "bash",
  "shell",
  "json",
  "jsonc",
  "html",
  "css",
  "python",
  "yaml",
  "markdown",
  "graphql",
  "sql",
  "diff",
  "hcl",
  "toml",
];

/**
 * Shared Shiki context for all code blocks underneath.
 * Mount once per message (see `markdown.tsx`) – or once at the app root.
 * Shiki is lazy-loaded on first mount and reused for every `CodeHighlighted`.
 */
export function CodeBlockProvider({ children }: { children: ReactNode }) {
  return (
    <ShikiProvider engine="javascript" languages={CODE_BLOCK_LANGUAGES}>
      {children}
    </ShikiProvider>
  );
}

export type CodeBlockProps = {
  code?: string;
  language?: string;
  showLineNumbers?: boolean;
  highlightLines?: number[];
  showCopyButton?: boolean;
  /** Accessible labels for i18n – mirrors `CodeHighlighted` + `ClipboardText`. */
  labels?: { copy?: string; copied?: string };
  className?: string;
} & Omit<React.HTMLAttributes<HTMLDivElement>, "lang">;

/**
 * Plain wrapper – kept for backwards compatibility.
 * `CodeHighlighted` already renders its own bordered container
 * (`border-kumo-fill bg-kumo-base`), so this must NOT be a `LayerCard`
 * (avoids nested cards / double borders).
 */
function CodeBlock({ children, className, ...props }: CodeBlockProps) {
  return (
    <div className={cn("w-full min-w-0", className)} {...props}>
      {children}
    </div>
  );
}

/**
 * Feedback duration – matches `ClipboardText` (`COPIED_FEEDBACK_MS`).
 */
const COPIED_FEEDBACK_MS = 1500;

/**
 * Copy helper – mirrors `ClipboardText`: `navigator.clipboard` with a
 * `textarea` + `execCommand` fallback for non-secure contexts.
 */
async function copyTextToClipboard(text: string): Promise<void> {
  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard &&
    typeof navigator.clipboard.writeText === "function"
  ) {
    await navigator.clipboard.writeText(text);
    return;
  }
  if (typeof document !== "undefined") {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "absolute";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    const selection = document.getSelection();
    const previousRange = selection?.rangeCount ? selection.getRangeAt(0) : null;
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
    return;
  }
  throw new Error("Clipboard is unavailable");
}

/**
 * Floating copy button – the Kumo `ClipboardText` manner (icon swap +
 * `Copy` / `Copied!` tooltip) positioned top-right like `CodeHighlighted`'s
 * built-in button. Hidden until hover/focus to avoid cluttering code.
 */
function CodeBlockCopyButton({
  code,
  labels,
}: {
  code: string;
  labels?: { copy?: string; copied?: string };
}) {
  const [copied, setCopied] = useState(false);
  const resetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const copyLabel = labels?.copy ?? "Copy";
  const copiedLabel = labels?.copied ?? "Copied!";

  useEffect(() => {
    return () => {
      if (resetTimeoutRef.current !== null) {
        clearTimeout(resetTimeoutRef.current);
      }
    };
  }, []);

  const handleCopy = useCallback(async () => {
    try {
      await copyTextToClipboard(code);
      setCopied(true);
      if (resetTimeoutRef.current !== null) {
        clearTimeout(resetTimeoutRef.current);
      }
      resetTimeoutRef.current = setTimeout(() => {
        setCopied(false);
        resetTimeoutRef.current = null;
      }, COPIED_FEEDBACK_MS);
    } catch (error) {
      console.warn("Clipboard copy failed", error);
    }
  }, [code]);

  return (
    <div
      className={cn(
        "absolute top-2 right-2",
        !copied && "opacity-0 group-hover:opacity-100 focus-within:opacity-100",
      )}
    >
      <Tooltip
        content={copied ? copiedLabel : copyLabel}
        side="top"
        render={
          <Button
            type="button"
            variant="secondary"
            size="sm"
            shape="square"
            icon={copied ? CheckIcon : CopyIcon}
            aria-label={copied ? copiedLabel : copyLabel}
            onClick={handleCopy}
            className="focus-visible:opacity-100"
          />
        }
      />
      <span className="sr-only" aria-live="polite">
        {copied ? copiedLabel : ""}
      </span>
    </div>
  );
}

/**
 * Chat code block – the Kumo way.
 * Delegates highlighting and dual light/dark themes (`github-light` / `vesper`)
 * to `CodeHighlighted`. The copy button is our own overlay in the
 * `ClipboardText` manner (icon swap + `Copy` / `Copied!` tooltip) positioned
 * top-right – `CodeHighlighted`'s built-in text button is disabled so we
 * don't have to patch `node_modules` to restyle it.
 */
function CodeBlockThemed({
  code = "",
  language = "plaintext",
  showLineNumbers = false,
  highlightLines,
  showCopyButton = true,
  labels,
  className,
  ...props
}: CodeBlockProps) {
  return (
    <CodeBlock className={cn("group relative", className)} {...props}>
      <CodeHighlighted
        code={code}
        lang={language}
        showLineNumbers={showLineNumbers}
        highlightLines={highlightLines}
        showCopyButton={false}
      />
      {showCopyButton && <CodeBlockCopyButton code={code} labels={labels} />}
    </CodeBlock>
  );
}

export type CodeBlockCodeProps = {
  code: string;
  language?: string;
  showLineNumbers?: boolean;
  highlightLines?: number[];
  showCopyButton?: boolean;
  labels?: { copy?: string; copied?: string };
  className?: string;
} & Omit<React.HTMLAttributes<HTMLDivElement>, "lang">;

/**
 * Direct `CodeHighlighted` wrapper.
 * The legacy `theme` prop is intentionally dropped – Kumo hardcodes
 * `github-light` (light) / `vesper` (dark) for consistency.
 */
function CodeBlockCode({
  code,
  language = "tsx",
  showLineNumbers = false,
  highlightLines,
  showCopyButton = false,
  labels,
  className,
  ...props
}: CodeBlockCodeProps) {
  return (
    <div className={cn("group relative w-full min-w-0", className)} {...props}>
      <CodeHighlighted
        code={code}
        lang={language}
        showLineNumbers={showLineNumbers}
        highlightLines={highlightLines}
        showCopyButton={false}
      />
      {showCopyButton && <CodeBlockCopyButton code={code} labels={labels} />}
    </div>
  );
}

export type CodeBlockGroupProps = React.HTMLAttributes<HTMLDivElement>;

/**
 * Kept for backwards compatibility – prefer the `CodeBlockCopyButton`
 * overlay rendered by `CodeBlockThemed` / `CodeBlockCode`.
 */
function CodeBlockGroup({ children, className, ...props }: CodeBlockGroupProps) {
  return (
    <div className={cn("flex items-center justify-between", className)} {...props}>
      {children}
    </div>
  );
}

export { CodeBlockGroup, CodeBlockCode, CodeBlock, CodeBlockThemed };
