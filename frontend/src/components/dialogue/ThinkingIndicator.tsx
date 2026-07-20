"use client";

interface ThinkingIndicatorProps {
  text: string;
  isActive: boolean;
  variant?: "pulse" | "scan" | "dots";
}

export default function ThinkingIndicator({
  text,
  isActive,
  variant = "pulse",
}: ThinkingIndicatorProps) {
  if (!isActive) return null;

  return (
    <div className="flex items-start gap-3 px-4 py-3 animate-fade-in">
      <div className="flex-shrink-0 mt-0.5">
        {variant === "pulse" && (
          <div className="relative w-7 h-7 rounded-full bg-brand/10 flex items-center justify-center">
            <div className="w-3 h-3 rounded-full bg-brand animate-pulse" />
            <div className="absolute inset-0 rounded-full border-2 border-brand/30 animate-ping" />
          </div>
        )}
        {variant === "dots" && (
          <div className="flex items-center gap-1 px-1 py-2">
            <span className="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-1.5 h-1.5 rounded-full bg-brand animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
        )}
        {variant === "scan" && (
          <div className="relative w-7 h-7 rounded-full bg-brand/10 flex items-center justify-center overflow-hidden">
            <div className="w-3 h-3 rounded-full bg-brand" />
            <div
              className="absolute inset-0 bg-gradient-to-r from-transparent via-brand/30 to-transparent"
              style={{ animation: "scan 1.5s linear infinite" }}
            />
            <style>{`@keyframes scan { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }`}</style>
          </div>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-slate-400 mb-1">A1 Agent 思考中...</p>
        <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap break-words">
          {text || "正在分析需求..."}
        </p>
        <div className="mt-2 h-1 bg-slate-700 rounded-full overflow-hidden w-full max-w-[200px]">
          <div className="h-full bg-gradient-to-r from-brand to-brand-light rounded-full animate-pulse" style={{ width: "60%" }} />
        </div>
      </div>
    </div>
  );
}
