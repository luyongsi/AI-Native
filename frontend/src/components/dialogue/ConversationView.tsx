"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useDialogueStore } from "@/stores/dialogueStore";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";
import ThinkingIndicator from "./ThinkingIndicator";
import StreamingMessage from "./StreamingMessage";
import MessageInput from "./MessageInput";
import ClarificationCard from "@/components/ClarificationCard";

interface ConversationViewProps {
  initialTitle?: string;
  onComplete?: (reqId: string, sessionId: string) => void;
  onCancel?: () => void;
}

export default function ConversationView({
  initialTitle = "",
  onComplete,
  onCancel,
}: ConversationViewProps) {
  const router = useRouter();
  const store = useDialogueStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [localMessages, setLocalMessages] = useState<
    { role: "user" | "assistant"; content: string; timestamp?: string }[]
  >([]);
  const [isCreating, setIsCreating] = useState(false);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMessages, store.thinkingText]);

  // 创建对话 session
  const createSession = useCallback(
    async (title?: string) => {
      setIsCreating(true);
      store.reset();
      try {
        const result = await api.createDialogueRequirement(title || undefined);
        store.setSession(result.req_id, result.session_id || null, "active", 0);
        return result;
      } catch (err) {
        store.setSession("", null, "no_session", 0);
        store.stopStreaming("", err instanceof Error ? err.message : "创建失败");
        return null;
      } finally {
        setIsCreating(false);
      }
    },
    [store]
  );

  // 发送消息并开始 SSE 流
  const handleSend = useCallback(
    async (content: string) => {
      const currentSessionId = store.sessionId;
      const currentReqId = store.reqId;

      // 如果还没有 session，先创建
      if (!currentSessionId) {
        const result = await createSession(initialTitle);
        if (!result) return;

        // 重新获取 session id
        const sid = useDialogueStore.getState().sessionId;
        if (!sid) return;

        // 添加用户消息
        setLocalMessages((prev) => [
          ...prev,
          { role: "user", content, timestamp: new Date().toLocaleTimeString("zh-CN") },
        ]);

        // 开始 SSE 流
        store.startStreaming();
        api.sendDialogueMessage(
          sid,
          content,
          null, // 不需要 clarification_answer
          (event) => {
            store.handleEvent(event);
          },
          () => {
            // onComplete (XHR done)
          },
          (error) => {
            store.stopStreaming(sid, error instanceof Error ? error.message : "SSE 连接失败");
          }
        );
        return;
      }

      // 已有 session，直接发送
      setLocalMessages((prev) => [
        ...prev,
        { role: "user", content, timestamp: new Date().toLocaleTimeString("zh-CN") },
      ]);
      store.startStreaming();
      api.sendDialogueMessage(
        currentSessionId,
        content,
        null,
        (event) => store.handleEvent(event),
        () => {},
        (error) => {
          store.stopStreaming(
            currentSessionId,
            error instanceof Error ? error.message : "SSE 连接失败"
          );
        }
      );
    },
    [store, initialTitle, createSession]
  );

  // 确认完成
  const handleConfirm = useCallback(async () => {
    const sid = store.sessionId;
    if (!sid) return;
    try {
      await api.confirmDialogue(sid);
      store.confirmDone();
      if (onComplete && store.reqId) {
        onComplete(store.reqId, sid);
      } else if (store.reqId) {
        router.push(`/app/requirements/${store.reqId}`);
      }
    } catch (err) {
      store.stopStreaming(sid, err instanceof Error ? err.message : "确认失败");
    }
  }, [store, onComplete, router]);

  // 当 done 事件触发时，添加 assistant 消息
  useEffect(() => {
    if (!store.isStreaming && store.draft && localMessages.length > 0) {
      const lastMsg = localMessages[localMessages.length - 1];
      if (lastMsg?.role === "assistant") return; // 已经有 assistant 回复了
      // 添加草稿摘要
      const summary =
        store.draft.title || store.draft.overview
          ? `已生成需求草稿：「${store.draft.title || "未命名"}」`
          : "对话已完成";
      setLocalMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: summary,
          timestamp: new Date().toLocaleTimeString("zh-CN"),
        },
      ]);
    }
  }, [store.isStreaming, store.draft]);

  // 判断是否显示确认按钮
  const showConfirm = !store.isStreaming && store.draft !== null && store.status === "active";

  return (
    <div className="flex flex-col h-full bg-slate-800 rounded-2xl border border-slate-700 overflow-hidden shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800 bg-slate-800">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
            <svg className="w-4.5 h-4.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-100">
              {initialTitle || "A1 需求对话"}
            </h2>
            <p className="text-[11px] text-slate-400">
              {store.isStreaming
                ? "A1 正在分析..."
                : store.draft
                ? `Round ${store.cycle} · 置信度 ${Math.round((store.confidenceScore ?? 0) * 100)}%`
                : isCreating
                ? "正在创建对话..."
                : "开始描述你的需求"}
            </p>
          </div>
        </div>
        {onCancel && (
          <button
            onClick={onCancel}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-400 hover:bg-slate-700 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto bg-slate-800/50/50">
        {localMessages.length === 0 && !store.isStreaming && !isCreating ? (
          <div className="flex flex-col items-center justify-center h-full p-8 text-center">
            <div className="w-16 h-16 rounded-2xl bg-brand/10 flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-brand" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <h3 className="text-sm font-medium text-slate-200 mb-1">开始需求对话</h3>
            <p className="text-xs text-slate-400 max-w-sm">
              输入你的需求描述，A1 Agent 将通过多轮对话帮你完善需求，生成需求草稿和线框图。
            </p>
          </div>
        ) : isCreating ? (
          <div className="flex items-center justify-center h-full">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-brand border-t-transparent rounded-full animate-spin" />
              <p className="text-xs text-slate-400">正在创建对话...</p>
            </div>
          </div>
        ) : (
          <>
            {localMessages.map((msg, i) => (
              <StreamingMessage
                key={i}
                role={msg.role}
                content={msg.content}
                timestamp={msg.timestamp}
              />
            ))}

            {/* Thinking Indicator */}
            {store.isStreaming && (
              <ThinkingIndicator text={store.thinkingText} isActive={store.isStreaming} variant="dots" />
            )}

            {/* Clarifications */}
            {store.clarifications.length > 0 && (
              <div className="px-4 py-3">
                {store.clarifications.map((item, i) => (
                  <ClarificationCard key={i} items={[item]} onSelect={() => {}} />
                ))}
              </div>
            )}

            {/* Error */}
            {store.error && (
              <div className="mx-4 my-3 p-3 bg-red-50 border border-red-100 rounded-xl">
                <p className="text-xs text-red-600 flex items-center gap-1.5">
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
                  </svg>
                  {store.error}
                </p>
              </div>
            )}

            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Area */}
      <MessageInput
        onSend={handleSend}
        onConfirm={handleConfirm}
        disabled={isCreating}
        isStreaming={store.isStreaming}
        showConfirm={showConfirm}
        placeholder={
          store.isStreaming
            ? "A1 正在思考..."
            : "描述你的需求，或提出修改意见..."
        }
      />
    </div>
  );
}
