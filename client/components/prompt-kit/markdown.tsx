"use client";

import { cn } from "@/lib/utils";
import { marked } from "marked";
import { memo, useId, useMemo } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { CodeBlockThemed } from "./code-block";
import { DataTable, type DataTableColumn, type DataTableRow } from "./data-table";

export type MarkdownProps = {
  children: string;
  id?: string;
  className?: string;
  isStreaming?: boolean;
  components?: Partial<Components>;
};

type MarkdownBlock = {
  content: string;
  type: "table" | "other";
};

function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const tokens = marked.lexer(markdown);
  return tokens.map((token) => ({
    content: token.raw,
    type: token.type === "table" ? "table" : "other",
  }));
}

function extractLanguage(className?: string): string {
  if (!className) return "plaintext";
  const match = className.match(/language-([\w+-]+)/i);
  if (!match) return "plaintext";
  return match[1].toLowerCase();
}

function extractCodeText(children: React.ReactNode): string {
  const text = Array.isArray(children)
    ? children.map((child) => String(child)).join("")
    : String(children ?? "");
  // react-markdown appends a trailing newline to fenced blocks – strip one.
  return text.replace(/\n$/, "");
}

const INITIAL_COMPONENTS: Partial<Components> = {
  // Headings — Kumo semantic text, semibold (never font-bold), sentence case
  // (no uppercase/capitalize). 14px+ body rule: headings may exceed 14px.
  h1: function H1({ children }) {
    return (
      <h1 className="mt-5 mb-2 text-lg font-semibold text-kumo-strong first:mt-0">{children}</h1>
    );
  },
  h2: function H2({ children }) {
    return (
      <h2 className="mt-5 mb-2 text-base font-semibold text-kumo-strong first:mt-0">{children}</h2>
    );
  },
  h3: function H3({ children }) {
    return (
      <h3 className="mt-4 mb-2 text-sm font-semibold text-kumo-strong first:mt-0">{children}</h3>
    );
  },
  h4: function H4({ children }) {
    return (
      <h4 className="mt-4 mb-2 text-sm font-semibold text-kumo-strong first:mt-0">{children}</h4>
    );
  },
  // Body text — 14px (text-sm) per kumo-design content-text-size.
  // Semantic token adapts to light/dark via light-dark(), unlike `prose`
  // which hardcodes light-mode grays and goes invisible in dark mode.
  p: function P({ children }) {
    return (
      <p className="my-3 text-sm leading-relaxed text-kumo-default first:mt-0 last:mb-0">
        {children}
      </p>
    );
  },
  // Links — semantic link token, immediate hover (no transition-colors).
  a: function A({ children, href }) {
    return (
      <a
        href={href}
        className="font-medium text-kumo-link underline underline-offset-2 hover:opacity-80"
      >
        {children}
      </a>
    );
  },
  // Bold inline — font-medium per kumo-design (never font-bold).
  strong: function Strong({ children }) {
    return <strong className="font-medium text-kumo-strong">{children}</strong>;
  },
  em: function Em({ children }) {
    return <em className="text-kumo-default italic">{children}</em>;
  },
  ul: function UL({ children }) {
    return (
      <ul className="my-3 list-disc space-y-1.5 ps-6 text-sm text-kumo-default marker:text-kumo-subtle first:mt-0 last:mb-0">
        {children}
      </ul>
    );
  },
  ol: function OL({ children }) {
    return (
      <ol className="my-3 list-decimal space-y-1.5 ps-6 text-sm text-kumo-default marker:text-kumo-subtle first:mt-0 last:mb-0">
        {children}
      </ol>
    );
  },
  li: function LI({ children }) {
    return <li className="leading-relaxed text-kumo-default">{children}</li>;
  },
  // GFM task-list checkboxes.
  input: function Input(props) {
    if (props.type !== "checkbox") return <input {...props} />;
    return (
      <input
        {...props}
        disabled={props.disabled ?? true}
        className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-kumo-brand"
      />
    );
  },
  blockquote: function Blockquote({ children }) {
    return (
      <blockquote className="my-3 border-l-2 border-kumo-line ps-3 text-sm text-kumo-subtle italic first:mt-0 last:mb-0">
        {children}
      </blockquote>
    );
  },
  hr: function HR() {
    return <hr className="my-6 border-t border-kumo-hairline" />;
  },
  table: function Table({ children }) {
    return (
      <span className="scrollbar-on-hover my-4 block overflow-x-auto rounded-md ring ring-kumo-line first:mt-0 last:mb-0">
        <table className="w-full border-collapse text-sm">{children}</table>
      </span>
    );
  },
  thead: function THead({ children }) {
    return <thead className="bg-kumo-tint">{children}</thead>;
  },
  th: function TH({ children }) {
    return (
      <th className="border-b border-kumo-line px-3 py-2 text-left text-sm font-semibold text-kumo-strong">
        {children}
      </th>
    );
  },
  td: function TD({ children }) {
    return (
      <td className="border-b border-kumo-hairline px-3 py-2 text-sm text-kumo-default last:border-b-0">
        {children}
      </td>
    );
  },
  tr: function TR({ children }) {
    return <tr>{children}</tr>;
  },
  img: function Img({ src, alt }) {
    if (!src) return null;
    return (
      // oxlint-disable-next-line @next/next/no-img-element
      <img
        src={src as string}
        alt={(alt as string) ?? ""}
        className="my-3 h-auto max-w-full rounded-md ring ring-kumo-line first:mt-0 last:mb-0"
      />
    );
  },
  code: function CodeComponent({ className, children, ...props }) {
    // Block code always carries a `language-*` class from react-markdown.
    // (Don't use node position: a single-line fence would misclassify as inline.)
    const language = extractLanguage(className);
    const isBlock = /language-/.test(className ?? "");

    if (!isBlock) {
      return (
        <span
          className={cn(
            "rounded-sm bg-kumo-recessed px-1 font-mono text-[0.9em] text-kumo-default",
            className,
          )}
          {...props}
        >
          {children}
        </span>
      );
    }

    return (
      <CodeBlockThemed
        code={extractCodeText(children)}
        language={language}
        showCopyButton
        className="my-3 first:mt-0 last:mb-0"
      />
    );
  },
  pre: function PreComponent({ children }) {
    return <>{children}</>;
  },
};

function splitMarkdownRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split(/(?<!\\)\|/)
    .map((cell) => cell.trim().replace(/\\\|/g, "|"));
}

function cleanMarkdownCell(raw: string): string {
  return raw
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\(([^)]*)\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*\*([^*]+)\*\*\*/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/~~([^~]+)~~/g, "$1")
    .trim();
}

/**
 * Parse a GFM markdown table (header + delimiter + body) into the
 * column/row shapes the interactive DataTable expects. Returns null when the
 * source is not a well-formed table, e.g. a mid-stream fragment.
 */
function parseMarkdownTableBlock(
  source: string,
): { columns: DataTableColumn[]; rows: DataTableRow[] } | null {
  const lines = source
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  // A GFM table needs at least header + delimiter rows.
  if (lines.length < 2) return null;

  const header = splitMarkdownRow(lines[0]);
  const delimiter = lines[1];
  // Delimiter row: one `:?-+:?` segment per column.
  if (header.length === 0 || !/^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/.test(delimiter)) {
    return null;
  }

  const alignCells = splitMarkdownRow(delimiter);
  const columns = header.map((rawHeader, index) => {
    const delimiterCell = alignCells[index] ?? "";
    const align: "left" | "right" | "center" | undefined =
      delimiterCell.startsWith(":") && delimiterCell.endsWith(":")
        ? "center"
        : delimiterCell.endsWith(":")
          ? "right"
          : delimiterCell.startsWith(":")
            ? "left"
            : undefined;

    return {
      key: `col_${index}`,
      header: cleanMarkdownCell(rawHeader),
      align,
    };
  });

  const rows: DataTableRow[] = [];
  for (const line of lines.slice(2)) {
    const cells = splitMarkdownRow(line);
    const row: DataTableRow = {};
    let hasContent = false;
    columns.forEach((column, index) => {
      const value = cleanMarkdownCell(cells[index] ?? "");
      if (value !== "") hasContent = true;
      row[column.key] = value;
    });
    if (hasContent) rows.push(row);
  }

  return { columns, rows };
}

const MarkdownTable = memo(function MarkdownTable({ source }: { source: string }) {
  const parsed = useMemo(() => parseMarkdownTableBlock(source), [source]);
  if (!parsed || parsed.rows.length === 0) return null;
  return <DataTable columns={parsed.columns} rows={parsed.rows} />;
});
MarkdownTable.displayName = "MarkdownTable";

const MemoizedMarkdownBlock = memo(
  function MarkdownBlock({
    content,
    components = INITIAL_COMPONENTS,
  }: {
    content: string;
    components?: Partial<Components>;
  }) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} components={components}>
        {content}
      </ReactMarkdown>
    );
  },
  function propsAreEqual(prevProps, nextProps) {
    return prevProps.content === nextProps.content && prevProps.components === nextProps.components;
  },
);

MemoizedMarkdownBlock.displayName = "MemoizedMarkdownBlock";

function MarkdownComponent({
  children,
  id,
  className,
  isStreaming = false,
  components = INITIAL_COMPONENTS,
}: MarkdownProps) {
  const generatedId = useId();
  const blockId = id ?? generatedId;
  const blocks = useMemo(() => parseMarkdownBlocks(children), [children]);

  // NOTE: no Shiki/CodeBlock provider here on purpose. Markdown is rendered
  // once per chat message, and each provider spins up its own Shiki
  // highlighter (grammar WASM/JS + themes + 19 languages). Mount the single
  // shared <CodeBlockProvider> once around the message list instead —
  // otherwise every message pays the full highlighter init cost.
  return (
    <div className={className}>
      {blocks.map((block, index) =>
        // While a message is streaming, tables render as the plain static
        // markdown table (rows appear as they stream). Only once streaming
        // finishes — or for persisted/history messages — does the table
        // upgrade to the interactive sortable/searchable/paginated view.
        !isStreaming && block.type === "table" ? (
          <MarkdownTable key={`${blockId}-block-${index}`} source={block.content} />
        ) : (
          <MemoizedMarkdownBlock
            key={`${blockId}-block-${index}`}
            content={block.content}
            components={components}
          />
        ),
      )}
    </div>
  );
}

const Markdown = memo(MarkdownComponent);
Markdown.displayName = "Markdown";

export { Markdown };
