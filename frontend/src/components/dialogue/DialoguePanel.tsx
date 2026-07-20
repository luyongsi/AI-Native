"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useDialogueStore } from "@/stores/dialogueStore";
import { api } from "@/lib/api";
import ThinkingIndicator from "./ThinkingIndicator";
import StreamingMessage from "./StreamingMessage";
import MessageInput from "./MessageInput";
import ClarificationCard from "@/components/ClarificationCard";

interface DialoguePanelProps {
  reqId: string;
  sessionId?: string;
  variant?: "embedded" | "fullscreen";
  onDraftUpdate?: (draft: any) => void;
  onWireframeUpdate?: (wireframe: any) => void;
}

export default function DialoguePanel({
  reqId,
  sessionId: initialSessionId,
  variant = "embedded",
  onDraftUpdate,
  onWireframeUpdate,
}: DialoguePanelProps) {
  const store = useDialogueStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [localMessages, setLocalMessages] = useState<
    { role: "user" | "assistant"; content: string; timestamp?: string }[]
  >([]);
  const [initialized, setInitialized] = useState(false);

  // 初始化 session
  useEffect(() => {
    if (initialized) return;
    if (store.reqId === reqId && store.sessionId) {
      setInitialized(true);
      return;
    }

    const init = async () => {
      try {
        if (initialSessionId) {
          // 已有 session，加载历史
          const history = await api.getDialogueHistory(initialSessionId);
          store.setHistory(history.cycles);
          setInitialized(true);
        } else {
          // 创建新 session
          const current = await api.getDialogueCurrent(reqId);
          if (current.session_id) {
            store.setSession(reqId, current.session_id, current.status || "active", current.cycle || 0);
          }
          setInitialized(true);
        }
      } catch {
        setInitialized(true);
      }
    };
    init();
  }, [reqId, initialSessionId, initialized, store]);

  // 自动滚动
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMessages, store.thinkingText]);

  // 从 store 历史加载消息
  useEffect(() => {
    if (store.messages.length > 0 && localMessages.length === 0) {
      const msgs = store.messages.map((m) => ({
        role: m.role as "user" | "assistant",
        content:
          typeof m.content === "string"
            ? m.content
            : m.content?.text || (m.content?.clarifications ? JSON.stringify(m.content.clarifications) : JSON.stringify(m.content)),
        timestamp: m.timestamp ? new Date(m.timestamp).toLocaleTimeString("zh-CN") : undefined,
      }));
      setLocalMessages(msgs);
    }
  }, [store.messages]);

  // 转发 draft 更新
  useEffect(() => {
    if (store.draft && onDraftUpdate) {
      onDraftUpdate(store.draft);
    }
  }, [store.draft, onDraftUpdate]);

  // 转发 wireframe 更新
  useEffect(() => {
    if (store.wireframe && onWireframeUpdate) {
      onWireframeUpdate(store.wireframe);
    }
  }, [store.wireframe, onWireframeUpdate]);

  // done 事件后添加 assistant 消息
  useEffect(() => {
    if (!store.isStreaming && store.draft) {
      const lastMsg = localMessages[localMessages.length - 1];
      if (lastMsg?.role === "assistant") return;
      const summary = store.draft.title
        ? `已更新需求草稿：「${store.draft.title}」`
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
  }, [store.isStreaming]);

  const handleSend = useCallback(
    (content: string) => {
      const sid = store.sessionId || initialSessionId;
      if (!sid) return;

      setLocalMessages((prev) => [
        ...prev,
        { role: "user", content, timestamp: new Date().toLocaleTimeString("zh-CN") },
      ]);
      store.startStreaming();

      api.sendDialogueMessage(
        sid,
        content,
        null,
        (event) => store.handleEvent(event),
        () => {},
        (error) => {
          store.stopStreaming(sid, error instanceof Error ? error.message : "SSE 连接失败");
        }
      );
    },
    [store, initialSessionId]
  );

  const handleConfirm = useCallback(async () => {
    const sid = store.sessionId || initialSessionId;
    if (!sid) return;
    try {
      await api.confirmDialogue(sid);
      store.confirmDone();
    } catch (err) {
      store.stopStreaming(sid, err instanceof Error ? err.message : "确认失败");
    }
  }, [store, initialSessionId]);

  const showConfirm = !store.isStreaming && store.draft !== null && store.status === "active";

  return (
    <div className="flex flex-col h-full bg-slate-800">
      {/* Compact Header (embedded mode) */}
      {variant === "embedded" && (
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
              <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <span className="text-xs font-medium text-slate-600">A1 对话</span>
            {store.isStreaming && (
              <span className="inline-flex items-center gap-1 text-[10px] text-brand">
                <span className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
                分析中
              </span>
            )}
          </div>
          {store.draft && (
            <span className="text-[10px] text-slate-400">
              Round {store.cycle} · 置信度 {Math.round((store.confidenceScore ?? 0) * 100)}%
            </span>
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto bg-slate-800/50/50">
        {localMessages.length === 0 && !store.isStreaming ? (
          <div className="flex items-center justify-center h-full p-4 text-center">
            <p className="text-xs text-slate-400">等待对话开始...</p>
          </div>
        ) : (
          <>
            {localMessages.map((msg, i) => (
              <StreamingMessage key={i} role={msg.role} content={msg.content} timestamp={msg.timestamp} />
            ))}
            {store.isStreaming && (
              <ThinkingIndicator text={store.thinkingText} isActive={store.isStreaming} />
            )}
            {store.clarifications.length > 0 && (
              <div className="px-4 py-2">
                {store.clarifications.map((item, i) => (
                  <ClarificationCard key={i} items={[item]} onSelect={() => {}} />
                ))}
              </div>
            )}
            {store.error && (
              <div className="mx-4 my-2 p-2 bg-red-50 border border-red-100 rounded-lg">
                <p className="text-xs text-red-600">{store.error}</p>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input */}
      <MessageInput
        onSend={handleSend}
        onConfirm={handleConfirm}
        isStreaming={store.isStreaming}
        showConfirm={showConfirm}
        placeholder="输入修改意见或补充信息..."
      />
    </div>
  );
}
