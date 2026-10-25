"use client";

import { Button, Sidebar, Text, Tooltip, useSidebar } from "@cloudflare/kumo";
import {
  ArrowsInIcon,
  ArrowsOutIcon,
  CopyIcon,
  DownloadSimpleIcon,
  EyeIcon,
  NotebookIcon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CodeBlockThemed } from "@/components/prompt-kit/code-block";
import { getBackendToken } from "@/lib/auth-client";
import {
  artifactFilename,
  buildMolabEmbedUrl,
  downloadNotebook,
  isSmallNotebook,
  looksLikeMarimoNotebook,
  type MarimoArtifact,
} from "@/lib/marimo";
import { cn } from "@/lib/utils";

const backendUrl = process.env.NEXT_PUBLIC_PYTHON_BACKEND_URL ?? "http://localhost:8000";

type ExportState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; htmlUrl: string }
  | { status: "error"; message: string };

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (
      typeof navigator !== "undefined" &&
      navigator.clipboard &&
      typeof navigator.clipboard.writeText === "function"
    ) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

/** Fullscreen helpers with a Safari fallback. */
function requestFullscreen(element: HTMLElement): Promise<void> {
  if (typeof element.requestFullscreen === "function") {
    return element.requestFullscreen();
  }
  const webkit = (
    element as HTMLElement & {
      webkitRequestFullscreen?: () => Promise<void> | void;
    }
  ).webkitRequestFullscreen;
  if (typeof webkit === "function") return Promise.resolve(webkit.call(element));
  return Promise.reject(new Error("Fullscreen is not supported"));
}

function ArtifactToolbar({
  artifact,
  isFullscreen,
  onToggleFullscreen,
  exportState,
  onExport,
}: {
  artifact: MarimoArtifact;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  exportState: ExportState;
  onExport: () => void;
}) {
  const needsExport = !isSmallNotebook(artifact.byteSize) && exportState.status !== "ready";
  return (
    <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-1.5">
      {needsExport && (
        <Button
          variant="primary"
          size="sm"
          icon={EyeIcon}
          aria-label="Render full preview on the server"
          title="Render full preview on the server"
          disabled={exportState.status === "loading" || !artifact.complete}
          onClick={onExport}
        >
          {exportState.status === "loading" ? "Rendering…" : "Render preview"}
        </Button>
      )}
      <Button
        variant="secondary"
        size="sm"
        shape="square"
        icon={CopyIcon}
        aria-label="Copy notebook source"
        title="Copy notebook source"
        onClick={() => void copyText(artifact.code)}
      />
      <Button
        variant="secondary"
        size="sm"
        shape="square"
        icon={DownloadSimpleIcon}
        aria-label="Download notebook (.py)"
        title="Download notebook (.py)"
        onClick={() => downloadNotebook(artifact.code, artifactFilename(artifact.title))}
      />
      <Button
        variant="secondary"
        size="sm"
        shape="square"
        icon={isFullscreen ? ArrowsInIcon : ArrowsOutIcon}
        aria-label={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
        title={isFullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
        onClick={onToggleFullscreen}
      />
    </div>
  );
}

/**
 * Full-bleed iframe that fades in on load over a theme-aware placeholder,
 * so the white first paint never flashes. Keyed by src so each notebook
 * (or re-render) restarts hidden.
 */
function ArtifactFrame({ src, title }: { src: string; title: string }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <div className="relative min-h-84 w-full min-w-0 flex-1 overflow-hidden bg-kumo-base">
      {!loaded && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Text variant="secondary">Loading notebook…</Text>
        </div>
      )}
      <iframe
        title={title}
        src={src}
        sandbox="allow-scripts allow-same-origin allow-downloads allow-popups allow-forms"
        allow="microphone"
        allowFullScreen
        loading="lazy"
        onLoad={() => setLoaded(true)}
        // Dark-mode inversion lives in globals.css
        // ([data-mode="dark"] .marimo-frame).
        className={cn(
          "marimo-frame absolute inset-0 h-full w-full border-0 bg-kumo-base transition-opacity duration-300",
          loaded ? "opacity-100" : "opacity-0",
        )}
      />
    </div>
  );
}

function ArtifactPreview({
  artifact,
  exportState,
  onExport,
  onShowCode,
}: {
  artifact: MarimoArtifact;
  exportState: ExportState;
  onExport: () => void;
  onShowCode: () => void;
}) {
  const embedUrl = useMemo(() => {
    // Compress once per finished small notebook — never during streaming,
    // where the code changes on every token.
    if (!artifact.complete || !isSmallNotebook(artifact.byteSize)) return null;
    try {
      return buildMolabEmbedUrl(artifact.code);
    } catch {
      return null;
    }
  }, [artifact.code, artifact.complete, artifact.byteSize]);

  if (!artifact.complete) {
    return (
      <div className="flex min-h-84 w-full min-w-0 flex-1 items-center justify-center bg-kumo-base">
        <Text variant="secondary">Generating notebook…</Text>
      </div>
    );
  }

  if (exportState.status === "ready") {
    return (
      <ArtifactFrame
        key={exportState.htmlUrl}
        src={exportState.htmlUrl}
        title={`${artifact.title} (server-rendered preview)`}
      />
    );
  }

  // Structurally invalid output (no App definition/cells): molab would show
  // a cryptic error page and nothing would run. Say so plainly and point at
  // the code instead of embedding a broken preview.
  if (!looksLikeMarimoNotebook(artifact.code)) {
    return (
      <div className="flex min-h-84 w-full min-w-0 flex-1 flex-col items-center justify-center gap-3 bg-kumo-base px-5 text-center">
        <Text as="h3" variant="heading">
          Notebook didn&apos;t run
        </Text>
        <Text variant="secondary">
          The generated code isn&apos;t a runnable marimo notebook (it needs an App definition with
          cells). Inspect or fix the source, then ask for a corrected notebook.
        </Text>
        <div className="flex flex-wrap justify-center gap-2">
          <Button variant="primary" size="sm" onClick={onShowCode}>
            View code
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={DownloadSimpleIcon}
            onClick={() => downloadNotebook(artifact.code, artifactFilename(artifact.title))}
          >
            Download .py
          </Button>
        </div>
      </div>
    );
  }

  if (!isSmallNotebook(artifact.byteSize)) {
    return (
      <div className="flex min-h-84 w-full min-w-0 flex-1 flex-col items-center justify-center gap-3 bg-kumo-base px-5 text-center">
        <Text as="h3" variant="heading">
          Large notebook ({formatBytes(artifact.byteSize)})
        </Text>
        <Text variant="secondary">
          {exportState.status === "error"
            ? `Server preview failed: ${exportState.message} Download the file instead.`
            : "Too large to embed by URL. Render a full preview on the server, or download the file."}
        </Text>
        {exportState.status !== "loading" && (
          <div className="flex flex-wrap justify-center gap-2">
            <Button variant="primary" size="sm" icon={EyeIcon} onClick={onExport}>
              Render full preview
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={DownloadSimpleIcon}
              onClick={() => downloadNotebook(artifact.code, artifactFilename(artifact.title))}
            >
              Download .py
            </Button>
          </div>
        )}
        {exportState.status === "loading" && <Text variant="secondary">Rendering preview…</Text>}
      </div>
    );
  }

  if (!embedUrl) {
    return (
      <div className="flex min-h-84 w-full min-w-0 flex-1 items-center justify-center bg-kumo-base">
        <Text variant="secondary">
          Could not build the live preview. Use the code tab or download.
        </Text>
      </div>
    );
  }

  return (
    <ArtifactFrame key={embedUrl} src={embedUrl} title={`${artifact.title} (live notebook)`} />
  );
}

/** Slim header + Preview/Code tabs; the body below owns all remaining space. */
function ArtifactChrome({
  artifact,
  tab,
  onTabChange,
  toolbar,
  children,
}: {
  artifact: MarimoArtifact;
  tab: "preview" | "code";
  onTabChange: (tab: "preview" | "code") => void;
  toolbar: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b border-kumo-hairline px-2 py-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div
            role="tablist"
            aria-label="Notebook view"
            className="flex shrink-0 items-center gap-1 rounded-md bg-kumo-recessed p-1"
          >
            {(["preview", "code"] as const).map((value) => (
              <button
                key={value}
                role="tab"
                aria-selected={tab === value}
                type="button"
                onClick={() => onTabChange(value)}
                className={cn(
                  "rounded-sm px-2.5 py-1 text-sm font-medium text-kumo-subtle",
                  tab === value && "bg-kumo-base text-kumo-strong ring ring-kumo-line",
                )}
              >
                {value === "preview" ? "Preview" : "Code"}
              </button>
            ))}
          </div>
          {toolbar}
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <div className="hidden min-w-0 min-[480px]:block">
            <Text variant="secondary" truncate>
              {formatBytes(artifact.byteSize)}
              {!isSmallNotebook(artifact.byteSize) && " · large"}
              {!artifact.complete && " · generating"}
            </Text>
          </div>
          {/* Kumo sidebar trigger: collapses/expands with animation. */}
          <Sidebar.Trigger className="shrink-0" />
        </div>
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
    </>
  );
}

/**
 * Single notebook: owns its container so true (native) fullscreen covers
 * exactly this artifact. The preview/code body is full-bleed — no padding,
 * card, or margins around it.
 */
export function MarimoArtifactView({ artifact }: { artifact: MarimoArtifact }) {
  const [tab, setTab] = useState<"preview" | "code">("preview");
  const [exportState, setExportState] = useState<ExportState>({
    status: "idle",
  });
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onChange = () =>
      setIsFullscreen(typeof document !== "undefined" && document.fullscreenElement !== null);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  // Exit fullscreen if this artifact unmounts while fullscreen (e.g. the
  // user switches notebooks) so the browser never strands a dead element.
  useEffect(() => {
    return () => {
      if (typeof document !== "undefined" && document.fullscreenElement !== null) {
        void document.exitFullscreen().catch(() => undefined);
      }
    };
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (typeof document === "undefined") return;
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => undefined);
      return;
    }
    const element = containerRef.current;
    if (element) void requestFullscreen(element).catch(() => undefined);
  }, []);

  const handleExport = async () => {
    if (exportState.status === "loading") return;
    setExportState({ status: "loading" });
    try {
      const token = await getBackendToken();
      const response = await fetch(`${backendUrl}/artifacts/export`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ code: artifact.code }),
      });
      if (!response.ok) {
        throw new Error(`Export failed: ${response.status}`);
      }
      const data = (await response.json()) as {
        exported: boolean;
        html_url: string | null;
        error?: string | null;
      };
      if (data.exported && data.html_url) {
        setExportState({
          status: "ready",
          htmlUrl: `${backendUrl}${data.html_url}`,
        });
      } else {
        throw new Error(data.error || "Export unavailable");
      }
    } catch (error) {
      setExportState({
        status: "error",
        message: error instanceof Error ? error.message : "Export failed",
      });
    }
  };

  const onExport = () => void handleExport();

  return (
    <div
      ref={containerRef}
      className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-x-clip bg-kumo-base"
    >
      <ArtifactChrome
        artifact={artifact}
        tab={tab}
        onTabChange={setTab}
        toolbar={
          <ArtifactToolbar
            artifact={artifact}
            isFullscreen={isFullscreen}
            onToggleFullscreen={toggleFullscreen}
            exportState={exportState}
            onExport={onExport}
          />
        }
      >
        {tab === "preview" ? (
          <ArtifactPreview
            artifact={artifact}
            exportState={exportState}
            onExport={onExport}
            onShowCode={() => setTab("code")}
          />
        ) : (
          <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            <CodeBlockThemed
              code={artifact.code}
              language="python"
              showLineNumbers
              showCopyButton
            />
          </div>
        )}
      </ArtifactChrome>
    </div>
  );
}

/**
 * Collapsed icon rail: one button per notebook. Hover shows the notebook
 * title via a Kumo Tooltip and does nothing else; only clicking selects
 * and expands. Never expand or preview on hover.
 */
function ArtifactRail({
  artifacts,
  activeKey,
  onSelect,
}: {
  artifacts: MarimoArtifact[];
  activeKey: string | null;
  onSelect: (key: string) => void;
}) {
  const { setOpen } = useSidebar();
  return (
    <div className="flex h-full flex-col items-center gap-1 overflow-y-auto py-2">
      <Tooltip
        content="Notebooks"
        side="left"
        render={
          <Button
            variant="ghost"
            shape="square"
            icon={NotebookIcon}
            aria-label="Expand notebooks panel"
            onClick={() => setOpen(true)}
            className="shrink-0 text-kumo-subtle"
          />
        }
      />
      <div aria-hidden="true" className="h-px w-6 shrink-0 bg-kumo-hairline" />
      {artifacts.map((item, pos) => (
        <Tooltip
          key={item.key}
          content={item.title}
          side="left"
          render={
            <Button
              variant="ghost"
              shape="square"
              aria-label={`Open ${item.title}`}
              onClick={() => {
                onSelect(item.key);
                setOpen(true);
              }}
              className={cn(
                "shrink-0 text-kumo-subtle font-sans",
                item.key === activeKey && "bg-kumo-tint text-kumo-strong",
              )}
            >
              {pos + 1}
            </Button>
          }
        />
      ))}
    </div>
  );
}

/**
 * Sidebar body: full panel when open, icon rail when collapsed.
 * Hovering the rail or the sidebar never expands or previews a notebook —
 * tooltips show titles, click selects/opens.
 */
function ArtifactSidebarBody({
  artifacts,
  activeKey,
  onSelect,
}: {
  artifacts: MarimoArtifact[];
  activeKey: string | null;
  onSelect: (key: string) => void;
}) {
  const { open } = useSidebar();
  const active =
    artifacts.find((item) => item.key === activeKey) ?? artifacts[artifacts.length - 1];

  if (!active) return null;
  if (!open) {
    return <ArtifactRail artifacts={artifacts} activeKey={active.key} onSelect={onSelect} />;
  }
  return (
    <>
      {artifacts.length > 1 && (
        <div
          role="tablist"
          aria-label="Notebooks"
          className="flex w-full min-w-0 shrink-0 items-center gap-1 overflow-x-auto border-b border-kumo-hairline bg-kumo-recessed px-2 py-1"
        >
          {artifacts.map((item) => (
            <button
              key={item.key}
              role="tab"
              aria-selected={item.key === active.key}
              type="button"
              title={item.title}
              onClick={() => onSelect(item.key)}
              className={cn(
                "min-w-24 flex-1 truncate rounded-sm px-2.5 py-1 text-sm font-medium text-kumo-subtle",
                item.key === active.key && "bg-kumo-base text-kumo-strong ring ring-kumo-line",
              )}
            >
              {item.title}
            </button>
          ))}
        </div>
      )}
      <MarimoArtifactView key={active.key} artifact={active} />
    </>
  );
}

/**
 * Notebook panel as a Kumo right sidebar: resizable, animated
 * collapse/expand, click-to-open. Must be a child of the transcript's
 * nested `Sidebar.Provider` (side="right"). Hovering never opens or
 * previews — rail icon tooltips show titles, click selects.
 */
export function MarimoArtifactPanel({
  artifacts,
  activeKey,
  onSelect,
  className,
}: {
  artifacts: MarimoArtifact[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  className?: string;
}) {
  // The aside sets no display utility itself, so `hidden lg:block` is safe.
  // max-w-full caps the fixed pixel width on narrow screens (mobile tabs).
  return (
    <Sidebar className={cn("min-w-0 max-w-full", className)}>
      {/* Custom body instead of Sidebar.Content: the scroll-area padding and
      auto height would break the full-height flex-1 preview. The sidebar
      still owns positioning, animation, and resize behavior (no peek). */}
      <div className="flex min-h-0 w-full min-w-0 bg-kumo-canvas max-w-full flex-1 flex-col overflow-x-clip whitespace-normal">
        <ArtifactSidebarBody artifacts={artifacts} activeKey={activeKey} onSelect={onSelect} />
      </div>
      <Sidebar.ResizeHandle />
    </Sidebar>
  );
}
