"use client";

import { cn } from "@/lib/utils";
import { CaretDownIcon } from "@phosphor-icons/react";
import React, { createContext, useContext, useEffect, useId, useRef, useState } from "react";
import { Markdown } from "./markdown";

type ReasoningContextType = {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  isStreaming?: boolean;
};

const ReasoningContext = createContext<ReasoningContextType | undefined>(undefined);

function useReasoningContext() {
  const context = useContext(ReasoningContext);
  if (!context) {
    throw new Error("useReasoningContext must be used within a Reasoning provider");
  }
  return context;
}

export type ReasoningProps = {
  children: React.ReactNode;
  className?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  isStreaming?: boolean;
};
function Reasoning({ children, className, open, onOpenChange, isStreaming }: ReasoningProps) {
  const [internalOpen, setInternalOpen] = useState(false);

  const isControlled = open !== undefined;
  const isOpen = isControlled ? open : internalOpen;

  const [prevIsStreaming, setPrevIsStreaming] = useState(isStreaming);
  if (isStreaming !== prevIsStreaming) {
    setPrevIsStreaming(isStreaming);
    if (!isControlled) {
      setInternalOpen(Boolean(isStreaming));
    }
  }

  const handleOpenChange = (newOpen: boolean) => {
    if (!isControlled) {
      setInternalOpen(newOpen);
    }
    onOpenChange?.(newOpen);
  };

  return (
    <ReasoningContext.Provider
      value={{
        isOpen,
        onOpenChange: handleOpenChange,
        isStreaming,
      }}
    >
      <div className={className}>{children}</div>
    </ReasoningContext.Provider>
  );
}

export type ReasoningTriggerProps = {
  children: React.ReactNode;
  className?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

function ReasoningTrigger({ children, className, id, ...props }: ReasoningTriggerProps) {
  const { isOpen, onOpenChange } = useReasoningContext();
  const fallbackId = useId();
  const controlsId = props["aria-controls"] ?? `reasoning-${fallbackId}`;

  return (
    <button
      type="button"
      id={id}
      aria-expanded={isOpen}
      aria-controls={controlsId}
      className={cn("flex cursor-pointer items-center gap-2", className)}
      onClick={() => onOpenChange(!isOpen)}
      {...props}
    >
      <span className="text-sm text-kumo-default">{children}</span>
      <span className="h-lh flex items-center">
        <span className={cn("flex transition-transform", isOpen ? "rotate-180" : "")}>
          <CaretDownIcon className="size-4 text-kumo-subtle" aria-hidden />
        </span>
      </span>
    </button>
  );
}

export type ReasoningContentProps = {
  children: React.ReactNode;
  className?: string;
  markdown?: boolean;
  contentClassName?: string;
} & React.HTMLAttributes<HTMLDivElement>;

function ReasoningContent({
  children,
  className,
  contentClassName,
  markdown = false,
  ...props
}: ReasoningContentProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const { isOpen, isStreaming } = useReasoningContext();
  useEffect(() => {
    if (!contentRef.current || !innerRef.current) return;

    const observer = new ResizeObserver(() => {
      if (contentRef.current && innerRef.current && isOpen) {
        contentRef.current.style.maxHeight = `${innerRef.current.scrollHeight}px`;
      }
    });

    observer.observe(innerRef.current);

    contentRef.current.style.maxHeight = isOpen ? `${innerRef.current.scrollHeight}px` : "0px";

    return () => observer.disconnect();
  }, [isOpen]);

  const content = markdown ? (
    <Markdown isStreaming={isStreaming}>{children as string}</Markdown>
  ) : (
    children
  );

  return (
    <div
      ref={contentRef}
      role="region"
      className={cn("overflow-hidden transition-[max-height] duration-150 ease-out", className)}
      {...props}
    >
      <div ref={innerRef} className={cn("text-sm text-kumo-subtle", contentClassName)}>
        {content}
      </div>
    </div>
  );
}

export { Reasoning, ReasoningTrigger, ReasoningContent };
