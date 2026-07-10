"use client";

import {
  BrainCircuit,
  ChartNoAxesCombined,
  FolderOpen,
  GraduationCap,
  House,
  SquarePlus,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface NavigationItem {
  href: string;
  label: string;
  icon: LucideIcon;
  matches: (pathname: string) => boolean;
}

export const navigationItems: NavigationItem[] = [
  { href: "/dashboard", label: "首页", icon: House, matches: (pathname) => pathname === "/dashboard" },
  { href: "/questions/new", label: "错题录入", icon: SquarePlus, matches: (pathname) => pathname === "/questions/new" },
  { href: "/questions", label: "错题库", icon: FolderOpen, matches: (pathname) => pathname.startsWith("/questions") && pathname !== "/questions/new" },
  { href: "/review", label: "今日复习", icon: GraduationCap, matches: (pathname) => pathname.startsWith("/review") },
  { href: "/analytics", label: "数据统计", icon: ChartNoAxesCombined, matches: (pathname) => pathname.startsWith("/analytics") },
];

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

function SidebarContent({ onClose }: Pick<SidebarProps, "onClose">) {
  const pathname = usePathname() ?? "";

  return (
    <>
      <div className="flex h-24 items-center gap-3 px-6">
        <span className="flex size-9 items-center justify-center rounded-xl bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true">
          <BrainCircuit className="size-6" strokeWidth={2.2} />
        </span>
        <span className="text-base font-semibold tracking-tight text-[#0D1B4C]">公考错题诊断系统</span>
      </div>
      <nav aria-label="主导航" className="flex-1 space-y-2 px-3 py-5">
        {navigationItems.map(({ href, label, icon: Icon, matches }) => {
          const active = matches(pathname);
          return (
            <Link
              key={href}
              href={href}
              onClick={onClose}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex h-12 items-center gap-4 rounded-lg px-4 text-[15px] font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5] focus-visible:ring-offset-2",
                active
                  ? "bg-[#4F46E5] text-white shadow-[0_8px_18px_rgba(79,70,229,0.2)]"
                  : "text-[#24385D] hover:bg-[#F1F3F9]",
              )}
            >
              <Icon className="size-5 shrink-0" strokeWidth={2} aria-hidden="true" />
              {label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}

export function Sidebar({ open, onClose }: SidebarProps) {
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-[#E4E8F2] bg-white lg:flex">
        <SidebarContent onClose={onClose} />
      </aside>

      {open ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="关闭导航"
            className="absolute inset-0 bg-[#0D1B4C]/35"
            onClick={onClose}
          />
          <aside className="relative flex h-full w-60 flex-col bg-white shadow-xl">
            <Button
              variant="ghost"
              size="icon"
              className="absolute right-3 top-5 z-10"
              aria-label="关闭导航菜单"
              onClick={onClose}
            >
              <X className="size-5" aria-hidden="true" />
            </Button>
            <SidebarContent onClose={onClose} />
          </aside>
        </div>
      ) : null}
    </>
  );
}
