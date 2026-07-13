"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";

import { AiAdvice } from "@/components/dashboard/ai-advice";
import { RecentQuestions } from "@/components/dashboard/recent-questions";
import { ReviewHero } from "@/components/dashboard/review-hero";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api";
import type { AnalyticsAdviceResult, DashboardResponse } from "@/types/api";

function dashboardError(error: unknown) {
  if (error instanceof ApiError && error.status === 404) return "学习概览暂不可用，请稍后重试。";
  return error instanceof ApiError ? error.body.message : "学习概览加载失败，请检查网络后重试。";
}

function adviceError(error: unknown) {
  return error instanceof ApiError ? error.body.message : "AI 建议刷新失败，请检查网络后重试。";
}

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch<DashboardResponse>("/dashboard"),
  });
  const advice = useMutation({
    mutationFn: () => apiFetch<AnalyticsAdviceResult>("/analytics/advice", { method: "POST" }),
    onSuccess: (result) => {
      queryClient.setQueryData<DashboardResponse>(["dashboard"], (previous) => previous ? {
        ...previous,
        ai_advice: result.advice,
        provider_mode: result.is_demo ? "demo" : "live",
      } : previous);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-[#4F46E5]">每日学习驾驶舱</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[#0D1B4C] sm:text-3xl">今日学习概览</h1>
          <p className="mt-2 text-sm text-[#52627F]">先完成今天最重要的复习，再整理新错题。</p>
        </div>
        <Link href="/questions/new" className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-[#4F46E5] px-4 text-sm font-semibold text-white hover:bg-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5] focus-visible:ring-offset-2">
          <Plus className="size-4" aria-hidden="true" />录入错题
        </Link>
      </div>

      {dashboard.isPending ? <div className="rounded-xl border border-[#E4E8F2] bg-white px-6 py-16 text-center text-sm text-[#52627F]" role="status">正在加载今日学习概览…</div> : null}
      {dashboard.error ? <div className="rounded-xl border border-[#FFD7DB] bg-[#FFF7F8] p-5 text-sm text-[#C33746]" role="alert"><p>{dashboardError(dashboard.error)}</p><Button className="mt-3" size="sm" variant="secondary" onClick={() => dashboard.refetch()}>重新加载</Button></div> : null}
      {dashboard.data ? (
        <>
          <ReviewHero data={dashboard.data.today_review} currentQuestion={dashboard.data.current_question} />
          <div className="grid gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <Link href="/questions/new" className="flex min-h-32 items-center gap-4 rounded-xl border border-[#CDECE2] bg-white p-5 transition-colors hover:bg-[#F7FCFA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#10B981]">
              <span className="flex size-11 items-center justify-center rounded-lg bg-[#E8F8F3] text-[#006B50]" aria-hidden="true"><Plus className="size-6" /></span>
              <span><span className="block font-semibold text-[#006B50]">快速录入</span><span className="mt-1 block text-sm leading-6 text-[#52627F]">上传截图或手动记录新错题</span></span>
            </Link>
            <AiAdvice
              advice={dashboard.data.ai_advice}
              providerMode={dashboard.data.provider_mode}
              refreshing={advice.isPending}
              error={advice.error ? adviceError(advice.error) : null}
              onRefresh={() => advice.mutate()}
            />
          </div>
          <RecentQuestions questions={dashboard.data.recent_questions} />
        </>
      ) : null}
    </div>
  );
}
