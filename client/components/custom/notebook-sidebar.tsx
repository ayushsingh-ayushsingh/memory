"use client";

import { Button, Input, Sidebar, useKumoToastManager } from "@cloudflare/kumo";
import { CheckIcon, NotebookIcon, PencilSimpleIcon, TrashIcon, XIcon } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { displayTitle, useNotebookStore, type NotebookRecord } from "@/lib/notebook-store";

function NotebookRow({ record }: { record: NotebookRecord }) {
  const router = useRouter();
  const toastManager = useKumoToastManager();
  const renameNotebook = useNotebookStore((state) => state.renameNotebook);
  const deleteNotebook = useNotebookStore((state) => state.deleteNotebook);

  const title = displayTitle(record);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  const open = () => {
    if (editing) return;
    router.push(`/dashboard/chat/${record.conversationId}?notebook=${record.id}`);
  };

  const saveRename = async () => {
    const trimmed = draft.trim();
    if (trimmed === title) {
      setEditing(false);
      return;
    }
    setBusy(true);
    const ok = await renameNotebook(record.id, trimmed);
    setBusy(false);
    setEditing(false);
    if (!ok) {
      setDraft(title);
      toastManager.add({
        title: "Rename failed",
        description: "Please try again.",
        variant: "error",
      });
    }
  };

  const confirmDelete = async () => {
    setBusy(true);
    const ok = await deleteNotebook(record.id);
    setBusy(false);
    setConfirmingDelete(false);
    if (!ok) {
      toastManager.add({
        title: "Delete failed",
        description: "Please try again.",
        variant: "error",
      });
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
            aria-label="Rename notebook"
            placeholder="Notebook name (empty clears it)"
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

  if (confirmingDelete) {
    return (
      <Sidebar.MenuSubItem>
        <div className="flex items-center gap-1 px-1 py-0.5">
          <span className="flex-1 truncate text-sm text-kumo-danger">Delete “{title}”?</span>
          <Button
            variant="outline"
            size="sm"
            shape="square"
            icon={CheckIcon}
            aria-label={`Confirm delete ${title}`}
            title="Confirm delete"
            disabled={busy}
            onClick={() => void confirmDelete()}
          />
          <Button
            variant="outline"
            size="sm"
            shape="square"
            icon={XIcon}
            aria-label="Cancel delete"
            title="Cancel"
            disabled={busy}
            onClick={() => setConfirmingDelete(false)}
          />
        </div>
      </Sidebar.MenuSubItem>
    );
  }

  return (
    <Sidebar.MenuSubItem className="hover:border-kumo-hairline border border-transparent rounded-lg hover:bg-kumo-fill-hover">
      <div className="group flex items-center gap-1 pr-1">
        <Sidebar.MenuSubButton
          onClick={open}
          title={`${title} — ${record.conversationTitle ?? "chat"}`}
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
  );
}

export function NotebookSidebar() {
  const notebooks = useNotebookStore((state) => state.notebooks);
  const fetchNotebooks = useNotebookStore((state) => state.fetchNotebooks);
  const [query, setQuery] = useState("");

  useEffect(() => {
    void fetchNotebooks();
  }, [fetchNotebooks]);

  const needle = query.trim().toLowerCase();
  const visible =
    needle.length === 0
      ? notebooks
      : notebooks.filter((record) => {
          const haystack =
            `${displayTitle(record)} ${record.conversationTitle ?? ""}`.toLowerCase();
          return needle.split(/\s+/).every((word) => haystack.includes(word));
        });

  return (
    <Sidebar.Group>
      <Sidebar.Menu>
        <Sidebar.MenuItem>
          <Sidebar.Collapsible defaultOpen={false}>
            <Sidebar.CollapsibleTrigger
              render={
                <Sidebar.MenuButton icon={NotebookIcon} tooltip="Notebooks">
                  Notebooks <Sidebar.MenuChevron />
                </Sidebar.MenuButton>
              }
            />
            <Sidebar.CollapsibleContent>
              <Sidebar.MenuSub>
                <Sidebar.MenuSubItem>
                  <div className="flex items-center gap-1.5 px-1 py-0.5">
                    <Input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Search notebooks"
                      aria-label="Search notebooks"
                      className="h-8 min-w-0 flex-1 text-sm"
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
                {visible.map((record) => (
                  <NotebookRow key={record.id} record={record} />
                ))}
                {visible.length === 0 && (
                  <Sidebar.MenuSubItem>
                    <span className="block px-2 py-1 text-sm text-kumo-subtle">
                      {notebooks.length === 0
                        ? "No notebooks yet — ask for one in chat."
                        : "No notebooks match."}
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
