"use client";

import { compressToEncodedURIComponent } from "lz-string";

/**
 * Marimo notebook artifacts.
 *
 * The conductor agent emits complete notebooks inside a single fenced block
 * tagged `python marimo`:
 *
 * ```python marimo
 * import marimo
 * ...
 * ```
 *
 * Small notebooks (< 14 KB) embed directly via an lz-string-compressed molab
 * URL (`...#code/{compressed}`). Larger notebooks exceed practical URL limits
 * and fall back to the backend export endpoint (`POST /artifacts/export`),
 * which serves a static WASM page without running code server-side.
 */

/** Raw sources at or below this size embed directly via molab URL. */
export const SMALL_NOTEBOOK_BYTES = 14 * 1024;

const MOLAB_EMBED_BASE = "https://molab.marimo.io/new/wasm/?embed=true";

const FENCE_OPEN_RE = /```python\s+marimo[^\S\n]*\n/g;

export interface MarimoArtifact {
  /** Stable key: `${messageId}:${index}` (index within the message). */
  key: string;
  index: number;
  /** Zero-based position among ALL notebooks in the conversation. Used for
  global "Notebook N" fallback titles and as the stable identity for
  persisted notebook records (with codeHash). */
  ordinal: number;
  code: string;
  /** Sync 64-bit content hash (cyrb53 hex) identifying the notebook source. */
  codeHash: string;
  /** False while the fence is still streaming (no closing ``` yet). */
  complete: boolean;
  byteSize: number;
  title: string;
}

/**
 * Sync 64-bit cyrb53 hash, hex-encoded. Used to match a notebook's source to
 * its persisted record (rename/delete) without async crypto.
 */
export function hashNotebookCode(code: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < code.length; i++) {
    const ch = code.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (h2 >>> 0).toString(16).padStart(8, "0") + (h1 >>> 0).toString(16).padStart(8, "0");
}

function cleanTitle(raw: string): string {
  return raw
    .replace(/[*_`~]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

function deriveTitle(code: string, fallback: string): string {
  // 1. mo.md("# Title") / mo.md(f"# Title") — inline or triple-quoted.
  const mdPatterns = [
    /mo\.md\(\s*(?:f\s*)?"""\s*\n\s*#\s+([^\n]{1,80})/,
    /mo\.md\(\s*(?:f\s*)?["']#\s+([^"'#\n]{1,80})/,
    /mo\.md\(\s*(?:f\s*)?["']\s*#\s+([^"'#\n]{1,80})/,
  ];
  for (const pattern of mdPatterns) {
    const match = code.match(pattern);
    if (match) {
      const title = cleanTitle(match[1]);
      if (title.length >= 2) return title;
    }
  }
  // 2. First top-level `# Comment` outside the PEP 723 header block.
  const withoutPep723 = code.replace(/^# \/\/\/ script[\s\S]*?^# \/\/\/\s*$/m, "");
  const comment = withoutPep723.match(/^#\s(?!\/\/\/|!|-|\*)([^#\n]{4,80})$/m);
  if (comment) {
    const title = cleanTitle(comment[1]);
    if (title.length >= 2) return title;
  }
  return fallback;
}

/**
 * Extract every ```python marimo fence (including a trailing partial).
 * `startOrdinal` is the count of notebooks already seen earlier in the
 * conversation, so fallback titles number globally (Notebook 1, 2, …)
 * instead of restarting at 1 in every message.
 */
export function extractMarimoArtifacts(
  messageId: string,
  content: string,
  startOrdinal = 0,
): MarimoArtifact[] {
  const artifacts: MarimoArtifact[] = [];
  let match: RegExpExecArray | null;
  // Reset lastIndex: module-level regex is stateful across calls.
  FENCE_OPEN_RE.lastIndex = 0;
  let index = 0;
  while ((match = FENCE_OPEN_RE.exec(content)) !== null) {
    const codeStart = match.index + match[0].length;
    const closeIndex = content.indexOf("```", codeStart);
    const complete = closeIndex !== -1;
    const raw = complete ? content.slice(codeStart, closeIndex) : content.slice(codeStart);
    const code = raw.replace(/\s+$/, "");
    const byteSize = new TextEncoder().encode(code).length;
    const ordinal = startOrdinal + index;
    artifacts.push({
      key: `${messageId}:${index}`,
      index,
      ordinal,
      code,
      codeHash: hashNotebookCode(code),
      complete,
      byteSize,
      title: deriveTitle(code, `Notebook ${ordinal + 1}`),
    });
    index += 1;
    if (!complete) break;
    FENCE_OPEN_RE.lastIndex = closeIndex + 3;
  }
  FENCE_OPEN_RE.lastIndex = 0;
  return artifacts;
}

/**
 * Replace marimo fences with short placeholders so the chat column stays
 * readable — the full notebook lives in the artifact panel. Streaming
 * (unclosed) fences render a "generating" placeholder instead.
 */
export function stripMarimoFences(content: string): string {
  FENCE_OPEN_RE.lastIndex = 0;
  let result = "";
  let cursor = 0;
  let match: RegExpExecArray | null;
  let index = 0;
  while ((match = FENCE_OPEN_RE.exec(content)) !== null) {
    const codeStart = match.index + match[0].length;
    const closeIndex = content.indexOf("```", codeStart);
    const complete = closeIndex !== -1;
    result += content.slice(cursor, match.index);
    result += complete
      ? `\n> Notebook ${index + 1} is shown in the notebook panel.\n`
      : `\n> Generating notebook…\n`;
    index += 1;
    if (!complete) {
      cursor = content.length;
      break;
    }
    cursor = closeIndex + 3;
    FENCE_OPEN_RE.lastIndex = cursor;
  }
  result += content.slice(cursor);
  FENCE_OPEN_RE.lastIndex = 0;
  return result;
}

/** Direct molab embed URL for small notebooks (lz-string compressed hash). */
export function buildMolabEmbedUrl(code: string): string {
  return `${MOLAB_EMBED_BASE}#code/${compressToEncodedURIComponent(code)}`;
}

/**
 * Structural check: does the fence content look like a runnable marimo
 * notebook? Mirrors the backend's `_is_marimo_notebook` gate in
 * `marimo_artifacts.py` so small (direct-embed) notebooks get the same
 * validation as large (exported) ones. Without an App definition/cells,
 * molab fails with a cryptic error page and nothing runs — the UI shows a
 * clear message instead.
 */
export function looksLikeMarimoNotebook(code: string): boolean {
  return code.includes("marimo") && (code.includes("marimo.App") || code.includes("@app.cell"));
}

export function isSmallNotebook(byteSize: number): boolean {
  return byteSize <= SMALL_NOTEBOOK_BYTES;
}

/** Trigger a `.py` download of the notebook source. */
export function downloadNotebook(code: string, filename: string): void {
  if (typeof document === "undefined") return;
  const blob = new Blob([code], { type: "text/x-python;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename.endsWith(".py") ? filename : `${filename}.py`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export function artifactFilename(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return slug || "notebook";
}
