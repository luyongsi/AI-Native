"use client";

import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
}

const defaultIcon = (
  <svg
    className="h-12 w-12 text-slate-400"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1}
    stroke="currentColor"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M20.25 7.5l-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5m6 4.125 2.25 2.25m0 0 2.25 2.25M12 13.875l2.25-2.25M12 13.875l-2.25 2.25M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z"
    />
  </svg>
);

export default function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex min-h-[280px] flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-slate-700 bg-slate-900/50 px-6 py-12 text-center",
        className,
      )}
    >
      {/* 图标 */}
      <div className="flex-shrink-0 text-slate-400">{icon ?? defaultIcon}</div>

      {/* 标题 */}
      <h3 className="text-base font-semibold text-slate-600">{title}</h3>

      {/* 描述 */}
      {description && (
        <p className="max-w-xs text-sm text-slate-400 leading-relaxed">
          {description}
        </p>
      )}

      {/* CTA */}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-2 inline-flex items-center gap-2 rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-slate-100 transition-colors hover:bg-slate-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
