"use client";

import { useAppStore } from "@/stores/appStore";
import ErrorBoundary from "@/components/ui/ErrorBoundary";
import { ToastProvider } from "@/components/ui/Toast";
import TopBar from "./TopBar";
import Sidebar from "./Sidebar";
import StatusBar from "./StatusBar";
import { cn } from "@/lib/utils";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed);

  return (
    <ErrorBoundary>
      <ToastProvider>
        <div className="min-h-screen bg-slate-900 text-slate-100">
          <TopBar />
          <Sidebar />
          <main
            className={cn(
              "pt-12 pb-8 min-h-[calc(100vh-5rem)] transition-[margin] duration-200",
              sidebarCollapsed ? "ml-16" : "ml-56"
            )}
            id="app-main-content"
          >
            {children}
          </main>
          <StatusBar />
        </div>
      </ToastProvider>
    </ErrorBoundary>
  );
}
