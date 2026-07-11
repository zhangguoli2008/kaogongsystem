"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { QuestionFilters } from "@/components/questions/question-filters";
import { QuestionTable } from "@/components/questions/question-table";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api";
import type { QuestionPage } from "@/types/api";

function requestParams(searchParams: URLSearchParams) {
  const params = new URLSearchParams(searchParams.toString());
  params.set("page", params.get("page") || "1");
  params.set("page_size", "20");
  const createdFrom = params.get("created_from");
  const createdTo = params.get("created_to");
  if (createdFrom) params.set("created_from", `${createdFrom}T00:00:00.000Z`);
  if (createdTo) params.set("created_to", `${createdTo}T23:59:59.999Z`);
  return params.toString();
}

function queryError(error: unknown) {
  return error instanceof ApiError ? error.body.message : "错题列表加载失败，请检查网络后重试";
}

export function QuestionLibrary() {
  const searchParams = useSearchParams();
  const pathname = usePathname() || "/questions";
  const router = useRouter();
  const search = searchParams.toString();
  const list = useQuery({
    queryKey: ["questions", search],
    queryFn: () => apiFetch<QuestionPage>(`/questions?${requestParams(new URLSearchParams(search))}`),
  });

  function changePage(page: number) {
    const params = new URLSearchParams(search);
    params.set("page", String(page));
    router.replace(`${pathname}?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-[#4F46E5]">错题管理</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[#0D1B4C] sm:text-3xl">错题库</h1>
          <p className="mt-2 text-sm leading-6 text-[#6A7893]">筛选、整理并回顾每一道需要攻克的错题。</p>
        </div>
        <Link href="/questions/new" className="inline-flex h-11 items-center justify-center gap-2 rounded-lg border border-transparent bg-[#4F46E5] px-4 text-sm font-medium text-white transition-colors hover:bg-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5] focus-visible:ring-offset-2">
          <Plus className="size-4" aria-hidden="true" />
          录入错题
        </Link>
      </div>

      <QuestionFilters />
      {list.isPending ? <div className="rounded-xl border border-[#E4E8F2] bg-white px-6 py-14 text-center text-sm text-[#6A7893]" role="status">正在加载错题库…</div> : null}
      {list.error ? <div className="rounded-xl border border-[#FFD7DB] bg-[#FFF7F8] px-5 py-4 text-sm text-[#C33746]" role="alert"><p>{queryError(list.error)}</p><Button className="mt-3" size="sm" variant="secondary" onClick={() => list.refetch()}>重新加载</Button></div> : null}
      {list.data ? <>
        <QuestionTable items={list.data.items} />
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-[#6A7893]">
          <p>共 {list.data.total} 道错题</p>
          <div className="flex items-center gap-2" aria-label="错题库分页">
            <Button size="sm" variant="secondary" disabled={list.data.page <= 1} onClick={() => changePage(list.data.page - 1)}>上一页</Button>
            <span>第 {list.data.page} / {Math.max(1, Math.ceil(list.data.total / list.data.page_size))} 页</span>
            <Button size="sm" variant="secondary" disabled={list.data.page * list.data.page_size >= list.data.total} onClick={() => changePage(list.data.page + 1)}>下一页</Button>
          </div>
        </div>
      </> : null}
    </div>
  );
}
