'use client';

export default function StatusBar() {
  return (
    <div className="fixed bottom-0 left-0 right-0 h-8 bg-slate-50 border-t border-slate-200 flex items-center justify-between px-4 z-30">
      <div className="flex items-center gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          Control Plane 正常
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          Event Bus 正常 (0 积压)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          5/5 Worker 在线
        </span>
      </div>
      <span className="text-[11px] text-slate-400">
        WebSocket 已连接 · SSE 已连接 · 最后同步: 2秒前
      </span>
    </div>
  );
}
