"use client";

import type { DialogueCycle } from "@/lib/types";

interface CycleNavigatorProps {
  cycles: DialogueCycle[];
  currentCycle: number;
  onCycleChange: (cycle: number) => void;
}

export default function CycleNavigator({
  cycles,
  currentCycle,
  onCycleChange,
}: CycleNavigatorProps) {
  if (cycles.length === 0) return null;

  return (
    <div className="px-3 py-2 border-b border-slate-800">
      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider px-1 mb-1.5">
        对话轮次
      </h3>
      <div className="flex items-center gap-1.5">
        {cycles.map((cycle) => {
          const isActive = cycle.cycle === currentCycle;
          return (
            <button
              key={cycle.cycle}
              onClick={() => onCycleChange(cycle.cycle)}
              className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                isActive
                  ? "bg-brand text-white shadow-sm"
                  : "bg-slate-700 text-slate-400 hover:bg-slate-600 hover:text-slate-600"
              }`}
            >
              Round {cycle.cycle}
            </button>
          );
        })}
      </div>
    </div>
  );
}
