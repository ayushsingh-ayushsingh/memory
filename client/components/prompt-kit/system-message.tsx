"use client";

import { Banner, Button } from "@cloudflare/kumo";
import { cn } from "@/lib/utils";
import { InfoIcon, WarningCircleIcon, WarningIcon } from "@phosphor-icons/react";
import React from "react";

export type SystemMessageProps = React.ComponentProps<"div"> & {
  variant?: "action" | "error" | "warning";
  fill?: boolean;
  icon?: React.ReactNode;
  isIconHidden?: boolean;
  cta?: {
    label: string;
    onClick?: () => void;
    variant?: "primary" | "secondary" | "outline" | "ghost";
  };
};

function variantToBanner(
  variant: NonNullable<SystemMessageProps["variant"]>,
): "default" | "error" | "alert" {
  switch (variant) {
    case "error":
      return "error";
    case "warning":
      return "alert";
    default:
      return "default";
  }
}

export function SystemMessage({
  children,
  variant = "action",
  fill = false,
  icon,
  isIconHidden = false,
  cta,
  className,
  role,
  ...props
}: SystemMessageProps) {
  const getDefaultIcon = () => {
    if (isIconHidden) return null;

    switch (variant) {
      case "error":
        return <WarningCircleIcon aria-hidden weight="fill" className="size-4 fill-kumo-danger" />;
      case "warning":
        return <WarningIcon aria-hidden weight="fill" className="size-4 fill-kumo-warning" />;
      default:
        return <InfoIcon aria-hidden weight="fill" className="size-4 fill-kumo-info" />;
    }
  };

  const getIconToShow = () => {
    if (isIconHidden) return null;
    if (icon) return icon;
    return getDefaultIcon();
  };

  const bannerVariant = variantToBanner(variant);
  const computedRole =
    role ?? (variant === "error" ? "alert" : variant === "warning" ? "alert" : "status");

  return (
    <div className={cn(className)} role={computedRole} {...props}>
      <Banner
        variant={bannerVariant}
        icon={
          getIconToShow() ? (
            <span className="h-lh flex items-center">{getIconToShow()}</span>
          ) : undefined
        }
        description={<span className="text-sm">{children}</span>}
        action={
          cta ? (
            <Button
              variant={
                cta.variant === "primary"
                  ? "primary"
                  : cta.variant === "ghost"
                    ? "ghost"
                    : cta.variant === "outline"
                      ? "outline"
                      : "secondary"
              }
              size="sm"
              onClick={cta.onClick}
            >
              {cta.label}
            </Button>
          ) : undefined
        }
      />
      {fill ? <span className="sr-only">Filled system message</span> : null}
    </div>
  );
}
