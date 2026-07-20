"use client";

import type { RequirementDraft, WireframeData } from "@/lib/types";
import MarkdownRenderer from "@/components/MarkdownRenderer";

interface ArtifactPreviewProps {
  activeView: "draft" | "wireframe" | "spec";
  draft: RequirementDraft | null;
  wireframe: WireframeData | null;
  isStreaming: boolean;
  onViewChange: (view: "draft" | "wireframe" | "spec") => void;
}

export default function ArtifactPreview({
  activeView,
  draft,
  wireframe,
  isStreaming,
  onViewChange,
}: ArtifactPreviewProps) {
  return (
    <div className="h-full flex flex-col">
      {/* PreviewSwitcher */}
      <div className="flex items-center gap-1 px-3 py-2.5 border-b border-slate-800">
        {(["draft", "wireframe", "spec"] as const).map((view) => (
          <button
            key={view}
            onClick={() => onViewChange(view)}
            className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
              activeView === view
                ? "bg-brand text-white shadow-sm"
                : "text-slate-400 hover:bg-slate-700 hover:text-slate-600"
            }`}
          >
            <span className="flex items-center gap-1">
              {view === "draft" && (
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              )}
              {view === "wireframe" && (
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm0 8a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zm12 0a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                </svg>
              )}
              {view === "spec" && (
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                </svg>
              )}
              {{ draft: "需求草稿", wireframe: "线框图", spec: "Spec" }[view]}
            </span>
          </button>
        ))}

        {isStreaming && (
          <span className="ml-auto flex items-center gap-1 text-[10px] text-brand">
            <span className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
            生成中
          </span>
        )}
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto">
        {activeView === "draft" && <DraftPreviewContent draft={draft} isStreaming={isStreaming} />}
        {activeView === "wireframe" && <WireframePreviewContent wireframe={wireframe} />}
        {activeView === "spec" && <SpecPreviewContent draft={draft} />}
      </div>
    </div>
  );
}

/* ── 需求草稿预览 ── */
function DraftPreviewContent({
  draft,
  isStreaming,
}: {
  draft: RequirementDraft | null;
  isStreaming: boolean;
}) {
  if (!draft) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-slate-700 flex items-center justify-center mb-3">
          <svg className="w-6 h-6 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <p className="text-xs text-slate-400">
          {isStreaming ? "A1 正在生成需求草稿..." : "等待 A1 生成需求草稿"}
        </p>
      </div>
    );
  }

  const sections: { title: string; key: keyof RequirementDraft }[] = [
    { title: "概述", key: "overview" },
    { title: "背景", key: "background" },
    { title: "目标", key: "objectives" },
    { title: "功能需求", key: "functional_requirements" },
    { title: "非功能需求", key: "non_functional_requirements" },
    { title: "约束条件", key: "constraints" },
    { title: "验收标准", key: "acceptance_criteria" },
  ];

  return (
    <div className="p-4 space-y-4">
      {/* Title & Confidence */}
      {draft.title && (
        <div className="pb-3 border-b border-slate-800">
          <h2 className="text-base font-semibold text-slate-100">{draft.title}</h2>
          {draft.category && (
            <span className="text-[10px] text-slate-400 mt-1">{draft.category}</span>
          )}
        </div>
      )}

      {/* Sections */}
      {sections.map(
        (section) =>
          draft[section.key] && (
            <div key={section.key}>
              <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
                {section.title}
              </h3>
              <div className="text-sm text-slate-600 leading-relaxed">
                <MarkdownRenderer content={String(draft[section.key])} />
              </div>
            </div>
          )
      )}

      {/* Confidence */}
      {draft.confidence !== undefined && (
        <div className="pt-3 border-t border-slate-800">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-400">AI 置信度</span>
            <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${
                  draft.confidence >= 0.8
                    ? "bg-emerald-500"
                    : draft.confidence >= 0.5
                    ? "bg-amber-400"
                    : "bg-red-400"
                }`}
                style={{ width: `${Math.round(draft.confidence * 100)}%` }}
              />
            </div>
            <span className="text-[10px] font-medium text-slate-400">
              {Math.round(draft.confidence * 100)}%
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 线框图预览 ── */
function WireframePreviewContent({ wireframe }: { wireframe: WireframeData | null }) {
  if (!wireframe) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <div className="w-12 h-12 rounded-xl bg-slate-700 flex items-center justify-center mb-3">
          <svg className="w-6 h-6 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm0 8a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zm12 0a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
          </svg>
        </div>
        <p className="text-xs text-slate-400">等待 A1 生成线框图</p>
        <p className="text-[10px] text-slate-600 mt-1">线框图将在对话过程中自动生成</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <h3 className="text-xs font-medium text-slate-600 mb-3">
        {wireframe.pages?.length || 0} 个页面 · {wireframe.components?.length || 0} 个组件
      </h3>
      {wireframe.pages?.map((page, i) => (
        <div key={i} className="mb-4 p-3 bg-slate-800/50 rounded-xl border border-slate-700">
          <p className="text-xs font-medium text-slate-600 mb-1">{page.title || 'Page'}</p>
          <p className="text-[10px] text-slate-400">{page.route || page.zones?.join(", ") || ""}</p>
        </div>
      ))}
      {(!wireframe.pages || wireframe.pages.length === 0) && (
        <p className="text-xs text-slate-400">线框图数据加载中...</p>
      )}
    </div>
  );
}

/* ── Spec 预览 ── */
function SpecPreviewContent({ draft }: { draft: RequirementDraft | null }) {
  if (!draft) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <p className="text-xs text-slate-400">确认需求后将自动生成技术 Spec</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="text-sm text-slate-600 leading-relaxed">
        <MarkdownRenderer
          content={`# ${draft.title || "需求 Spec"}

## 概述
${draft.overview || "暂无"}

## 功能需求
${draft.functional_requirements || "暂无"}

## 验收标准
${draft.acceptance_criteria || "暂无"}
`}
        />
      </div>
    </div>
  );
}
