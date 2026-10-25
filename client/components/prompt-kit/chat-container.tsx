"use client";

import { cn } from "@/lib/utils";
import { StickToBottom } from "use-stick-to-bottom";

export type ChatContainerRootProps = {
  children: React.ReactNode;
  className?: string;
} & React.HTMLAttributes<HTMLDivElement>;

export type ChatContainerContentProps = {
  children: React.ReactNode;
  className?: string;
} & React.HTMLAttributes<HTMLDivElement>;

export type ChatContainerScrollAnchorProps = {
  className?: string;
  ref?: React.RefObject<HTMLDivElement>;
} & React.HTMLAttributes<HTMLDivElement>;

function ChatContainerRoot({ children, className, ...props }: ChatContainerRootProps) {
  return (
    <StickToBottom
      className={cn("flex overflow-y-auto bg-kumo-base", className)}
      // "instant" (not "smooth"): during streaming the content grows dozens
      // of times per second. Smooth-animating every growth queues overlapping
      // scroll animations that fight the user's wheel and make scrolling feel
      // stuck while the AI is responding.
      resize="instant"
      initial="instant"
      role="log"
      aria-label="Chat messages"
      aria-live="off"
      {...props}
    >
      {children}
    </StickToBottom>
  );
}

function ChatContainerContent({ children, className, ...props }: ChatContainerContentProps) {
  return (
    <StickToBottom.Content className={cn("flex w-full flex-col", className)} {...props}>
      {children}
    </StickToBottom.Content>
  );
}

function ChatContainerScrollAnchor({ className, ...props }: ChatContainerScrollAnchorProps) {
  return (
    <div
      className={cn("h-px w-full shrink-0 scroll-mt-4", className)}
      aria-hidden="true"
      {...props}
    />
  );
}

export { ChatContainerRoot, ChatContainerContent, ChatContainerScrollAnchor };
