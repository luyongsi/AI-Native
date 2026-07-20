"use client";

import { cn } from "@/lib/utils";

export interface SkeletonProps {
  variant?: "text" | "circular" | "rectangular";
  width?: string;
  height?: string;
  className?: string;
}

const variantDefaults: Record<
  NonNullable<SkeletonProps["variant"]>,
  { width: string; height: string; className: string }
> = {
  text: {
    width: "100%",
    height: "1rem",
    className: "rounded",
  },
  circular: {
    width: "2.5rem",
    height: "2.5rem",
    className: "rounded-full",
  },
  rectangular: {
    width: "100%",
    height: "8rem",
    className: "rounded-lg",
  },
};

export default function Skeleton({
  variant = "text",
  width,
  height,
  className,
}: SkeletonProps) {
  const defaults = variantDefaults[variant];

  return (
    <div
      className={cn(
        "animate-pulse bg-slate-700/60",
        defaults.className,
        className,
      )}
      style={{
        width: width ?? defaults.width,
        height: height ?? defaults.height,
      }}
      aria-hidden="true"
    />
  );
}
