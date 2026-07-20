'use client';

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Requirement } from "@/lib/types";

type ViewMode = "kanban" | "list" | "stream";

const stageOrder = ["pool", "designing", "developing", "testing", "releasing", "done"] as const;
type Stage = typeof stageOrder[number];

const stageLabels: Record<Stage, string> = {
  pool: "需求池",
  designing: "设计中",
  developing: "开发中",
  testing: "测试中",
  releasing: "待发布",
  done: "已上线",
};

const stageColors: Record<Stage, string> = {
  pool: "bg-slate-700 border-slate-700",
  designing: "bg-indigo-50 border-indigo-200",
  developing: "bg-amber-50 border-amber-200",
  testing: "bg-cyan-50 border-cyan-200",
  releasing: "bg-emerald-50 border-emerald-200",
  done: "bg-green-50 border-green-200",
};

const wipLimits: Record<Stage, number> = {
  pool: 20,
  designing: 8,
  developing: 8,
  testing: 6,
  releasing: 4,
  done: 99,
};

const stageIcons: Record<Stage, string> = {
  pool: "📥",
  designing: "🎨",
  developing: "🔧",
  testing: "🧪",
  releasing: "🚀",
  done: "✅",
};

export default function RequirementsPage() {
  const router = useRouter();
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("kanban");
  const [filterVersion, setFilterVersion] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [filterPriority, setFilterPriority] = useState("all");
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState<string | null>(null);

  const fetchRequirements = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.getRequirements();
      setRequirements(res.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取需求列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRequirements();
  }, [fetchRequirements]);

  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  const filtered = requirements.filter((r) => {
    if (filterVersion !== "all" && r.version !== filterVersion) return false;
    if (filterType !== "all" && (r.type || "" || r.sourceType) !== filterType) return false;
    if (filterPriority !== "all" && r.priority !== filterPriority) return false;
    if (search && !r.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const requirementsByStage = stageOrder.reduce((acc, stage) => {
    acc[stage] = filtered.filter((r) => (r.stage || r.status) === stage);
    return acc;
  }, {} as Record<Stage, Requirement[]>);

  const versions = [...new Set(requirements.map((r) => r.version).filter(Boolean))];
  const types = [...new Set(requirements.map((r) => r.type || "").filter(Boolean))];
  const priorities = [...new Set(requirements.map((r) => r.priority).filter(Boolean))];

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-800/50">
        <div className="animate-spin h-8 w-8 border-2 border-slate-900 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-slate-800/50 gap-4">
        <div className="text-red-500">{error}</div>
        <button onClick={fetchRequirements} className="text-blue-600 hover:underline text-sm">重试</button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-slate-800/50 p-6">
      {toast && (
        <div className="fixed top-20 right-6 z-50 bg-slate-900 text-white text-xs px-4 py-2 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h1 className="text-lg font-semibold text-slate-100">需求流</h1>
        <div className="flex items-center gap-2">
          <div className="flex bg-slate-700 rounded-lg p-0.5">
            {(["kanban", "list", "stream"] as ViewMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setViewMode(m)}
                className={`px-3 py-1 text-xs rounded-md transition-colors ${
                  viewMode === m ? "bg-slate-800 text-slate-100 shadow-sm" : "text-slate-400 hover:text-slate-600"
                }`}
              >
                {{ kanban: "看板", list: "列表", stream: "价值流" }[m]}
              </button>
            ))}
          </div>
          <button
            onClick={() => router.push("/app/requirements/new")}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 text-white text-xs font-medium rounded-lg hover:bg-slate-800 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            新建需求
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-shrink-0">
        <select
          value={filterVersion}
          onChange={(e) => setFilterVersion(e.target.value)}
          className="text-xs border border-slate-700 rounded-lg px-3 py-1.5 bg-slate-800 text-slate-400"
        >
          <option value="all">全部版本</option>
          {versions.map((v) => <option key={v}>{v}</option>)}
        </select>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="text-xs border border-slate-700 rounded-lg px-3 py-1.5 bg-slate-800 text-slate-400"
        >
          <option value="all">全部类型</option>
          <option value="feature">功能需求</option>
          <option value="tech">技术优化</option>
          <option value="bug">Bug修复</option>
        </select>
        <select
          value={filterPriority}
          onChange={(e) => setFilterPriority(e.target.value)}
          className="text-xs border border-slate-700 rounded-lg px-3 py-1.5 bg-slate-800 text-slate-400"
        >
          <option value="all">全部优先级</option>
          <option>P0</option>
          <option>P1</option>
          <option>P2</option>
          <option>P3</option>
        </select>
        <input
          type="text"
          placeholder="搜索需求..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="text-xs border border-slate-700 rounded-lg px-3 py-1.5 bg-slate-800 text-slate-400 flex-1 max-w-xs"
        />
        <div className="flex-1" />
        <span className="text-[10px] text-slate-400">共 {requirements.length} 个需求</span>
      </div>

      {/* Kanban View */}
      {viewMode === "kanban" && (
        <div className="flex-1 flex gap-3 overflow-x-auto pb-4 min-h-0">
          {stageOrder.map((stage) => {
            const reqs = requirementsByStage[stage];
            const count = reqs.length;
            const limit = wipLimits[stage];
            const isOver = count > limit;

            return (
              <div key={stage} className="flex-shrink-0 w-[280px] flex flex-col">
                <div className={`flex items-center justify-between mb-2 px-2 rounded-t-lg py-2 ${
                  stageColors[stage]
                }`}>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs">{stageIcons[stage]}</span>
                    <span className="text-xs font-semibold text-slate-600">{stageLabels[stage]}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                      isOver ? "bg-red-100 text-red-600" : "bg-slate-800/60 text-slate-400"
                    }`}>
                      {count}/{limit}
                    </span>
                  </div>
                  {isOver && <span className="text-[10px] text-red-500">WIP超限</span>}
                </div>
                <div className={`flex-1 rounded-b-lg border p-2 space-y-2 overflow-y-auto min-h-0 ${
                  stageColors[stage]
                }`}>
                  {reqs.length === 0 && (
                    <div className="text-[10px] text-slate-400 text-center py-6">
                      拖拽需求到此列
                    </div>
                  )}
                  {reqs.map((req) => (
                    <div
                      key={req.id}
                      onClick={() => router.push(`/app/requirements/${req.id}`)}
                      className="bg-slate-800 rounded-lg border border-slate-700 p-3 cursor-pointer hover:border-slate-400 hover:shadow-sm transition-all"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] text-slate-400">{req.id}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          req.priority === "P0" ? "bg-red-100 text-red-700" :
                          req.priority === "P1" ? "bg-orange-100 text-orange-700" :
                          "bg-slate-700 text-slate-400"
                        }`}>{req.priority}</span>
                      </div>
                      <div className="text-xs font-medium text-slate-200 mb-1.5 line-clamp-2">{req.title}</div>
                      {req.blocked && (
                        <span className="text-[10px] text-red-500 bg-red-50 px-1.5 py-0.5 rounded">阻塞: {req.blockReason}</span>
                      )}
                      <div className="flex items-center gap-2 mt-2 text-[10px] text-slate-400">
                        <span>{req.version}</span>
                        <span>·</span>
                        <span>{req.pm}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* List View */}
      {viewMode === "list" && (
        <div className="flex-1 overflow-auto bg-slate-800 rounded-xl border border-slate-700 min-h-0">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-800/50/50 text-left text-[10px] uppercase tracking-wider text-slate-400">
                <th className="py-2 px-3 font-medium">ID</th>
                <th className="py-2 px-3 font-medium">标题</th>
                <th className="py-2 px-3 font-medium">状态</th>
                <th className="py-2 px-3 font-medium">优先级</th>
                <th className="py-2 px-3 font-medium">版本</th>
                <th className="py-2 px-3 font-medium">PM</th>
                <th className="py-2 px-3 font-medium">AI完成度</th>
                <th className="py-2 px-3 font-medium">创建时间</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((req) => (
                <tr
                  key={req.id}
                  onClick={() => router.push(`/app/requirements/${req.id}`)}
                  className="border-b border-slate-50 hover:bg-slate-800/50 cursor-pointer transition-colors"
                >
                  <td className="py-2 px-3 text-slate-400">{req.id}</td>
                  <td className="py-2 px-3 font-medium text-slate-200 max-w-[200px] truncate">{req.title}</td>
                  <td className="py-2 px-3">
                    <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full ${
                      (req.stage || req.status || "pool") === "done" ? "bg-green-100 text-green-700" :
                      (req.stage || req.status || "pool") === "pool" ? "bg-slate-700 text-slate-400" :
                      "bg-blue-50 text-blue-600"
                    }`}>
                      {stageIcons[(req.stage || req.status || "pool") as Stage]} {stageLabels[(req.stage || req.status || "pool") as Stage]}
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    <span className={`text-[10px] ${
                      req.priority === "P0" ? "text-red-600 font-medium" :
                      req.priority === "P1" ? "text-orange-600" : "text-slate-400"
                    }`}>{req.priority}</span>
                  </td>
                  <td className="py-2 px-3 text-slate-400">{req.version}</td>
                  <td className="py-2 px-3 text-slate-400">{req.pm || "-"}</td>
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-1.5">
                      <div className="w-12 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                        <div className="h-full bg-blue-500 rounded-full" style={{ width: `${(req as any).aiCompletion || 0}%` }} />
                      </div>
                      <span className="text-[10px]">{(req as any).aiCompletion || 0}%</span>
                    </div>
                  </td>
                  <td className="py-2 px-3 text-slate-400">{new Date(req.createdAt).toLocaleDateString("zh-CN")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Stream View */}
      {viewMode === "stream" && (
        <div className="flex-1 overflow-auto min-h-0">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {filtered.map((req) => (
              <div
                key={req.id}
                onClick={() => router.push(`/app/requirements/${req.id}`)}
                className="bg-slate-800 rounded-xl border border-slate-700 p-4 cursor-pointer hover:border-slate-400 hover:shadow-sm transition-all"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-slate-400">{req.id}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      req.priority === "P0" ? "bg-red-100 text-red-700" :
                      req.priority === "P1" ? "bg-orange-100 text-orange-700" :
                      "bg-slate-700 text-slate-400"
                    }`}>{req.priority}</span>
                    {req.blocked && <span className="text-[10px] text-red-500 bg-red-50 px-1.5 py-0.5 rounded">阻塞</span>}
                  </div>
                  <span className="text-[10px] text-slate-400">{req.version}</span>
                </div>
                <div className="text-sm font-medium text-slate-200 mb-3 line-clamp-2">{req.title}</div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px] text-slate-400">
                  <span>AI完成度: {(req as any).aiCompletion || 0}%</span>
                  <span>人工介入: {(req as any).humanInterventions || 0}次</span>
                  <span>参与: {(req as any).assignees?.join(", ") || "-"}</span>
                  <span>{stageLabels[(req.stage || req.status || "pool") as Stage]}</span>
                </div>
                <div className="mt-3 pt-3 border-t border-slate-50">
                  <div className="flex items-center gap-3">
                    {stageOrder.map((s, i) => (
                      <div key={s} className="flex items-center gap-1">
                        <div className={`w-2 h-2 rounded-full ${
                          stageOrder.indexOf((req.stage || req.status || "pool") as Stage) >= i ? "bg-blue-500" : "bg-slate-200"
                        }`} />
                        <span className="text-[10px]">{stageIcons[s]}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); router.push(`/app/requirements/${req.id}`); }}
                  className="mt-3 w-full text-center text-[10px] text-blue-600 hover:text-blue-700 font-medium py-1.5 border border-blue-100 rounded-lg hover:bg-blue-50 transition-colors"
                >
                  进入需求工作台
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
