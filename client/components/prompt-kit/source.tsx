"use client";

import { Badge, LayerCard, Popover } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import NextImage from "next/image";
import { createContext, useContext } from "react";

const SourceContext = createContext<{
  href: string;
  domain: string;
} | null>(null);

function useSourceContext() {
  const ctx = useContext(SourceContext);
  if (!ctx) throw new Error("Source.* must be used inside <Source>");
  return ctx;
}

export type SourceProps = {
  href: string;
  children: React.ReactNode;
};

export function Source({ href, children }: SourceProps) {
  let domain = "";
  try {
    domain = new URL(href).hostname;
  } catch {
    domain = href.split("/").pop() || href;
  }

  return (
    <SourceContext.Provider value={{ href, domain }}>
      <Popover>{children}</Popover>
    </SourceContext.Provider>
  );
}

export type SourceTriggerProps = {
  label?: string | number;
  showFavicon?: boolean;
  className?: string;
};

export function SourceTrigger({ label, showFavicon = false, className }: SourceTriggerProps) {
  const { href, domain } = useSourceContext();
  const labelToShow = label ?? domain.replace("www.", "");

  return (
    <Popover.Trigger
      render={
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`${labelToShow} (opens in new tab)`}
          className={cn(
            "inline-flex h-5 max-w-32 items-center gap-1 overflow-hidden rounded-full bg-kumo-tint py-0 text-xs text-kumo-subtle no-underline hover:text-kumo-default",
            showFavicon ? "pr-2 pl-1" : "px-1",
            className,
          )}
        >
          {showFavicon && (
            <NextImage
              src={`https://www.google.com/s2/favicons?sz=64&domain_url=${encodeURIComponent(
                href,
              )}`}
              alt=""
              aria-hidden
              width={14}
              height={14}
              unoptimized
              className="size-3.5 rounded-full"
            />
          )}
          <span className="truncate tabular-nums text-center font-normal">{labelToShow}</span>
        </a>
      }
    />
  );
}

export type SourceContentProps = {
  title: string;
  description: string;
  className?: string;
};

export function SourceContent({ title, description, className }: SourceContentProps) {
  const { href, domain } = useSourceContext();

  return (
    <Popover.Content className={cn("w-80", className)}>
      <LayerCard className="p-0">
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`${title} (opens in new tab)`}
          className="flex flex-col gap-2 p-3"
        >
          <div className="flex items-center gap-1.5">
            <NextImage
              src={`https://www.google.com/s2/favicons?sz=64&domain_url=${encodeURIComponent(
                href,
              )}`}
              alt=""
              aria-hidden
              className="size-4 rounded-full"
              width={16}
              height={16}
              unoptimized
            />
            <div className="truncate text-sm text-kumo-default">{domain.replace("www.", "")}</div>
          </div>
          <Badge variant="secondary" className="self-start">
            Source
          </Badge>
          <div className="line-clamp-2 text-sm font-medium text-kumo-strong">{title}</div>
          <div className="line-clamp-2 text-sm text-kumo-subtle">{description}</div>
        </a>
      </LayerCard>
    </Popover.Content>
  );
}
