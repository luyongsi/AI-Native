import type { Metadata } from "next";
import "./globals.css";
import TopBar from "@/components/layout/TopBar";
import StatusBar from "@/components/layout/StatusBar";

export const metadata: Metadata = {
  title: "AI Native Mission Control",
  description: "AI驱动研发管理指挥舱",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="bg-slate-50 text-slate-900 antialiased">
        <TopBar />
        <main className="pt-12 pb-8 min-h-screen">
          {children}
        </main>
        <StatusBar />
      </body>
    </html>
  );
}