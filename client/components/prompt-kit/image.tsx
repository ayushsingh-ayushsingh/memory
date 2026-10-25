"use client";

import { cn } from "@/lib/utils";
import NextImage from "next/image";
import { useEffect, useMemo, type ImgHTMLAttributes } from "react";

export type GeneratedImageLike = {
  base64?: string;
  uint8Array?: Uint8Array;
  mediaType?: string;
};

export type ImageProps = GeneratedImageLike &
  Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & {
    alt: string;
  };

function getImageSrc({ base64, mediaType }: Pick<GeneratedImageLike, "base64" | "mediaType">) {
  if (base64 && mediaType) {
    return `data:${mediaType};base64,${base64}`;
  }
  return undefined;
}

export const Image = ({
  base64,
  uint8Array,
  mediaType = "image/png",
  className,
  alt,
  ...props
}: ImageProps) => {
  const objectUrl = useMemo(() => {
    if (!uint8Array || !mediaType) return undefined;
    const blob = new Blob([uint8Array as BlobPart], { type: mediaType });
    return URL.createObjectURL(blob);
  }, [uint8Array, mediaType]);

  useEffect(() => {
    if (!objectUrl) return;
    return () => URL.revokeObjectURL(objectUrl);
  }, [objectUrl]);

  const base64Src = getImageSrc({ base64, mediaType });
  const src = base64Src ?? objectUrl;

  if (!src) {
    return (
      <div
        aria-label={alt}
        role="img"
        className={cn(
          "h-auto max-w-full animate-pulse overflow-hidden rounded-lg bg-kumo-recessed motion-reduce:animate-none",
          className,
        )}
        {...props}
      />
    );
  }

  return (
    <NextImage
      {...(props as Omit<
        React.ComponentProps<typeof NextImage>,
        "src" | "alt" | "width" | "height"
      >)}
      src={src}
      alt={alt}
      width={0}
      height={0}
      sizes="100vw"
      unoptimized
      className={cn("h-auto max-w-full overflow-hidden rounded-lg ring ring-kumo-line", className)}
      role="img"
    />
  );
};
