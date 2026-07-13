"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AppHeader } from "@/components/layout/app-header";
import { Sidebar } from "@/components/layout/sidebar";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiFetch } from "@/lib/api";
import { replaceDocument } from "@/lib/document-navigation";

export function AppShell({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const queryClient = useQueryClient();
  const session = useSession();
  const logout = useMutation({
    mutationFn: () => apiFetch<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      queryClient.clear();
      replaceDocument("/login");
    },
  });

  if (session.isPending) {
    return <div className="grid min-h-screen place-items-center bg-[#F7F8FC] text-sm text-[#6A7893]">正在加载学习空间…</div>;
  }

  if (session.error instanceof ApiError && session.error.status === 401) {
    return <div className="grid min-h-screen place-items-center bg-[#F7F8FC] text-sm text-[#6A7893]" role="status">正在返回登录页…</div>;
  }

  if (!session.data) {
    return null;
  }

  return (
    <div className="min-h-screen bg-[#F7F8FC]">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="min-h-screen lg:pl-60">
        <AppHeader
          user={session.data}
          onOpenNavigation={() => setSidebarOpen(true)}
          onLogout={() => logout.mutate()}
          logoutPending={logout.isPending}
        />
        {logout.isError ? (
          <p
            className="border-b border-[#F4C7CE] bg-[#FFF7F8] px-4 py-2 text-right text-sm text-[#B42336] sm:px-8 lg:px-9"
            role="alert"
          >
            退出失败，请检查网络后重试。
          </p>
        ) : null}
        <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-8 sm:py-8 lg:px-9 lg:py-10">{children}</main>
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
