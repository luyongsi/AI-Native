import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Native — Mission Control",
  description: "AI 驱动的研发管理指挥室",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="bg-slate-800/50 text-slate-100 antialiased">
        {children}
      </body>
    </html>
  );
}
