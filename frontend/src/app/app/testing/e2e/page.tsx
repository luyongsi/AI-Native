"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { api } from "@/lib/api";
import type { E2EEvent, E2ERunResult } from "@/lib/types";

type StepStatus = "pending" | "running" | "passed" | "failed" | "warning";

const STEP_META: Record<string, { label: string; icon: string }> = {
  create_req: { label: "创建需求", icon: "\uD83D\uDCDD" },
  infra_check: { label: "基础设施检测", icon: "\uD83D\uDD27" },
  a1_dialogue: { label: "A1 对话分析", icon: "\uD83E\uDDE0" },
  confirm: { label: "确认对话", icon: "\u2705" },
  trigger_wf: { label: "触发工作流", icon: "\uD83D\uDE80" },
  a2_analysis: { label: "A2 知识分析", icon: "\uD83D\uDD0D" },
  gate0_record: { label: "Gate0 审批记录", icon: "\uD83D\uDEF0\uFE0F" },
};

function makeInitialSteps() {
  const s: Record<string, { status: StepStatus; detail: string; error?: string }> = {};
  Object.keys(STEP_META).forEach(k => { s[k] = { status: "pending", detail: "" }; });
  return s;
}

const PRESETS = [
  { title: "用户登录功能", message: "实现用户登录功能，支持邮箱+密码登录，包含记住密码、忘记密码、OAuth登录选项" },
  { title: "订单管理看板", message: "订单管理看板，包含订单列表、筛选、导出、状态流转，支持批量操作" },
  { title: "API网关权限控制", message: "API网关的RBAC权限控制系统，支持基于角色和资源的细粒度访问控制" },
];

export default function E2ETestPage() {
  const [pipelineStatus, setPipelineStatus] = useState<"idle" | "running" | "completed">("idle");
  const [steps, setSteps] = useState(makeInitialSteps);
  const [runId, setRunId] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<E2ERunResult[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<number | null>(null);

  useEffect(() => {
    api.e2e.history(10).then(res => { if (res && res.items) setHistory(res.items); }).catch(() => {});
  }, []);

  const handleRun = useCallback(async () => {
    const t = title.trim() || "E2E Test";
    const m = message.trim() || t;
    if (!t) return;
    setPipelineStatus("running");
    setError(null);
    setSteps(makeInitialSteps());
    try {
      const res = await api.e2e.run(t, m);
      setRunId(res.run_id);
      api.e2e.stream(res.run_id, (event: E2EEvent) => {
        if (event.type === "step-update") {
          const stepKey = event.data.status || "";
          setSteps(prev => ({
            ...prev,
            [stepKey]: {
              status: (event.data.status || "pending") as StepStatus,
              detail: event.data.detail || "",
              error: event.data.error,
            },
          }));
        } else if (event.type === "run-complete") {
          setVerdict(event.data.verdict || null);
          setPipelineStatus("completed");
          api.e2e.history(10).then(r => { if (r && r.items) setHistory(r.items); }).catch(() => {});
        }
      }).catch(err => { setError(err.message); setPipelineStatus("completed"); });
    } catch (err: any) { setError(err.message); setPipelineStatus("idle"); }
  }, [title, message]);

  const getStepColor = (s: StepStatus) => {
    switch (s) {
      case "passed": return "text-emerald-400";
      case "failed": return "text-red-400";
      case "running": return "text-blue-400 animate-pulse";
      default: return "text-slate-500";
    }
  };

  const getStepIcon = (s: StepStatus) => {
    switch (s) {
      case "passed": return "\u2705";
      case "failed": return "\u274C";
      case "running": return "\u23F3";
      default: return "\u26AA";
    }
  };

  return (
    <div className="p-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">E2E Pipeline Test</h1>
          <p className="text-xs text-slate-400 mt-0.5">端到端管线测试与验证</p>
        </div>
        <span className={"text-[10px] px-2.5 py-1 rounded-full font-medium " + 
          (pipelineStatus === "running" ? "bg-blue-500/10 text-blue-400" : 
           pipelineStatus === "completed" ? (verdict === "pass" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400") : 
           "bg-slate-700 text-slate-400")}>
          {pipelineStatus === "idle" ? "就绪" : pipelineStatus === "running" ? "运行中" : verdict === "pass" ? "PASS" : "FAIL"}
        </span>
      </div>

      <div className="grid grid-cols-[1fr_2fr] gap-5">
        {/* Left: Config */}
        <div className="space-y-4">
          {/* Presets */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700">
              <span className="text-xs font-semibold text-slate-200">预设场景</span>
            </div>
            <div className="p-3 space-y-2">
              {PRESETS.map((preset, i) => (
                <button key={i} onClick={() => { setSelectedPreset(i); setTitle(preset.title); setMessage(preset.message); }}
                  className={"w-full text-left p-3 rounded-lg border transition-all " + 
                    (selectedPreset === i ? "border-blue-500 bg-blue-500/5" : "border-slate-700 hover:border-slate-500 bg-slate-800/50")}>
                  <p className="text-xs font-medium text-slate-200">{preset.title}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5 truncate">{preset.message}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Custom Input */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700">
              <span className="text-xs font-semibold text-slate-200">自定义测试</span>
            </div>
            <div className="p-4 space-y-3">
              <input value={title} onChange={e => { setTitle(e.target.value); setSelectedPreset(null); }}
                placeholder="需求标题" className="w-full bg-slate-900 border border-slate-700 text-slate-200 text-xs px-3 py-2 rounded-lg focus:border-blue-500 outline-none" />
              <textarea value={message} onChange={e => { setMessage(e.target.value); setSelectedPreset(null); }}
                placeholder="需求描述" rows={4} className="w-full bg-slate-900 border border-slate-700 text-slate-200 text-xs px-3 py-2 rounded-lg focus:border-blue-500 outline-none resize-none" />
              <button onClick={handleRun} disabled={pipelineStatus === "running"}
                className="w-full py-2.5 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg transition-colors flex items-center justify-center gap-2">
                {pipelineStatus === "running" ? <><span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />运行中...</> : "运行 E2E 测试"}
              </button>
              {error && <p className="text-[10px] text-red-400">{error}</p>}
            </div>
          </div>
        </div>

        {/* Right: Progress */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden flex flex-col min-h-[500px]">
          <div className="px-4 py-3 border-b border-slate-700">
            <span className="text-xs font-semibold text-slate-200">Pipeline 进度 {runId ? "Run " + runId.slice(0, 12) + "..." : ""}</span>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-1">
            {pipelineStatus === "idle" ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-12">
                <div className="text-3xl mb-3">🚀</div>
                <p className="text-xs text-slate-400">选择预设场景或自定义输入后点击运行</p>
                <p className="text-[10px] text-slate-500 mt-1">测试将通过 7 个步骤验证完整的 E2E 管线</p>
              </div>
            ) : (
              Object.entries(STEP_META).map(([key, meta]) => {
                const step = steps[key] || { status: "pending", detail: "" };
                return (
                  <div key={key} className={"flex items-center gap-3 px-3 py-2.5 rounded-lg " + (step.status === "running" ? "bg-blue-500/5" : "")}>
                    <span className="text-sm">{getStepIcon(step.status)}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-slate-200">{meta.icon} {meta.label}</span>
                        <span className={"text-[9px] font-medium " + getStepColor(step.status)}>{step.status}</span>
                      </div>
                      {step.detail && <p className="text-[10px] text-slate-400 mt-0.5 truncate">{step.detail}</p>}
                      {step.error && <p className="text-[10px] text-red-400 mt-0.5">{step.error}</p>}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* History */}
      <div className="mt-6 bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700">
          <span className="text-xs font-semibold text-slate-200">测试历史 ({history.length})</span>
        </div>
        {history.length === 0 ? (
          <div className="p-8 text-center text-xs text-slate-400">暂无历史记录</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-slate-700 text-slate-400">
                <th className="text-left px-4 py-2 font-medium">Run ID</th>
                <th className="text-left px-4 py-2 font-medium">标题</th>
                <th className="text-left px-4 py-2 font-medium">结果</th>
                <th className="text-left px-4 py-2 font-medium">耗时</th>
              </tr></thead>
              <tbody>
                {history.map(h => {
                  const pass = h.verdict === "pass";
                  let dur = "";
                  if (h.started_at && h.finished_at) {
                    const d = (new Date(h.finished_at).getTime() - new Date(h.started_at).getTime()) / 1000;
                    dur = d < 60 ? Math.round(d) + "s" : Math.floor(d / 60) + "m" + Math.round(d % 60) + "s";
                  }
                  return (
                    <tr key={h.run_id} className="border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer">
                      <td className="px-4 py-2.5 font-mono text-[10px] text-slate-300">{h.run_id.slice(0, 18)}...</td>
                      <td className="px-4 py-2.5 text-slate-200">{h.title || "?"}</td>
                      <td className="px-4 py-2.5">
                        <span className={"inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded " + (pass ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400")}>
                          <span className={"w-1.5 h-1.5 rounded-full " + (pass ? "bg-emerald-400" : "bg-red-400")} />{pass ? "PASS" : "FAIL"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-slate-400">{dur}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
