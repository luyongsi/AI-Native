"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";

interface MessageInputProps {
  onSend: (content: string) => void;
  onConfirm?: () => void;
  onSkip?: () => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
  showConfirm?: boolean;
}

export default function MessageInput({
  onSend,
  onConfirm,
  onSkip,
  disabled = false,
  isStreaming = false,
  placeholder = "输入你的需求描述...",
  showConfirm = false,
}: MessageInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 150)}px`;
    }
  }, [value]);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-slate-700 bg-slate-800 px-4 py-3">
      <div className="flex items-end gap-2">
        {/* Textarea */}
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="w-full px-4 py-2.5 text-sm border border-slate-700 rounded-xl 
              focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/10
              placeholder:text-slate-600 resize-none disabled:opacity-50 disabled:cursor-not-allowed
              bg-slate-800/50 hover:bg-slate-800 transition-colors"
          />
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {showConfirm && onConfirm && (
            <button
              onClick={onConfirm}
              className="px-4 py-2.5 bg-emerald-500 text-white text-xs font-medium rounded-xl
                hover:bg-emerald-600 transition-colors flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              确认完成
            </button>
          )}
          {showConfirm && onSkip && (
            <button
              onClick={onSkip}
              className="px-3 py-2.5 text-xs font-medium text-slate-400 hover:text-slate-600
                hover:bg-slate-700 rounded-xl transition-colors"
            >
              跳过
            </button>
          )}

          {/* Send button */}
          <button
            onClick={handleSend}
            disabled={disabled || !value.trim()}
            className="p-2.5 bg-brand text-white rounded-xl hover:bg-brand-dark transition-colors
              disabled:opacity-40 disabled:cursor-not-allowed"
            title="发送 (Enter)"
          >
            {isStreaming ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Hint */}
      <p className="text-[10px] text-slate-400 mt-1.5 text-center">
        Enter 发送 · Shift+Enter 换行
      </p>
    </div>
  );
}
