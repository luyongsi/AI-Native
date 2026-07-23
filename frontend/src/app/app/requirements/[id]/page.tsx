"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Requirement, RequirementDraft, WireframeData } from "@/lib/types";
import { useDialogueStore } from "@/stores/dialogueStore";
import ThreeColumnLayout from "@/components/three-column/ThreeColumnLayout";
import ContextPanel from "@/components/context/ContextPanel";
import DialoguePanel from "@/components/dialogue/DialoguePanel";
import ArtifactPreview from "@/components/artifact/ArtifactPreview";

export default function RequirementDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const dialogueStore = useDialogueStore();

  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"draft" | "wireframe" | "spec">("draft");

  // 加载需求数据
  const fetchRequirement = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getRequirement(id);
      setRequirement(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchRequirement();
  }, [fetchRequirement]);

  // 加载 A1 对话当前状态
  useEffect(() => {
    if (!id) return;
    api
      .getDialogueCurrent(id)
      .then((current) => {
        if (current.session_id) {
          dialogueStore.setSession(id, current.session_id, current.status || "active", current.cycle || 0);
        }
      })
      .catch(() => {
        // 没有现有对话，保持 no_session 状态
      });
  }, [id]);

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-10rem)]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-2 border-brand border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-slate-400">加载需求详情...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-10rem)]">
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
            <svg className="w-6 h-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-medium text-slate-200">加载失败</p>
            <p className="text-xs text-slate-400 mt-1">{error}</p>
          </div>
          <button
            onClick={fetchRequirement}
            className="px-4 py-2 bg-brand text-white text-xs font-medium rounded-xl hover:bg-brand-dark transition-colors"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  // Not found
  if (!requirement) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-10rem)]">
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="w-12 h-12 rounded-full bg-slate-700 flex items-center justify-center">
            <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <p className="text-sm text-slate-400">需求未找到</p>
          <button
            onClick={() => router.push("/app/requirements")}
            className="px-4 py-2 text-xs font-medium text-brand hover:bg-brand/5 rounded-xl transition-colors"
          >
            返回需求列表
          </button>
        </div>
      </div>
    );
  }

  // 构造 ContextPanel 所需的 requirement 对象
  const contextReq = {
    id: requirement.id,
    title: requirement.title,
    status: requirement.status,
    priority: requirement.priority,
    created_at: requirement.created_at || requirement.createdAt,
    assignee: requirement.assignees?.[0],
    tags: [] as string[],
  };

  return (
    <div className="h-[calc(100vh-5rem)]">
      <ThreeColumnLayout
        left={
          <ContextPanel
            requirement={contextReq}
            knowledgeSources={dialogueStore.knowledgeSources}
            cycles={dialogueStore.cycles.map((c) => ({ cycle: c.cycle, status: c.status || 'active', messages: c.messages }))}
            currentCycle={dialogueStore.cycle}
            onCycleChange={() => {}}
            isStreaming={dialogueStore.isStreaming}
          />
        }
        center={
          <DialoguePanel
            reqId={id}
            sessionId={dialogueStore.sessionId || undefined}
            variant="embedded"
            onDraftUpdate={(draft: RequirementDraft) => {
              // Auto-switch to draft tab when draft content arrives
              setActiveView("draft");
            }}
            onWireframeUpdate={(wireframe: WireframeData) => {
              // Don't auto-switch so the user can freely explore all tabs.
              // The wireframe tab is available but won't steal focus.
            }}
          />
        }
        right={
          <ArtifactPreview
            activeView={activeView}
            draft={dialogueStore.draft}
            wireframe={dialogueStore.wireframe}
            isStreaming={dialogueStore.isStreaming}
            onViewChange={setActiveView}
          />
        }
      />
    </div>
  );
}
