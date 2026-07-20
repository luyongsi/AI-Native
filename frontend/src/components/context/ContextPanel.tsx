"use client";

import type { Requirement, KnowledgeSource } from "@/lib/types";
import KnowledgeSourceList from "@/components/dialogue/KnowledgeSourceList";
import CycleNavigator from "@/components/dialogue/CycleNavigator";

interface ContextPanelProps {
  requirement: {
    id: string;
    title: string;
    status: string;
    priority?: string;
    created_at?: string;
    assignee?: string;
    tags?: string[];
  } | null;
  knowledgeSources: KnowledgeSource[];
  cycles: import('@/lib/types').DialogueCycle[];
  currentCycle: number;
  onCycleChange?: (cycle: number) => void;
  isStreaming?: boolean;
}

const statusLabels: Record<string, string> = {
  pool: "需求池",
  designing: "设计中",
  developing: "开发中",
  testing: "测试中",
  releasing: "待发布",
  done: "已上线",
  draft: "草稿",
  confirmed: "已确认",
};

const priorityColors: Record<string, string> = {
  P0: "bg-red-100 text-red-700",
  P1: "bg-amber-100 text-amber-700",
  P2: "bg-blue-100 text-blue-700",
  P3: "bg-slate-700 text-slate-400",
};

export default function ContextPanel({
  requirement,
  knowledgeSources,
  cycles,
  currentCycle,
  onCycleChange,
  isStreaming,
}: ContextPanelProps) {
  if (!requirement) {
    return (
      <div className="p-4">
        <p className="text-xs text-slate-400 text-center">加载中...</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* 需求元信息 */}
      <div className="p-4 border-b border-slate-800">
        <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-2">
          需求信息
        </h3>
        <h2 className="text-sm font-semibold text-slate-100 mb-2 leading-snug">
          {requirement.title}
        </h2>
        <div className="flex flex-wrap gap-1.5 mb-2">
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-700 text-slate-400">
            {requirement.id}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded bg-blue-50 text-blue-600">
            {statusLabels[requirement.status] || requirement.status}
          </span>
          {requirement.priority && (
            <span className={`text-[10px] px-2 py-0.5 rounded ${priorityColors[requirement.priority] || "bg-slate-700 text-slate-400"}`}>
              {requirement.priority}
            </span>
          )}
        </div>
        {requirement.created_at && (
          <p className="text-[10px] text-slate-400">
            创建于 {new Date(requirement.created_at).toLocaleDateString("zh-CN")}
          </p>
        )}
      </div>

      {/* 对话轮次 */}
      {cycles.length > 0 && (
        <CycleNavigator
          cycles={cycles}
          currentCycle={currentCycle}
          onCycleChange={onCycleChange || (() => {})}
        />
      )}

      {/* 知识源 */}
      <div className="flex-1 overflow-y-auto">
        <KnowledgeSourceList sources={knowledgeSources} isStreaming={isStreaming} />
      </div>

      {/* 快捷操作 */}
      <div className="p-3 border-t border-slate-800">
        <button className="w-full py-2 text-xs font-medium text-brand bg-brand/5 rounded-lg hover:bg-brand/10 transition-colors">
          + 新增关联需求
        </button>
      </div>
    </div>
  );
}
