"use client";

import { CalendarDays, Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { User } from "@/types/api";

interface AppHeaderProps {
  user: User;
  onOpenNavigation: () => void;
}

export function AppHeader({ user, onOpenNavigation }: AppHeaderProps) {
  const date = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());

  return (
    <header className="flex h-20 items-center justify-between border-b border-[#E4E8F2] bg-white px-4 sm:px-8 lg:h-24 lg:px-9">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        aria-label="打开导航"
        onClick={onOpenNavigation}
      >
        <Menu className="size-5" aria-hidden="true" />
      </Button>
      <div className="hidden items-center gap-2 text-sm font-medium text-[#314568] sm:flex lg:ml-auto">
        <CalendarDays className="size-5 text-[#0D1B4C]" aria-hidden="true" />
        <time dateTime={new Date().toISOString().slice(0, 10)}>{date}</time>
      </div>
      <div className="flex items-center gap-3 text-right">
        <div className="hidden sm:block">
          <p className="text-sm font-medium text-[#0D1B4C]">{user.email}</p>
          <p className="mt-0.5 text-xs text-[#6A7893]">备考学员</p>
        </div>
        <span className="flex size-9 items-center justify-center rounded-full bg-[#EEF0FF] text-sm font-semibold text-[#4F46E5]" aria-label="当前用户">
          {user.email.slice(0, 1).toUpperCase()}
        </span>
      </div>
    </header>
  );
}
