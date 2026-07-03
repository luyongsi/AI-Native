'use client';

import type { TopologyNode, TopologyEdge } from '@/lib/types';

const dotColors: Record<string, string> = {
  running: 'bg-emerald-500',
  idle: 'bg-slate-300',
  waiting: 'bg-amber-400',
  error: 'bg-red-500',
  done: 'bg-blue-500',
};

/* Topology Node Component */
function TopoNode({
  id,
  label,
  status,
  subtitle,
  x,
  y,
  onClick,
}: {
  id: string;
  label: string;
  status: string;
  subtitle?: string;
  x: number;
  y: number;
  onClick?: (id: string) => void;
}) {
  return (
    <div
      onClick={() => onClick?.(id)}
      className="absolute bg-white border border-slate-200 rounded-xl px-3 py-2 shadow-sm hover:shadow-md hover:border-slate-300 transition-all cursor-pointer group"
      style={{ left: x - 60, top: y, width: 130 }}
    >
      <div className="flex items-center gap-1.5">
        <span
          className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColors[status] || 'bg-slate-300'}`}
        />
        <span className="text-[11px] font-medium text-slate-700 truncate">{label}</span>
      </div>
      {subtitle && <p className="text-[9px] text-slate-400 mt-0.5">{subtitle}</p>}
      {/* Hover action */}
      <div className="absolute -top-1 -right-1 w-4 h-4 bg-slate-900 text-white rounded-full hidden group-hover:flex items-center justify-center text-[8px]">
        +
      </div>
    </div>
  );
}

interface TopologyViewProps {
  onSelectNode?: (nodeId: string) => void;
}

export default function TopologyView({ onSelectNode }: TopologyViewProps) {
  return (
    <div className="flex-1 flex gap-4 min-h-0">
      {/* Main Topology Area */}
      <div
        className="flex-1 bg-white rounded-xl border border-slate-200 relative overflow-auto"
        style={{ minHeight: 600 }}
      >
        <div className="relative" style={{ width: 750, height: 600 }}>
          {/* SVG Edges */}
          <svg
            className="absolute inset-0 pointer-events-none"
            viewBox="0 0 750 600"
            style={{ width: 750, height: 600, zIndex: 1 }}
          >
            {/* Orchestrator -> PRD, UI, Test */}
            <line
              x1="400" y1="60" x2="150" y2="180"
              stroke="#cbd5e1" strokeWidth="1.5" markerEnd="url(#arrow)"
            />
            <line
              x1="400" y1="60" x2="400" y2="180"
              stroke="#cbd5e1" strokeWidth="1.5" markerEnd="url(#arrow)"
            />
            <line
              x1="400" y1="60" x2="650" y2="180"
              stroke="#cbd5e1" strokeWidth="1.5" strokeDasharray="5,5" markerEnd="url(#arrow)"
            />
            {/* PRD, UI -> Spec Decomposer */}
            <line
              x1="150" y1="180" x2="275" y2="300"
              stroke="#cbd5e1" strokeWidth="1.5" markerEnd="url(#arrow)"
            />
            <line
              x1="400" y1="180" x2="275" y2="300"
              stroke="#cbd5e1" strokeWidth="1.5" markerEnd="url(#arrow)"
            />
            {/* Spec -> DevAgents */}
            <line
              x1="275" y1="300" x2="85" y2="420"
              stroke="#cbd5e1" strokeWidth="1.5" markerEnd="url(#arrow)"
            />
            <line
              x1="275" y1="300" x2="275" y2="420"
              stroke="#cbd5e1" strokeWidth="1.5" markerEnd="url(#arrow)"
            />
            <line
              x1="275" y1="300" x2="500" y2="420"
              stroke="#cbd5e1" strokeWidth="1.5" markerEnd="url(#arrow)"
            />
            {/* Dev3 -> Test */}
            <line
              x1="500" y1="420" x2="650" y2="180"
              stroke="#cbd5e1" strokeWidth="1.5" strokeDasharray="5,5" markerEnd="url(#arrow)"
            />
            {/* Dev1, Dev2 -> CI */}
            <line
              x1="85" y1="420" x2="180" y2="540"
              stroke="#cbd5e1" strokeWidth="1.5" strokeDasharray="5,5" markerEnd="url(#arrow)"
            />
            <line
              x1="275" y1="420" x2="180" y2="540"
              stroke="#cbd5e1" strokeWidth="1.5" strokeDasharray="5,5" markerEnd="url(#arrow)"
            />
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                <polygon points="0 0, 8 3, 0 6" fill="#cbd5e1" />
              </marker>
            </defs>
          </svg>

          {/* Topology Nodes */}
          <div className="absolute inset-0" style={{ zIndex: 2 }}>
            <TopoNode id="orchestrator" label="Orchestrator" status="running" x={400} y={40} onClick={onSelectNode} />
            <TopoNode id="prd" label="PRD Agent" status="running" subtitle="生成 Spec" x={85} y={160} onClick={onSelectNode} />
            <TopoNode id="ui" label="UI Agent" status="running" subtitle="生成原型" x={340} y={160} onClick={onSelectNode} />
            <TopoNode id="test" label="Test Agent" status="waiting" subtitle="等待执行" x={580} y={160} onClick={onSelectNode} />
            <TopoNode id="spec" label="Spec Decomposer" status="running" subtitle="方案拆解中" x={210} y={280} onClick={onSelectNode} />
            <TopoNode id="dev1" label="DevAgent-1" status="running" subtitle="编码中" x={20} y={400} onClick={onSelectNode} />
            <TopoNode id="dev2" label="DevAgent-2" status="running" subtitle="编码中" x={220} y={400} onClick={onSelectNode} />
            <TopoNode id="dev3" label="DevAgent-3" status="done" subtitle="已完成" x={440} y={400} onClick={onSelectNode} />
            <TopoNode id="ci" label="CI Agent" status="error" subtitle="构建失败" x={120} y={520} onClick={onSelectNode} />
          </div>

          {/* Legend */}
          <div
            className="absolute bottom-4 left-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-slate-400 bg-white/90 px-3 py-2 rounded-lg border border-slate-100"
            style={{ zIndex: 3 }}
          >
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />运行中
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />编码中
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />等待中
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500" />异常
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-300" />空闲
            </span>
            <span className="ml-2">── 数据流</span>
            <span className="flex items-center gap-1">
              <span className="w-4 border-t border-dashed border-slate-300" />触发/通知
            </span>
          </div>
        </div>
      </div>

      {/* Selected Node Detail (placeholder) */}
      <div className="w-64 bg-white rounded-xl border border-slate-200 p-4 flex-shrink-0">
        <p className="text-[10px] text-slate-400 text-center py-8">
          点击拓扑图中任意节点查看详情
        </p>
      </div>
    </div>
  );
}
