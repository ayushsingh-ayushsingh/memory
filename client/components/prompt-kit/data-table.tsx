"use client";

import { Button, DropdownMenu, Input, Pagination, Table } from "@cloudflare/kumo";
import {
  CaretDownIcon,
  CaretUpIcon,
  ColumnsIcon,
  DownloadSimpleIcon,
  MagnifyingGlassIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  type ColumnDef,
  columnFilteringFeature,
  columnVisibilityFeature,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  flexRender,
  globalFilteringFeature,
  rowPaginationFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { type FormEvent, useId, useMemo, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Cell values are coerced to plain strings when rendered, so the
 * interactive table works with any markdown table content.
 */
export type DataTableCellValue = string | number | boolean | null | undefined;

export type DataTableColumn = {
  key: string;
  header?: string;
  align?: "left" | "right" | "center";
  sticky?: "left" | "right";
};

export type DataTableRow = Record<string, DataTableCellValue>;

/** Cells that hold no data: blanks plus the placeholders replies use for them. */
const EMPTY_CELLS = new Set(["", "-", "--", "—", "–", "n/a", "na", "null", "none"]);

const MAGNITUDE_SUFFIX: Record<string, number> = { B: 1e9, K: 1e3, M: 1e6, T: 1e12 };

function isBlankCell(value: DataTableCellValue): boolean {
  if (value === null || value === undefined) return true;
  return typeof value === "string" && EMPTY_CELLS.has(value.trim().toLowerCase());
}

/**
 * Parse a markdown table cell into the number it represents, or null when it
 * is not a number. Handles the shapes reply tables actually contain —
 * thousands separators ("1,234"), currency ("$1.2M"), percentages ("12%"),
 * signed deltas ("+8%", "−0.3%") and parenthesised negatives ("(1,234)") — so
 * a numeric column sorts by value instead of by digit string.
 */
function parseNumericCell(value: DataTableCellValue): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;

  let text = value.trim();
  if (isBlankCell(text)) return null;

  let sign = 1;
  if (text.startsWith("(") && text.endsWith(")")) {
    sign = -1;
    text = text.slice(1, -1).trim();
  }

  text = text
    // Unicode minus/en/em dashes used as minus signs.
    .replace(/[−–—]/g, "-")
    .replace(/^[$€£¥₹]\s*/, "")
    // Thousands separators: "1,234", "1_234".
    .replace(/[,_\u00a0]/g, "")
    .replace(/%$/, "")
    .trim();
  if (text === "") return null;

  // Uppercase magnitude suffix only, so "1.2M" scales while "5m" (minutes)
  // stays text.
  let magnitude = 1;
  const suffix = /([KMBT])$/.exec(text);
  if (suffix) {
    magnitude = MAGNITUDE_SUFFIX[suffix[1]];
    text = text.slice(0, -1).trim();
  }

  const parsed = Number(text);
  return Number.isFinite(parsed) ? sign * parsed * magnitude : null;
}

/**
 * A column sorts numerically when every cell that holds data is a number.
 * Empty cells and placeholders are ignored rather than disqualifying the
 * column; a column of nothing but placeholders stays text.
 */
function isNumericColumn(rows: DataTableRow[], key: string): boolean {
  let sawValue = false;
  for (const row of rows) {
    const value = row[key];
    if (isBlankCell(value)) continue;
    if (parseNumericCell(value) === null) return false;
    sawValue = true;
  }
  return sawValue;
}

function formatCellValue(value: DataTableCellValue): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function exportCsv(rows: DataTableRow[], columns: DataTableColumn[]) {
  const escape = (value: string) => `"${value.replace(/"/g, '""')}"`;
  const header = columns.map((column) => escape(column.header ?? column.key)).join(",");
  const lines = rows.map((row) =>
    columns.map((column) => escape(formatCellValue(row[column.key]))).join(","),
  );
  const csv = [header, ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "table.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

const features = tableFeatures({
  columnFilteringFeature,
  globalFilteringFeature,
  columnVisibilityFeature,
  rowPaginationFeature,
  rowSortingFeature,
  filteredRowModel: createFilteredRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
  sortedRowModel: createSortedRowModel(),
  sortFns: {
    // Natural text order ("Row 2" before "Row 10") for every non-numeric
    // column; numbers in mixed cells still compare by value.
    alphanumeric: sortFn_alphanumeric,
    numeric: (rowA, rowB, columnId) => {
      const a = parseNumericCell(rowA.getValue<DataTableCellValue>(columnId));
      const b = parseNumericCell(rowB.getValue<DataTableCellValue>(columnId));
      if (a === null) return b === null ? 0 : 1;
      if (b === null) return -1;
      return a < b ? -1 : a > b ? 1 : 0;
    },
  },
});

export type DataTableProps = {
  columns: DataTableColumn[];
  rows: DataTableRow[];
  pageSizeOptions?: number[];
  className?: string;
};

type ComputedColumn = {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  sticky?: "left" | "right";
  numeric: boolean;
};

/**
 * Sortable, searchable, paginated table built on TanStack Table and rendered
 * with Kumo primitives. Converts an assistant markdown table into an
 * interactive view once its source has finished streaming: a search bar with
 * an explicit search button, per-column sorting that compares numeric columns
 * by value, a column selector, and a CSV export of the current view.
 */
export function DataTable({
  columns: columnsSpec,
  rows,
  pageSizeOptions = [10, 25, 50],
  className,
}: DataTableProps) {
  const searchId = useId();
  // Draft is what the user is typing; the applied query lives in table state,
  // so results only move on Search / Enter — the button does the searching.
  const [searchDraft, setSearchDraft] = useState("");

  const computedColumns = useMemo<ComputedColumn[]>(
    () =>
      columnsSpec.map((column) => {
        const numeric = isNumericColumn(rows, column.key);
        return {
          key: column.key,
          header: column.header ?? column.key,
          // Numbers right-align by default so digits line up column-wise.
          align: column.align ?? (numeric ? "right" : undefined),
          sticky: column.sticky,
          numeric,
        };
      }),
    [columnsSpec, rows],
  );

  const columnMetaByKey = useMemo(
    () => new Map(computedColumns.map((column) => [column.key, column])),
    [computedColumns],
  );

  const tableColumns = useMemo<ColumnDef<typeof features, DataTableRow>[]>(
    () =>
      computedColumns.map((column) => ({
        accessorKey: column.key,
        id: column.key,
        header: column.header,
        cell: (info) => {
          const formatted = formatCellValue(info.getValue<DataTableCellValue>());
          return (
            <span
              className={cn(
                "block truncate",
                column.align === "right" && "text-right",
                column.align === "center" && "text-center",
              )}
              title={formatted}
            >
              {formatted || "\u2014"}
            </span>
          );
        },
        sortFn: column.numeric ? "numeric" : "alphanumeric",
      })),
    [computedColumns],
  );

  const table = useTable(
    {
      columns: tableColumns,
      data: rows,
      features,
      enableSortingRemoval: false,
      initialState: {
        columnVisibility: {},
        globalFilter: "",
        pagination: {
          pageIndex: 0,
          pageSize: pageSizeOptions[0] ?? 10,
        },
        sorting: columnsSpec[0]?.key ? [{ id: columnsSpec[0].key, desc: false }] : [],
      },
    },
    (state) => ({
      columnVisibility: state.columnVisibility,
      globalFilter: state.globalFilter,
      pagination: state.pagination,
      sorting: state.sorting,
    }),
  );

  const appliedQuery = String(table.state.globalFilter ?? "").trim();
  const hasQuery = appliedQuery.length > 0;
  const { pageIndex, pageSize } = table.state.pagination;
  const totalCount = rows.length;
  const filteredCount = table.getFilteredRowModel().rows.length;
  const visibleRows = table.getRowModel().rows;
  const visibleColumnCount = table.getVisibleLeafColumns().length;
  const allColumnsVisible = table.getIsAllColumnsVisible();

  const applySearch = (event?: FormEvent) => {
    event?.preventDefault();
    table.setGlobalFilter(searchDraft.trim());
    table.setPageIndex(0);
  };

  const clearSearch = () => {
    setSearchDraft("");
    table.setGlobalFilter("");
    table.setPageIndex(0);
  };

  const handleSort = (columnId: string) => {
    const column = table.getColumn(columnId);
    if (!column) return;
    // Two-state cycle: ascending on the first click, then descending.
    column.toggleSorting(column.getIsSorted() === "asc");
  };

  const handleExport = () => {
    const visibleKeys = new Set(table.getVisibleLeafColumns().map((column) => column.id));
    exportCsv(
      table.getSortedRowModel().rows.map((row) => row.original),
      computedColumns.filter((column) => visibleKeys.has(column.key)),
    );
  };

  return (
    <div
      className={cn(
        "my-4 overflow-hidden rounded-lg bg-kumo-base ring ring-kumo-line first:mt-0 last:mb-0",
        className,
      )}
    >
      {/* Toolbar: search + row summary + column selector + CSV export */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-kumo-hairline bg-kumo-base p-2.5">
        {/* <search> keeps the query field an accessible search landmark while
            the form gives Enter / the button their submit semantics. */}
        <search className="flex w-full min-w-0 items-center gap-1.5 sm:max-w-80">
          <form className="flex min-w-0 flex-1 items-center gap-1.5" onSubmit={applySearch}>
            <div className="relative min-w-0 flex-1">
              <MagnifyingGlassIcon
                aria-hidden
                className="pointer-events-none absolute inset-y-0 start-2.5 m-auto text-kumo-subtle"
                size={14}
              />
              <Input
                id={searchId}
                aria-label="Search rows"
                className="ps-8"
                placeholder="Search rows..."
                size="sm"
                value={searchDraft}
                onValueChange={(value) => setSearchDraft(value ?? "")}
              />
              {(searchDraft.length > 0 || hasQuery) && (
                <Button
                  variant="ghost"
                  shape="square"
                  size="xs"
                  icon={XIcon}
                  aria-label="Clear search"
                  className="absolute inset-y-0 end-1.5 m-auto"
                  onClick={clearSearch}
                />
              )}
            </div>
            <Button variant="secondary" size="sm" type="submit">
              Search
            </Button>
          </form>
        </search>

        <div className="flex items-center gap-2">
          <span aria-live="polite" className="text-xs text-kumo-subtle tabular-nums">
            {hasQuery
              ? `${filteredCount} of ${totalCount} rows`
              : `${totalCount} ${totalCount === 1 ? "row" : "rows"}`}
          </span>
          <DropdownMenu>
            <DropdownMenu.Trigger
              render={
                <Button
                  variant="secondary"
                  size="sm"
                  icon={ColumnsIcon}
                  aria-label="Select columns"
                >
                  Columns
                </Button>
              }
            />
            <DropdownMenu.Content align="end">
              <DropdownMenu.Group>
                <DropdownMenu.Label>Columns</DropdownMenu.Label>
                {table.getAllLeafColumns().map((column) => {
                  const visible = column.getIsVisible();
                  // Hiding the last visible column would leave an empty table.
                  const isLastVisible = visible && visibleColumnCount <= 1;
                  return (
                    <DropdownMenu.CheckboxItem
                      key={column.id}
                      checked={visible}
                      disabled={isLastVisible}
                      onCheckedChange={(checked) => column.toggleVisibility(checked)}
                    >
                      {columnMetaByKey.get(column.id)?.header ?? column.id}
                    </DropdownMenu.CheckboxItem>
                  );
                })}
              </DropdownMenu.Group>
              <DropdownMenu.Separator />
              <DropdownMenu.Item
                disabled={allColumnsVisible}
                onClick={() => table.toggleAllColumnsVisible(true)}
              >
                Show all
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu>
          <Button
            variant="secondary"
            size="sm"
            icon={DownloadSimpleIcon}
            disabled={visibleRows.length === 0}
            onClick={handleExport}
          >
            CSV
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="scrollbar-on-hover overflow-x-auto">
        <Table layout="auto">
          <Table.Header variant="compact" sticky>
            {table.getHeaderGroups().map((headerGroup) => (
              <Table.Row key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const columnId = header.column.id;
                  const meta = columnMetaByKey.get(columnId);
                  const align = meta?.align;
                  const isSorted = header.column.getIsSorted();
                  return (
                    <Table.Head
                      key={header.id}
                      sticky={meta?.sticky}
                      aria-sort={
                        isSorted === "asc"
                          ? "ascending"
                          : isSorted === "desc"
                            ? "descending"
                            : undefined
                      }
                    >
                      <button
                        type="button"
                        onClick={() => handleSort(columnId)}
                        className={cn(
                          "flex w-full cursor-pointer select-none items-center gap-1 rounded-sm px-1 py-0.5 text-left text-xs font-medium text-kumo-strong outline-none hover:text-kumo-default focus-visible:ring-2 focus-visible:ring-kumo-focus/50",
                          align === "right" && "justify-end",
                          align === "center" && "justify-center",
                        )}
                      >
                        <span className="truncate">
                          {flexRender(header.column.columnDef.header, header.getContext())}
                        </span>
                        {isSorted === "asc" ? (
                          <CaretUpIcon className="shrink-0 text-kumo-subtle" size={12} />
                        ) : isSorted === "desc" ? (
                          <CaretDownIcon className="shrink-0 text-kumo-subtle" size={12} />
                        ) : null}
                      </button>
                    </Table.Head>
                  );
                })}
              </Table.Row>
            ))}
          </Table.Header>
          <Table.Body>
            {visibleRows.length > 0 ? (
              visibleRows.map((row) => (
                <Table.Row key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <Table.Cell
                      key={cell.id}
                      sticky={columnMetaByKey.get(cell.column.id)?.sticky}
                      className="max-w-64"
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </Table.Cell>
                  ))}
                </Table.Row>
              ))
            ) : (
              <Table.Row>
                <Table.Cell
                  className="py-8 text-center text-sm text-kumo-subtle"
                  colSpan={Math.max(visibleColumnCount, 1)}
                >
                  {hasQuery ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span>No rows match “{appliedQuery}”.</span>
                      <Button variant="ghost" size="xs" onClick={clearSearch}>
                        Clear search
                      </Button>
                    </span>
                  ) : (
                    "No results found."
                  )}
                </Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table>
      </div>

      {/* Footer: pagination */}
      {filteredCount > 0 && (
        <div className="border-t border-kumo-hairline bg-kumo-base px-2.5 py-2">
          <Pagination
            page={pageIndex + 1}
            setPage={(page) => table.setPageIndex(page - 1)}
            perPage={pageSize}
            totalCount={filteredCount}
          >
            <Pagination.Info>
              {({ pageShowingRange, totalCount: shownTotal }) => (
                <>
                  Showing <span className="tabular-nums">{pageShowingRange}</span> of{" "}
                  <span className="tabular-nums">{shownTotal}</span>
                </>
              )}
            </Pagination.Info>
            <Pagination.Separator />
            <Pagination.PageSize
              value={pageSize}
              onChange={(size) => table.setPageSize(size)}
              options={pageSizeOptions}
            />
            <Pagination.Controls />
          </Pagination>
        </div>
      )}
    </div>
  );
}
