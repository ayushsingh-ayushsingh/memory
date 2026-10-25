"use client";

import { Button } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import { CaretDownIcon } from "@phosphor-icons/react";
import { useStickToBottomContext } from "use-stick-to-bottom";

export type ScrollButtonProps = {
  className?: string;
  variant?: "primary" | "secondary" | "ghost" | "outline" | "destructive";
  size?: "xs" | "sm" | "base" | "lg";
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

function ScrollButton({
  className,
  variant = "secondary",
  size = "sm",
  ...props
}: ScrollButtonProps) {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();
  const hidden = isAtBottom;

  return (
    <Button
      variant={variant}
      size={size}
      shape="circle"
      icon={CaretDownIcon}
      aria-label="Scroll to bottom"
      title="Scroll to bottom"
      aria-hidden={hidden || undefined}
      tabIndex={hidden ? -1 : undefined}
      className={cn(
        "shadow-md ring ring-kumo-line transition-transform duration-150 ease-out",
        !hidden
          ? "translate-y-0 scale-100 opacity-100"
          : "pointer-events-none translate-y-4 scale-95 opacity-0",
        className,
      )}
      onClick={() => scrollToBottom()}
      {...props}
    />
  );
}

export { ScrollButton };
