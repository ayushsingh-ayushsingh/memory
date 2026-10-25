"use client";

import { cn } from "@/lib/utils";

export type TextShimmerProps = {
  as?: string;
  duration?: number;
  spread?: number;
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLElement>;

export function TextShimmer({
  as = "span",
  className,
  duration = 4,
  spread = 20,
  children,
  ...props
}: TextShimmerProps) {
  const dynamicSpread = Math.min(Math.max(spread, 5), 45);
  const Component = as as React.ElementType;

  return (
    <Component
      role="status"
      aria-live="polite"
      className={cn(
        "bg-size-[200%_auto] bg-clip-text font-medium text-transparent motion-reduce:animate-none",
        "animate-[shimmer_4s_infinite_linear]",
        className,
      )}
      style={{
        backgroundImage: `linear-gradient(to right, var(--kumo-subtle) ${50 - dynamicSpread}%, var(--kumo-default) 50%, var(--kumo-subtle) ${50 + dynamicSpread}%)`,
        animationDuration: `${duration}s`,
      }}
      {...props}
    >
      {children}
    </Component>
  );
}
