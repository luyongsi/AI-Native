"use client";

import MarkdownRenderer from "@/components/MarkdownRenderer";

interface StreamingMessageProps {
  role: "user" | "assistant" | "system";
  content: string;
  isStreaming?: boolean;
  timestamp?: string;
}

export default function StreamingMessage({
  role,
  content,
  isStreaming = false,
  timestamp,
}: StreamingMessageProps) {
  const isUser = role === "user";
  const isAssistant = role === "assistant";

  return (
    <div
      className={`flex gap-3 px-4 py-3 animate-fade-in ${
        isUser ? "flex-row-reverse" : ""
      }`}
    >
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium ${
          isUser
            ? "bg-brand text-white"
            : isAssistant
            ? "bg-gradient-to-br from-violet-500 to-indigo-600 text-white"
            : "bg-slate-200 text-slate-400"
        }`}
      >
        {isUser ? "我" : isAssistant ? "A1" : "S"}
      </div>

      {/* Content */}
      <div
        className={`flex-1 min-w-0 ${
          isUser ? "flex flex-col items-end" : ""
        }`}
      >
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-medium text-slate-400">
            {isUser ? "我" : isAssistant ? "A1 Agent" : "系统"}
          </span>
          {timestamp && (
            <span className="text-[10px] text-slate-400">{timestamp}</span>
          )}
          {isStreaming && (
            <span className="inline-block w-1.5 h-3 bg-brand rounded-sm animate-pulse" />
          )}
        </div>
        <div
          className={`text-sm leading-relaxed whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 ${
            isUser
              ? "bg-brand text-white"
              : isAssistant
              ? "bg-slate-700 text-slate-200"
              : "bg-amber-50 text-amber-800 text-xs"
          }`}
        >
          {isAssistant && !isUser ? (
            <MarkdownRenderer content={content} />
          ) : (
            content
          )}
        </div>
      </div>
    </div>
  );
}
