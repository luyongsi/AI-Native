"use client";

import { useEffect, useState, useCallback } from "react";
import { wsClient } from "@/lib/ws";

// ---- ����״̬���� ----
interface SystemStatus {
  control_plane: { status: "healthy" | "degraded" | "down"; message?: string };
  event_bus: { status: "healthy" | "degraded" | "down"; backlog?: number; message?: string };
  workers: { total: number; online: number };
  a1_agent: { status: "ready" | "busy" | "down"; message?: string };
}

type ConnectionState = "connected" | "connecting" | "disconnected";

const statusDot = (status: string): { color: string; label: string } => {
  switch (status) {
    case "healthy":
    case "ready":
      return { color: "bg-emerald-500", label: "����" };
    case "degraded":
    case "busy":
      return { color: "bg-amber-500", label: "����" };
    case "down":
      return { color: "bg-red-500", label: "�쳣" };
    default:
      return { color: "bg-amber-500", label: "������" };
  }
};

// ---- ����״̬��ѯ Hook ----
function useSystemHealth() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [fetchState, setFetchState] = useState<ConnectionState>("connecting");

  const poll = useCallback(async () => {
    try {
      const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
      const res = await fetch(`${BASE_URL}/api/status`, {
        headers: { "Content-Type": "application/json" },
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: SystemStatus = await res.json();
      setStatus(data);
      setFetchState("connected");
    } catch {
      setFetchState("disconnected");
      // �����ϴ����ݣ������ status
    }
  }, []);

  useEffect(() => {
    poll();
    const interval = setInterval(poll, 30_000);
    return () => clearInterval(interval);
  }, [poll]);

  return { status, fetchState };
}

export default function StatusBar() {
  const { status, fetchState } = useSystemHealth();
  const [wsConnected, setWsConnected] = useState(false);

  // ��ѯ WebSocket ����״̬
  useEffect(() => {
    const check = () => setWsConnected(wsClient.isConnected);
    check();
    const interval = setInterval(check, 5_000);
    return () => clearInterval(interval);
  }, []);

  const wsState: ConnectionState = wsConnected ? "connected" : "disconnected";
  const sseState: ConnectionState = fetchState; // SSE ������ HTTP ��������

  const isLoading = status === null && fetchState === "connecting";

  return (
    <div className="fixed bottom-0 left-0 right-0 h-6 bg-slate-950 border-t border-slate-800 flex items-center justify-between px-4 z-30">
      {/* ��ࣺϵͳ���� */}
      <div className="flex items-center gap-4 text-[11px] text-slate-400">
        {isLoading ? (
          <span className="flex items-center gap-1.5 text-amber-400">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
            Connecting...
          </span>
        ) : status ? (
          <>
            {/* Control Plane */}
            <span className="flex items-center gap-1.5">
              <span
                className={`w-1.5 h-1.5 rounded-full ${statusDot(status.control_plane.status).color}`}
              />
              Control Plane {statusDot(status.control_plane.status).label}
            </span>

            {/* Event Bus */}
            <span className="flex items-center gap-1.5">
              <span
                className={`w-1.5 h-1.5 rounded-full ${statusDot(status.event_bus.status).color}`}
              />
              Event Bus {statusDot(status.event_bus.status).label}
              {status.event_bus.backlog !== undefined && (
                <span> ({status.event_bus.backlog} ��ѹ)</span>
              )}
            </span>

            {/* Workers */}
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              {status.workers.online}/{status.workers.total} Worker ����
            </span>

            {/* A1 Agent */}
            <span className="flex items-center gap-1.5">
              <span
                className={`w-1.5 h-1.5 rounded-full ${statusDot(status.a1_agent.status).color}`}
              />
              A1 Agent {statusDot(status.a1_agent.status).label}
            </span>
          </>
        ) : (
          <span className="flex items-center gap-1.5 text-amber-400">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            Connecting...
          </span>
        )}
      </div>

      {/* �Ҳࣺ����״̬ */}
      <div className="flex items-center gap-4 text-[11px]">
        <span className="flex items-center gap-1.5 text-slate-400">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              wsState === "connected" ? "bg-emerald-500" : "bg-red-500"
            }`}
          />
          WebSocket {wsState === "connected" ? "������" : "�Ͽ�"}
        </span>
        <span className="flex items-center gap-1.5 text-slate-400">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              sseState === "connected" ? "bg-emerald-500" : sseState === "connecting" ? "bg-amber-500" : "bg-red-500"
            }`}
          />
          SSE {sseState === "connected" ? "������" : sseState === "connecting" ? "������" : "�Ͽ�"}
        </span>
      </div>
    </div>
  );
}
