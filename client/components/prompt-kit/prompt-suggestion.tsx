"use client";

import { Button } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";

export type PromptSuggestionProps = {
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "outline" | "destructive";
  size?: "xs" | "sm" | "base" | "lg";
  className?: string;
  highlight?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

function PromptSuggestion({
  children,
  variant,
  size,
  className,
  highlight,
  ...props
}: PromptSuggestionProps) {
  const isHighlightMode = highlight !== undefined && highlight.trim() !== "";
  const content = typeof children === "string" ? children : "";

  if (!isHighlightMode) {
    return (
      <Button
        variant={variant || "outline"}
        size={size || "lg"}
        className={cn("rounded-full", className)}
        {...props}
      >
        {children}
      </Button>
    );
  }

  if (!content) {
    return (
      <Button
        variant={variant || "ghost"}
        size={size || "sm"}
        className={cn(
          "w-full cursor-pointer justify-start rounded-xl py-2 hover:bg-kumo-tint",
          className,
        )}
        {...props}
      >
        {children}
      </Button>
    );
  }

  const trimmedHighlight = highlight.trim();
  const contentLower = content.toLowerCase();
  const highlightLower = trimmedHighlight.toLowerCase();
  const shouldHighlight = contentLower.includes(highlightLower);

  return (
    <Button
      variant={variant || "ghost"}
      size={size || "sm"}
      className={cn(
        "w-full cursor-pointer justify-start gap-0 rounded-xl py-2 hover:bg-kumo-tint",
        className,
      )}
      {...props}
    >
      {shouldHighlight ? (
        (() => {
          const index = contentLower.indexOf(highlightLower);
          if (index === -1)
            return <span className="whitespace-pre-wrap text-kumo-subtle">{content}</span>;

          const actualHighlightedText = content.substring(index, index + highlightLower.length);

          const before = content.substring(0, index);
          const after = content.substring(index + actualHighlightedText.length);

          return (
            <>
              {before && <span className="whitespace-pre-wrap text-kumo-subtle">{before}</span>}
              <span className="font-medium whitespace-pre-wrap text-kumo-strong">
                {actualHighlightedText}
              </span>
              {after && <span className="whitespace-pre-wrap text-kumo-subtle">{after}</span>}
            </>
          );
        })()
      ) : (
        <span className="whitespace-pre-wrap text-kumo-subtle">{content}</span>
      )}
    </Button>
  );
}

export { PromptSuggestion };
