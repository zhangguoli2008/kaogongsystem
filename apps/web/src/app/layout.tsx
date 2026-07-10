import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/lib/query-client";

export const metadata: Metadata = {
  title: {
    default: "公考错题诊断系统",
    template: "%s | 公考错题诊断系统",
  },
  description: "用 AI 诊断错题，建立可持续的公考复习闭环。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full">
      <body className="min-h-full">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
