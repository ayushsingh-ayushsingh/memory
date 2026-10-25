"use client";

import { Badge, Banner, Collapsible, LayerCard } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import {
  CaretDownIcon,
  CheckCircleIcon,
  GearIcon,
  SpinnerGapIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import { useState } from "react";

export type ToolPart = {
  type: string;
  state: "input-streaming" | "input-available" | "output-available" | "output-error";
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  toolCallId?: string;
  errorText?: string;
};

export type ToolProps = {
  toolPart: ToolPart;
  defaultOpen?: boolean;
  className?: string;
};

const Tool = ({ toolPart, defaultOpen = false, className }: ToolProps) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const { state, input, output, toolCallId } = toolPart;

  const getStateIcon = () => {
    switch (state) {
      case "input-streaming":
        return <SpinnerGapIcon aria-hidden className="size-4 animate-spin fill-kumo-info" />;
      case "input-available":
        return <GearIcon aria-hidden className="size-4 fill-kumo-warning" />;
      case "output-available":
        return <CheckCircleIcon aria-hidden className="size-4 fill-kumo-success" weight="fill" />;
      case "output-error":
        return <XCircleIcon aria-hidden className="size-4 fill-kumo-danger" weight="fill" />;
      default:
        return <GearIcon aria-hidden className="size-4 fill-kumo-subtle" />;
    }
  };

  const getStateBadge = () => {
    switch (state) {
      case "input-streaming":
        return <Badge variant="info">Processing</Badge>;
      case "input-available":
        return <Badge variant="warning">Ready</Badge>;
      case "output-available":
        return <Badge variant="success">Completed</Badge>;
      case "output-error":
        return <Badge variant="error">Error</Badge>;
      default:
        return <Badge variant="secondary">Pending</Badge>;
    }
  };

  const formatValue = (value: unknown): string => {
    if (value === null) return "null";
    if (value === undefined) return "undefined";
    if (typeof value === "string") return value;
    if (typeof value === "object") {
      return JSON.stringify(value, null, 2);
    }
    return String(value);
  };

  return (
    <LayerCard className={cn("mt-3 overflow-hidden", className)}>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <Collapsible.Trigger
          aria-expanded={isOpen}
          className="flex h-auto w-full items-center justify-between rounded-b-none bg-kumo-base px-5 py-2 text-left"
        >
          <span className="flex items-center gap-2">
            <span className="h-lh flex items-center">{getStateIcon()}</span>
            <span className="font-mono text-sm font-medium text-[0.9em] text-kumo-default">
              {toolPart.type}
            </span>
            {getStateBadge()}
          </span>
          <CaretDownIcon
            aria-hidden
            className={cn("size-4 text-kumo-subtle transition-transform", isOpen && "rotate-180")}
          />
        </Collapsible.Trigger>
        <Collapsible.Panel className="overflow-hidden border-t border-kumo-hairline">
          <div className="space-y-3 bg-kumo-base p-3">
            {input && Object.keys(input).length > 0 && (
              <div>
                <h4 className="mb-2 text-sm font-medium text-kumo-subtle">Input</h4>
                <div className="rounded-lg border border-kumo-hairline bg-kumo-recessed p-2 font-mono text-sm text-[0.9em] text-kumo-default">
                  {Object.entries(input).map(([key, value]) => (
                    <div key={key} className="mb-1">
                      <span className="text-kumo-subtle">{key}:</span>{" "}
                      <span>{formatValue(value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {output && (
              <div>
                <h4 className="mb-2 text-sm font-medium text-kumo-subtle">Output</h4>
                <div className="scrollbar-on-hover max-h-60 overflow-auto rounded-lg border border-kumo-hairline bg-kumo-recessed p-2 font-mono text-sm text-[0.9em] text-kumo-default">
                  <pre className="whitespace-pre-wrap">{formatValue(output)}</pre>
                </div>
              </div>
            )}

            {state === "output-error" && toolPart.errorText && (
              <Banner variant="error" title="Error" description={toolPart.errorText} />
            )}

            {state === "input-streaming" && (
              <div role="status" aria-live="polite" className="text-sm text-kumo-subtle">
                Processing tool call...
              </div>
            )}

            {toolCallId && (
              <div className="border-t border-kumo-hairline pt-2 text-xs text-kumo-subtle">
                <span className="font-mono text-[0.9em]">Call ID: {toolCallId}</span>
              </div>
            )}
          </div>
        </Collapsible.Panel>
      </Collapsible>
    </LayerCard>
  );
};

export { Tool };
