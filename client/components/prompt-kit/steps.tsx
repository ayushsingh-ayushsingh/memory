"use client";

import { Collapsible } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import { CaretDownIcon } from "@phosphor-icons/react";

export type StepsItemProps = React.ComponentProps<"div">;

export const StepsItem = ({ children, className, ...props }: StepsItemProps) => (
  <div className={cn("text-sm text-kumo-subtle", className)} {...props}>
    {children}
  </div>
);

export type StepsTriggerProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  leftIcon?: React.ReactNode;
  swapIconOnHover?: boolean;
};

export const StepsTrigger = ({
  children,
  className,
  leftIcon,
  swapIconOnHover = true,
  ...props
}: StepsTriggerProps) => (
  <Collapsible.Trigger
    className={cn(
      "group flex w-full cursor-pointer items-center justify-start gap-1 text-sm text-kumo-subtle hover:text-kumo-default",
      className,
    )}
    {...props}
  >
    <div className="flex items-center gap-2">
      {leftIcon ? (
        <span className="relative inline-flex size-4 items-center justify-center">
          <span
            aria-hidden
            className={cn("transition-opacity", swapIconOnHover && "group-hover:opacity-0")}
          >
            {leftIcon}
          </span>
          {swapIconOnHover && (
            <CaretDownIcon
              aria-hidden
              className="absolute size-4 opacity-0 transition-opacity group-hover:opacity-100 group-data-[state=open]:rotate-180"
            />
          )}
        </span>
      ) : null}
      <span>{children}</span>
    </div>
    {!leftIcon && (
      <CaretDownIcon
        aria-hidden
        className="size-4 transition-transform group-data-[state=open]:rotate-180"
      />
    )}
  </Collapsible.Trigger>
);

export type StepsContentProps = React.HTMLAttributes<HTMLDivElement> & {
  bar?: React.ReactNode;
};

export const StepsContent = ({ children, className, bar, ...props }: StepsContentProps) => {
  return (
    <Collapsible.Panel className={cn("overflow-hidden text-kumo-default", className)} {...props}>
      <div className="mt-3 grid max-w-full min-w-0 grid-cols-[min-content_minmax(0,1fr)] items-start gap-x-3">
        <div className="min-w-0 self-stretch">{bar ?? <StepsBar />}</div>
        <div className="min-w-0 space-y-2">{children}</div>
      </div>
    </Collapsible.Panel>
  );
};

export type StepsBarProps = React.HTMLAttributes<HTMLDivElement>;

export const StepsBar = ({ className, ...props }: StepsBarProps) => (
  <div className={cn("h-full w-[2px] bg-kumo-line", className)} aria-hidden="true" {...props} />
);

export type StepsProps = React.HTMLAttributes<HTMLDivElement> & {
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
};

export function Steps({ defaultOpen = true, className, ...props }: StepsProps) {
  return <Collapsible className={cn(className)} defaultOpen={defaultOpen} {...props} />;
}
