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
        {activeView === "spec" && <SpecPreviewContent draft={draft} wireframe={wireframe} />}
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

  // Helper: render a field value — string, array, or fallback
  const renderField = (value: any): string => {
    if (!value) return "";
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.join(", ");
    return String(value);
  };

  // Helper: render acceptance criteria as clickable checklist-style items
  const renderAcceptanceCriteria = (ac: any) => {
    const items: string[] =
      Array.isArray(ac) ? ac.map(String) :
      typeof ac === "string" ? ac.split(/[,;]\s*/).filter(Boolean) : [];
    if (!items.length) return null;
    return (
      <div key="acceptance_criteria">
        <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-2">
          验收标准
        </h3>
        <ul className="space-y-1.5">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2 text-sm text-slate-600 leading-relaxed">
              <span className="flex-shrink-0 mt-1 w-2 h-2 rounded-full bg-emerald-500/60" />
              <span><MarkdownRenderer content={item} /></span>
            </li>
          ))}
        </ul>
      </div>
    );
  };

  // Build sections from draft fields — ordered for readability
  const sections: { title: string; content: any; isMarkdown?: boolean }[] = [
    { title: "概述", content: draft.overview || draft.description, isMarkdown: true },
    { title: "背景", content: draft.background, isMarkdown: true },
    { title: "目标", content: draft.objectives, isMarkdown: true },
    { title: "领域", content: draft.domain },
    { title: "功能需求", content: draft.functional_requirements, isMarkdown: true },
    { title: "非功能需求", content: draft.non_functional_requirements, isMarkdown: true },
    { title: "约束条件", content: renderField(draft.constraints), isMarkdown: true },
    { title: "风险", content: renderField(draft.risks), isMarkdown: true },
    { title: "预计成本", content: draft.estimated_cost },
  ];

  const hasEntities = Array.isArray(draft.entities) && draft.entities.length > 0;
  const hasUseCases = Array.isArray(draft.use_cases) && draft.use_cases.length > 0;

  return (
    <div className="p-4 space-y-4 pb-12">
      {/* Title & Category */}
      <div className="pb-3 border-b border-slate-800">
        <h2 className="text-base font-semibold text-slate-100">
          {draft.title || "未命名需求"}
        </h2>
        <div className="flex items-center gap-2 mt-1">
          {draft.category && (
            <span className="text-[10px] text-slate-400 bg-slate-700 px-2 py-0.5 rounded-full">
              {draft.category}
            </span>
          )}
          {/* Confidence */}
          {draft.confidence !== undefined && (
            <div className="flex items-center gap-1.5">
              <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
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
              <span className="text-[10px] text-slate-400">
                {Math.round(draft.confidence * 100)}%
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Sections */}
      {sections.map(
        (section) =>
          section.content && (
            <div key={section.title}>
              <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
                {section.title}
              </h3>
              <div className="text-sm text-slate-600 leading-relaxed">
                {section.isMarkdown ? (
                  <MarkdownRenderer content={String(section.content)} />
                ) : (
                  String(section.content)
                )}
              </div>
            </div>
          )
      )}

      {/* Entities */}
      {hasEntities && (
        <div>
          <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
            实体 ({draft.entities!.length})
          </h3>
          <div className="space-y-2">
            {draft.entities!.map((entity, i) => (
              <div
                key={i}
                className="bg-slate-800/50 border border-slate-700 rounded-lg p-2.5"
              >
                <p className="text-sm font-medium text-slate-600">{entity.name}</p>
                {entity.description && (
                  <p className="text-xs text-slate-400 mt-0.5">{entity.description}</p>
                )}
                {Array.isArray(entity.attributes) && entity.attributes.length > 0 && (
                  <p className="text-[10px] text-slate-400 mt-1">
                    属性：{entity.attributes.join("、")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Use Cases */}
      {hasUseCases && (
        <div>
          <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
            用例 ({draft.use_cases!.length})
          </h3>
          <ul className="space-y-1">
            {draft.use_cases!.map((uc, i) => (
              <li key={i} className="text-sm text-slate-600 flex gap-2">
                <span className="text-brand">▸</span>
                {uc}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Acceptance Criteria — rendered last as a checklist */}
      {renderAcceptanceCriteria(draft.acceptance_criteria)}
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

  // Map component type to icon/color
  const compMeta: Record<string, { color: string; label: string }> = {
    button: { color: "bg-blue-500/20 text-blue-400 border-blue-500/30", label: "按钮" },
    input: { color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30", label: "输入" },
    table: { color: "bg-purple-500/20 text-purple-400 border-purple-500/30", label: "表格" },
    form: { color: "bg-amber-500/20 text-amber-400 border-amber-500/30", label: "表单" },
    card: { color: "bg-pink-500/20 text-pink-400 border-pink-500/30", label: "卡片" },
    nav: { color: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30", label: "导航" },
  };

  return (
    <div className="p-4 space-y-4 pb-12">
      {/* Header */}
      <div className="flex items-center gap-2 pb-3 border-b border-slate-800">
        <span className="text-[10px] uppercase tracking-wider text-slate-400 bg-slate-700 px-2 py-0.5 rounded-full">
          {wireframe.type || "wireframe"}
        </span>
        <span className="text-xs text-slate-400">
          {wireframe.pages?.length || 0} 页面
        </span>
        {wireframe.generated_at && (
          <span className="text-[10px] text-slate-600 ml-auto">
            {new Date(wireframe.generated_at).toLocaleString("zh-CN")}
          </span>
        )}
      </div>

      {/* Pages */}
      {wireframe.pages?.map((page, pi) => {
        const pageComps = (wireframe.components || []).filter(
          (c) => c.page_id === page.id
        );
        return (
          <div key={pi} className="border border-slate-700 rounded-xl overflow-hidden">
            {/* Page Header */}
            <div className="flex items-center gap-2 px-3 py-2 bg-slate-800/70 border-b border-slate-700">
              <div className="w-5 h-5 rounded bg-brand/20 flex items-center justify-center">
                <svg className="w-3 h-3 text-brand" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
              </div>
              <span className="text-xs font-medium text-slate-600">{page.title}</span>
              <span className="text-[10px] text-slate-400 bg-slate-700 px-1.5 py-0.5 rounded">
                {page.route}
              </span>
            </div>

            {/* Zones */}
            <div className="p-2 space-y-2">
              {page.zones?.map((zone, zi) => {
                const zoneComps = pageComps.filter((c) => c.zone === zone);
                return (
                  <div key={zi} className="border border-dashed border-slate-700 rounded-lg p-2.5">
                    <p className="text-[10px] font-medium text-slate-400 uppercase mb-2">
                      {zone}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {zoneComps.length > 0 ? (
                        zoneComps.map((comp, ci) => {
                          const meta = compMeta[comp.type] || { color: "bg-slate-500/20 text-slate-400 border-slate-500/30", label: comp.type };
                          return (
                            <div
                              key={ci}
                              className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] border ${meta.color}`}
                              title={comp.component}
                            >
                              <span className="w-1 h-1 rounded-full bg-current opacity-60" />
                              {meta.label}
                            </div>
                          );
                        })
                      ) : (
                        <span className="text-[10px] text-slate-400 italic">无组件</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {/* Component Legend */}
      {wireframe.components && wireframe.components.length > 0 && (
        <div className="pt-3 border-t border-slate-800">
          <h4 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">
            组件清单
          </h4>
          <div className="space-y-1">
            {wireframe.components.map((comp, i) => {
              const meta = compMeta[comp.type] || { color: "bg-slate-500/20 text-slate-400 border-slate-500/30", label: comp.type };
              return (
                <div key={i} className="flex items-center gap-2 text-xs text-slate-600">
                  <span className={`inline-block w-1.5 h-1.5 rounded-full ${meta.color.split(" ")[1]}`} />
                  <span className="font-medium">{comp.component}</span>
                  <span className="text-[10px] text-slate-400">({meta.label})</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Spec 预览 ── */
function SpecPreviewContent({ draft, wireframe }: { draft: RequirementDraft | null; wireframe: WireframeData | null }) {
  if (!draft) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <p className="text-xs text-slate-400">确认需求后将自动生成技术 Spec</p>
      </div>
    );
  }

  // 从 draft 派生技术内容
  const title = draft.title || "未命名需求";
  const overview = draft.description || draft.overview || "";
  const entityNames = (draft.entities || []).map((e) => e.name).filter(Boolean);
  const domain = draft.domain || "core";
  const hasEntities = entityNames.length > 0;
  const hasUseCases = Array.isArray(draft.use_cases) && draft.use_cases.length > 0;
  const hasConstraints = Array.isArray(draft.constraints) && draft.constraints.length > 0;
  const hasRisks = Array.isArray(draft.risks) && draft.risks.length > 0;
  const hasWireframePages = wireframe?.pages && wireframe.pages.length > 0;

  return (
    <div className="p-4 space-y-5 pb-12">
      {/* Title */}
      <div className="pb-3 border-b border-slate-800">
        <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
        <p className="text-[10px] text-slate-400 mt-1">技术规格说明书</p>
      </div>

      {/* 1. 概述 */}
      {overview && (
        <section>
          <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
            1. 概述
          </h3>
          <div className="text-sm text-slate-600 leading-relaxed bg-slate-800/30 rounded-lg p-2.5">
            <MarkdownRenderer content={overview} />
          </div>
        </section>
      )}

      {/* 2. 技术栈建议 */}
      <section>
        <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
          2. 技术栈建议
        </h3>
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: "前端框架", value: "React / Next.js" },
            { label: "UI 库", value: "Tailwind CSS" },
            { label: "后端", value: "FastAPI / Python" },
            { label: "数据库", value: "PostgreSQL + pgvector" },
            { label: "缓存", value: "Redis" },
            { label: "消息队列", value: "NATS JetStream" },
            { label: "领域", value: domain },
            { label: "认证", value: "JWT / OAuth2" },
          ].map((item, i) => (
            <div key={i} className="bg-slate-800/40 border border-slate-700 rounded-lg p-2">
              <p className="text-[10px] text-slate-400">{item.label}</p>
              <p className="text-xs font-medium text-slate-600 mt-0.5">{item.value}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 3. API 接口设计 */}
      {hasEntities && (
        <section>
          <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
            3. API 接口设计
          </h3>
          <div className="space-y-1.5">
            {entityNames.map((name, i) => (
              <div key={i} className="bg-slate-800/30 border border-slate-700 rounded-lg px-2.5 py-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono text-brand bg-brand/10 px-1.5 py-0.5 rounded">
                    CRUD
                  </span>
                  <span className="text-xs font-medium text-slate-600">/api/{name.toLowerCase()}</span>
                  <span className="text-[10px] text-slate-400 ml-auto">
                    GET POST PUT DELETE
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 4. 数据模型 */}
      {hasEntities && (
        <section>
          <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
            4. 数据模型
          </h3>
          <div className="space-y-2">
            {draft.entities!.map((entity, i) => (
              <div key={i} className="bg-slate-800/30 border border-slate-700 rounded-lg p-2.5">
                <p className="text-xs font-semibold text-slate-600">{entity.name}</p>
                {entity.description && (
                  <p className="text-[10px] text-slate-400 mt-0.5">{entity.description}</p>
                )}
                {Array.isArray(entity.attributes) && entity.attributes.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {entity.attributes.map((attr, ai) => (
                      <span key={ai} className="text-[10px] bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded">
                        {attr}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 5. 页面路由 */}
      {hasWireframePages && (
        <section>
          <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
            5. 页面路由
          </h3>
          <div className="space-y-1.5">
            {wireframe!.pages.map((page, i) => (
              <div key={i} className="flex items-center gap-2 bg-slate-800/30 border border-slate-700 rounded-lg px-2.5 py-1.5">
                <span className="text-[10px] font-mono text-slate-500">page_{i + 1}</span>
                <span className="text-xs font-medium text-slate-600">{page.title}</span>
                <span className="text-[10px] font-mono text-brand ml-auto">{page.route}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 6. 约束与风险 */}
      {(hasConstraints || hasRisks) && (
        <section>
          <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
            6. 约束与风险
          </h3>
          {hasConstraints && (
            <div className="mb-2">
              <p className="text-[10px] text-slate-400 mb-1">约束条件</p>
              <ul className="space-y-0.5">
                {draft.constraints!.map((c, i) => (
                  <li key={i} className="text-xs text-slate-600 flex gap-1.5">
                    <span className="text-amber-400">⚠</span> {c}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {hasRisks && (
            <div>
              <p className="text-[10px] text-slate-400 mb-1">风险项</p>
              <ul className="space-y-0.5">
                {draft.risks!.map((r, i) => (
                  <li key={i} className="text-xs text-slate-600 flex gap-1.5">
                    <span className="text-red-400">!</span> {r}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {/* 7. 验收标准摘要 */}
      {draft.acceptance_criteria && (
        <section>
          <h3 className="text-[11px] font-medium text-slate-400 uppercase tracking-wider mb-1.5">
            7. 测试用例（BDD）
          </h3>
          <div className="space-y-1.5">
            {(Array.isArray(draft.acceptance_criteria)
              ? draft.acceptance_criteria
              : (draft.acceptance_criteria as any).split
                ? (draft.acceptance_criteria as string).split(/[,;]\s*/).filter(Boolean)
                : []
            ).slice(0, 5).map((ac, i) => (
              <div key={i} className="bg-slate-800/30 border border-slate-700 rounded-lg p-2">
                <p className="text-[10px] text-slate-400 mb-0.5">TC-{String(i + 1).padStart(3, "0")}</p>
                <p className="text-xs text-slate-600 leading-relaxed">{String(ac)}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
