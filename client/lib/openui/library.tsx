/**
 * The OpenUI component library the model builds its replies from.
 *
 * This file is the single source of truth for the generated UI: `pnpm openui:generate`
 * (see package.json) reads it, writes the system prompt the Python agent runs on
 * (`lib/openui/generated/system-prompt.txt`) and the serialized spec next to it.
 *
 * Everything renders with Kumo (the app's design system) or Evil Charts (charts),
 * so generated interfaces look native to the chat app, follow `[data-mode]`
 * light/dark, and reuse the same semantic tokens as the hand-written UI.
 *
 * Component design notes (per OpenUI's LLM guidance):
 * - schemas stay flat — required props first, optionals last, since arguments
 *   are positional;
 * - each component maps to exactly one visual idea;
 * - `Chart` takes plain `categories` + `series` so the model never has to write
 *   engine-specific options.
 */
import { createLibrary, defineComponent, type PromptOptions } from "@openuidev/react-lang";
import { Badge, Banner, LayerCard, Meter, Text } from "@cloudflare/kumo";
import { CheckCircleIcon, InfoIcon, WarningIcon, XCircleIcon } from "@phosphor-icons/react";
import { z } from "zod/v4";

import { DataTable, type DataTableColumn, type DataTableRow } from "@/components/prompt-kit/data-table";
import { GeneratedChart } from "./chart";

const tone = z.enum(["neutral", "info", "success", "warning", "danger"]);

/** A value the model may write as a string or a bare number. */
const scalar = z.union([z.string(), z.number()]);

// ─────────────────────────────────────────────────────────────────────────────
// Leaf components
// ─────────────────────────────────────────────────────────────────────────────

const Heading = defineComponent({
  name: "Heading",
  description:
    "Section title for the answer. Use once at the top of a program, not for every line.",
  props: z.object({ text: z.string() }),
  component: ({ props }) => (
    <Text as="h3" size="lg" variant="heading">
      {props.text}
    </Text>
  ),
});

const TextBlock = defineComponent({
  name: "Text",
  description:
    "A short paragraph of prose. Plain sentences only — no markdown, no headings, no lists.",
  props: z.object({
    content: z.string(),
    tone: z.enum(["default", "subtle", "success", "error"]).optional(),
  }),
  component: ({ props }) => (
    <Text
      variant={
        props.tone === "subtle"
          ? "secondary"
          : props.tone === "success"
            ? "success"
            : props.tone === "error"
              ? "error"
              : "body"
      }
    >
      {props.content}
    </Text>
  ),
});

const List = defineComponent({
  name: "List",
  description: "Bulleted list of short items, one per line.",
  props: z.object({ items: z.array(z.string()) }),
  component: ({ props }) => (
    <ul className="flex flex-col gap-1.5">
      {props.items.map((item, index) => (
        <li className="flex min-w-0 gap-2" key={`${index}-${item}`}>
          <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-kumo-fill" />
          <Text as="span">{item}</Text>
        </li>
      ))}
    </ul>
  ),
});

const Metric = defineComponent({
  name: "Metric",
  description:
    "One key number with its label and an optional change note. Group several in a Stack row for a KPI strip.",
  props: z.object({
    label: z.string(),
    value: scalar,
    hint: z.string().optional(),
  }),
  component: ({ props }) => (
    <div className="flex min-w-0 flex-1 basis-40 flex-col gap-1 rounded-lg border border-kumo-hairline bg-kumo-base p-3">
      <Text size="sm" variant="secondary">
        {props.label}
      </Text>
      <Text as="span" size="lg" variant="heading">
        {String(props.value)}
      </Text>
      {props.hint ? (
        <Text size="xs" variant="secondary">
          {props.hint}
        </Text>
      ) : null}
    </div>
  ),
});

const BadgeBlock = defineComponent({
  name: "Badge",
  description: "Small status label, for example next to a heading or inside a table cell.",
  props: z.object({ label: z.string(), tone: tone.optional() }),
  component: ({ props }) => (
    <Badge
      variant={
        props.tone === "info"
          ? "info"
          : props.tone === "success"
            ? "success"
            : props.tone === "warning"
              ? "warning"
              : props.tone === "danger"
                ? "error"
                : "secondary"
      }
    >
      {props.label}
    </Badge>
  ),
});

const Callout = defineComponent({
  name: "Callout",
  description: "Highlighted note for a warning, an error, a success or a tip.",
  props: z.object({
    title: z.string(),
    body: z.string().optional(),
    tone: tone.optional(),
  }),
  component: ({ props }) => {
    const icons = {
      danger: XCircleIcon,
      info: InfoIcon,
      neutral: InfoIcon,
      success: CheckCircleIcon,
      warning: WarningIcon,
    } as const;
    const Icon = icons[props.tone ?? "info"];
    return (
      <Banner
        description={props.body}
        icon={<Icon weight="fill" />}
        title={props.title}
        variant={
          props.tone === "danger"
            ? "error"
            : props.tone === "warning"
              ? "alert"
              : props.tone === "success"
                ? "secondary"
                : "default"
        }
      />
    );
  },
});

const Progress = defineComponent({
  name: "Progress",
  description:
    "A single value against a maximum, drawn as a progress bar. Use `value` with a percentage `max` (default 100).",
  props: z.object({
    label: z.string(),
    value: z.number(),
    max: z.number().optional(),
    customValue: z.string().optional(),
  }),
  component: ({ props }) => (
    <Meter
      customValue={props.customValue}
      label={props.label}
      max={props.max}
      value={props.value}
    />
  ),
});

const Code = defineComponent({
  name: "Code",
  description:
    "A code or command block, shown verbatim in monospace. Use for short snippets only; Python programs belong in a marimo notebook instead.",
  props: z.object({ content: z.string() }),
  component: ({ props }) => (
    <pre className="max-w-full overflow-x-auto rounded-lg border border-kumo-hairline bg-kumo-tint p-3">
      <Text as="code" size="lg" variant="mono">
        {props.content}
      </Text>
    </pre>
  ),
});

const TableBlock = defineComponent({
  name: "Table",
  description:
    "Rows and columns of values, for comparisons and lists of records. `rows` are strings or numbers, in the same order as `columns`.",
  props: z.object({
    columns: z.array(z.string()),
    rows: z.array(z.array(scalar)),
  }),
  component: ({ props }) => {
    // Hand the generated grid to the same interactive DataTable the markdown
    // renderer uses: a search bar with an explicit Search button, per-column
    // sorting that compares numeric columns by value (not digit string), a
    // column selector, and pagination. This also makes the table robust to
    // ragged rows and duplicate headers the model sometimes emits — the old
    // positional Kumo table could misalign (or a Chart-style mismatch throw)
    // when a row length didn't match `columns`.
    const seen = new Map<string, number>();
    const keys = props.columns.map((column) => {
      const count = seen.get(column) ?? 0;
      seen.set(column, count + 1);
      return count === 0 ? column : `${column}_${count}`;
    });
    const columns: DataTableColumn[] = props.columns.map((header, index) => ({
      key: keys[index],
      header,
    }));
    const rows: DataTableRow[] = props.rows.map((cells) => {
      const row: DataTableRow = {};
      keys.forEach((key, index) => {
        row[key] = cells[index] ?? null;
      });
      return row;
    });
    return <DataTable columns={columns} rows={rows} />;
  },
});

const Chart = defineComponent({
  name: "Chart",
  description:
    "An animated chart. `categories` are the x labels (or the slices of a pie) and each series holds one value per category, in the same order.",
  props: z.object({
    kind: z.enum(["area", "bar", "line", "pie"]),
    categories: z.array(z.string()),
    series: z.array(z.object({ name: z.string(), values: z.array(z.number()) })),
    title: z.string().optional(),
  }),
  component: ({ props }) => (
    <GeneratedChart
      categories={props.categories}
      kind={props.kind}
      series={props.series}
      title={props.title}
    />
  ),
});

// ─────────────────────────────────────────────────────────────────────────────
// Containers — defined after the leaves so their child unions can use `.ref`
// ─────────────────────────────────────────────────────────────────────────────

const contentNodes = [
  Heading.ref,
  TextBlock.ref,
  List.ref,
  Metric.ref,
  BadgeBlock.ref,
  Callout.ref,
  Progress.ref,
  Code.ref,
  TableBlock.ref,
  Chart.ref,
] as const;

const Card = defineComponent({
  name: "Card",
  description: "A titled card that groups a few components of the answer together.",
  props: z.object({
    title: z.string(),
    items: z.array(z.union(contentNodes)),
  }),
  component: ({ props, renderNode }) => (
    <LayerCard className="w-full">
      <LayerCard.Secondary>{props.title}</LayerCard.Secondary>
      <LayerCard.Primary>
        <div className="flex flex-col gap-3">{renderNode(props.items)}</div>
      </LayerCard.Primary>
    </LayerCard>
  ),
});

const Stack = defineComponent({
  name: "Stack",
  description:
    "Root container. Stacks its items vertically (default) or in a wrapping row. Every program starts with `root = Stack([...])`.",
  props: z.object({
    items: z.array(z.union([...contentNodes, Card.ref])),
    direction: z.enum(["column", "row"]).optional(),
  }),
  component: ({ props, renderNode }) => (
    <div
      className={
        props.direction === "row"
          ? "flex w-full min-w-0 flex-row flex-wrap items-stretch gap-3"
          : "flex w-full min-w-0 flex-col gap-3"
      }
    >
      {renderNode(props.items)}
    </div>
  ),
});

// ─────────────────────────────────────────────────────────────────────────────

export const library = createLibrary({
  componentGroups: [
    {
      components: ["Stack", "Card"],
      name: "Layout",
      notes: [
        '- Stack is the root of every program. Use direction "row" for a strip of Metric components — it wraps on narrow screens.',
        "- Neither Stack nor Card may contain another Stack or Card inside; nest content, not layout.",
      ],
    },
    {
      components: ["Heading", "Text", "List", "Metric", "Badge", "Callout", "Code"],
      name: "Content",
      notes: [
        "- Keep prose short and use the components instead of markdown.",
        "- A row of Metric components answers “what are the numbers?” faster than a paragraph.",
      ],
    },
    {
      components: ["Table", "Progress", "Chart"],
      name: "Data",
      notes: [
        "- Table for exact values, Chart for shape over time (area, line, bar) or parts of a whole (pie).",
        "- Chart: every series needs exactly one value per category. Use a single series for pie.",
        "- Do not put a chart inside a row — charts need the full width.",
      ],
    },
  ],
  components: [
    Stack,
    Card,
    Heading,
    TextBlock,
    List,
    Metric,
    BadgeBlock,
    Callout,
    Progress,
    Code,
    TableBlock,
    Chart,
  ],
  id: "chat-app-ui",
  root: "Stack",
});

/**
 * Tuned for this app: replies render inline in the conversation (there is no
 * separate canvas to edit), and the existing marimo notebook path stays
 * available for runnable Python.
 */
export const promptOptions: PromptOptions = {
  additionalRules: [
    "Answer with the smallest interface that fully answers the request. A short answer is one Text or a small Stack — never pad a simple reply into a dashboard.",
    "Never write markdown inside strings (no **, #, -, |, `): use Heading, List, Table and Code components instead.",
    "Use the real numbers from the user's request, this conversation or the results of your tools. If you have to illustrate instead, say so in a Text or Callout component.",
    "EXCEPTION — runnable Python: when the user asks for a Python program, a computation or a notebook, reply with a single ```python marimo fenced block and no openui-lang. The app renders those notebooks in its notebook panel. Never mix a Python fence into an openui-lang program.",
  ],
  examples: [
    `root = Stack([title, stats, trend])
title = Heading("Workers traffic — last 7 days")
stats = Stack([requests, errors], "row")
requests = Metric("Requests", "1.24M", "+6.1% vs last week")
errors = Metric("Error rate", "0.42%", "-0.08% vs last week")
trend = Card("Requests per day", [chart])
chart = Chart("area", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], [series], "Requests")
series = {name: "Requests", values: [180000, 210000, 195000, 240000, 236000, 171000, 168000]}`,
    `root = Stack([answer, plan, limits])
answer = Text("Vite+ runs the whole toolchain: vp check, vp test, vp build.")
plan = Card("Migration steps", [steps])
steps = List(["Install the toolchain", "Run vp migrate", "Fix the reported findings"])
limits = Callout("Heads up", "vp build is a Vite build — Next.js apps still build with vp run build.", "warning")`,
  ],
  preamble:
    "You are the assistant of a chat app that renders your reply as an interface instead of plain markdown. The app draws the program inline in the conversation, right after the user's message.",
};
