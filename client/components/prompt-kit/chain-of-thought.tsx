"use client";

import { Collapsible } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import { CaretDownIcon, CircleIcon } from "@phosphor-icons/react";
import React from "react";

export type ChainOfThoughtItemProps = React.ComponentProps<"div">;

export const ChainOfThoughtItem = ({ children, className, ...props }: ChainOfThoughtItemProps) => (
  <div className={cn("text-sm text-kumo-subtle", className)} {...props}>
    {children}
  </div>
);

export type ChainOfThoughtTriggerProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  leftIcon?: React.ReactNode;
  swapIconOnHover?: boolean;
};

export const ChainOfThoughtTrigger = ({
  children,
  className,
  leftIcon,
  swapIconOnHover = true,
  ...props
}: ChainOfThoughtTriggerProps) => (
  <Collapsible.Trigger
    className={cn(
      "group flex cursor-pointer items-center justify-start gap-1 text-left text-sm text-kumo-subtle hover:text-kumo-default",
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
      ) : (
        <span className="relative inline-flex size-4 items-center justify-center">
          <CircleIcon aria-hidden className="size-2 fill-kumo-brand" weight="fill" />
        </span>
      )}
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

export type ChainOfThoughtContentProps = React.HTMLAttributes<HTMLDivElement>;

export const ChainOfThoughtContent = ({
  children,
  className,
  ...props
}: ChainOfThoughtContentProps) => {
  return (
    <Collapsible.Panel className={cn("overflow-hidden text-kumo-default", className)} {...props}>
      <div className="grid grid-cols-[min-content_minmax(0,1fr)] gap-x-4">
        <div className="ml-1.75 h-full w-px bg-kumo-line group-data-[last=true]:hidden" />
        <div className="ml-1.75 h-full w-px bg-transparent group-data-[last=false]:hidden" />
        <div className="mt-2 space-y-2">{children}</div>
      </div>
    </Collapsible.Panel>
  );
};

export type ChainOfThoughtProps = {
  children: React.ReactNode;
  className?: string;
};

export function ChainOfThought({ children, className }: ChainOfThoughtProps) {
  const childrenArray = React.Children.toArray(children);

  return (
    <div className={cn("space-y-0", className)}>
      {childrenArray.map((child, index) => (
        <React.Fragment key={index}>
          {React.isValidElement(child) &&
            React.cloneElement(child as React.ReactElement<ChainOfThoughtStepProps>, {
              isLast: index === childrenArray.length - 1,
            })}
        </React.Fragment>
      ))}
    </div>
  );
}

export type ChainOfThoughtStepProps = {
  children: React.ReactNode;
  className?: string;
  isLast?: boolean;
};

export const ChainOfThoughtStep = ({
  children,
  className,
  isLast = false,
  ...props
}: ChainOfThoughtStepProps & React.HTMLAttributes<HTMLDivElement>) => {
  return (
    <Collapsible className={cn("group", className)} data-last={isLast} {...props}>
      {children}
      <div className="flex justify-start group-data-[last=true]:hidden">
        <div className="ml-1.75 h-4 w-px bg-kumo-line" />
      </div>
    </Collapsible>
  );
};
