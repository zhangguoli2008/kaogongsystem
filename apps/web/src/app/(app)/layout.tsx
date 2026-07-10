"use client";

import { useState, type ReactNode } from "react";

import { AppHeader } from "@/components/layout/app-header";
import { Sidebar } from "@/components/layout/sidebar";
import { useSession } from "@/hooks/use-session";

export function AppShell({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const session = useSession();

  if (session.isPending) {
    return <div className="grid min-h-screen place-items-center bg-[#F7F8FC] text-sm text-[#6A7893]">正在加载学习空间…</div>;
  }

  if (!session.data) {
    return null;
  }

  return (
    <div className="min-h-screen bg-[#F7F8FC]">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="min-h-screen lg:pl-60">
        <AppHeader user={session.data} onOpenNavigation={() => setSidebarOpen(true)} />
        <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-8 sm:py-8 lg:px-9 lg:py-10">{children}</main>
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
