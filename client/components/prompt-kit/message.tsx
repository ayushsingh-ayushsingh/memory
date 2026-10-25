import { Tooltip } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import { Markdown } from "./markdown";
import { ReactElement } from "react";

export type MessageProps = {
  children: React.ReactNode;
  className?: string;
} & React.HTMLProps<HTMLDivElement>;

const Message = ({ children, className, ...props }: MessageProps) => (
  <div className={cn("flex gap-3", className)} {...props}>
    {children}
  </div>
);

export type MessageAvatarProps = {
  src: string;
  alt: string;
  fallback?: string;
  delayMs?: number;
  className?: string;
};

const MessageAvatar = ({ src, alt, fallback, className }: MessageAvatarProps) => {
  return (
    <span
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-kumo-tint text-sm font-medium text-kumo-default ring ring-kumo-line",
        className,
      )}
      role="img"
      aria-label={alt}
    >
      {src ? (
        // oxlint-disable-next-line @next/next/no-img-element
        <img src={src} alt={alt} className="h-full w-full object-cover" />
      ) : (
        (fallback ?? alt.slice(0, 2).toUpperCase())
      )}
    </span>
  );
};

export type MessageContentProps = {
  children: React.ReactNode;
  markdown?: boolean;
  className?: string;
} & React.ComponentProps<typeof Markdown> &
  React.HTMLProps<HTMLDivElement>;

const MessageContent = ({
  children,
  markdown = false,
  className,
  ...props
}: MessageContentProps) => {
  const classNames = cn(
    "rounded-xl break-words whitespace-normal text-sm text-kumo-default",
    className,
  );

  return markdown ? (
    <Markdown className={classNames} {...props}>
      {children as string}
    </Markdown>
  ) : (
    <div className={classNames} {...props}>
      {children}
    </div>
  );
};

export type MessageActionsProps = {
  children: React.ReactNode;
  className?: string;
} & React.HTMLProps<HTMLDivElement>;

const MessageActions = ({ children, className, ...props }: MessageActionsProps) => (
  <div
    role="toolbar"
    aria-label="Message actions"
    className={cn("flex items-center gap-2 text-kumo-subtle", className)}
    {...props}
  >
    {children}
  </div>
);

export type MessageActionProps = {
  className?: string;
  tooltip: React.ReactNode;
  children: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  "aria-label"?: string;
};

const MessageAction = ({
  tooltip,
  children,
  className,
  side = "top",
  ...props
}: MessageActionProps) => {
  return (
    <span className={className}>
      <Tooltip content={tooltip} side={side} render={children as ReactElement} {...props} />
    </span>
  );
};

export { Message, MessageAvatar, MessageContent, MessageActions, MessageAction };
