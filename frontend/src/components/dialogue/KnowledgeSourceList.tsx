"use client";

import type { KnowledgeSource } from "@/lib/types";

interface KnowledgeSourceListProps {
  sources: KnowledgeSource[];
  isStreaming?: boolean;
}

export default function KnowledgeSourceList({
  sources,
  isStreaming,
}: KnowledgeSourceListProps) {
  if (sources.length === 0) {
    return (
      <div className="px-3 py-4 text-center">
        <p className="text-[11px] text-slate-400">
          {isStreaming ? "正在召回相关知识..." : "暂无知识源"}
        </p>
      </div>
    );
  }

  const getTypeIcon = (type: string) => {
    switch (type) {
      case "doc": return "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253";
      case "code": return "M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4";
      case "api": return "M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z";
      case "spec": return "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z";
      default: return "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z";
    }
  };

  const getRelevanceColor = (score: number) => {
    if (score >= 0.8) return "bg-emerald-500";
    if (score >= 0.5) return "bg-amber-400";
    return "bg-slate-300";
  };

  return (
    <div className="px-3 py-2">
      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider px-1 mb-2">
        知识源 ({sources.length})
      </h3>
      <div className="space-y-1">
        {sources.map((source, i) => (
          <div
            key={i}
            className="flex items-start gap-2 px-2 py-2 rounded-lg hover:bg-slate-800/50 transition-colors cursor-pointer group"
          >
            <svg
              className="w-3.5 h-3.5 text-slate-400 flex-shrink-0 mt-0.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d={getTypeIcon(source.type || "document")} />
            </svg>
            <div className="flex-1 min-w-0">
              <p className="text-[11px] text-slate-600 truncate group-hover:text-slate-100">
                {source.title || source.name || "未知来源"}
              </p>
              {source.type && (
                <span className="text-[9px] text-slate-400">{source.type}</span>
              )}
            </div>
            {source.relevance !== undefined && (
              <div className="flex items-center gap-1 flex-shrink-0">
                <div className="w-8 h-1 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${getRelevanceColor(source.relevance)} rounded-full transition-all`}
                    style={{ width: `${Math.round(source.relevance * 100)}%` }}
                  />
                </div>
                <span className="text-[9px] text-slate-400">
                  {Math.round(source.relevance * 100)}%
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
