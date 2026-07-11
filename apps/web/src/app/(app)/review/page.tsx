"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { ReviewSession } from "@/components/review/review-session";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api";
import type { TodayReviewResponse } from "@/types/api";

const reviewLimits = [10, 20, 30, 50] as const;

function reviewError(error: unknown) {
  if (error instanceof ApiError && error.status === 404) return "今日复习计划不存在，请刷新后重试。";
  return error instanceof ApiError ? error.body.message : "今日复习加载失败，请检查网络后重试。";
}

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const today = useQuery({
    queryKey: ["today-review"],
    queryFn: () => apiFetch<TodayReviewResponse>("/reviews/today"),
  });
  const settings = useMutation({
    mutationFn: (dailyReviewLimit: (typeof reviewLimits)[number]) => apiFetch<{ daily_review_limit: (typeof reviewLimits)[number] }>("/reviews/settings", {
      method: "PATCH",
      body: JSON.stringify({ daily_review_limit: dailyReviewLimit }),
    }),
    onSuccess: (updated) => {
      queryClient.setQueryData<TodayReviewResponse>(["today-review"], (previous) => previous ? { ...previous, daily_review_limit: updated.daily_review_limit } : previous);
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setStatusMessage("每日数量已更新");
    },
    onError: (error) => setStatusMessage(reviewError(error)),
  });

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-[#4F46E5]">每日复盘</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[#0D1B4C] sm:text-3xl">今日复习</h1>
          <p className="mt-2 text-sm leading-6 text-[#6A7893]">一次聚焦一道题，先回忆，再查看答案并记录掌握情况。</p>
        </div>
        <Link href="/questions" className="inline-flex h-10 items-center rounded-lg border border-[#E4E8F2] bg-white px-4 text-sm font-medium text-[#0D1B4C] hover:bg-[#F7F8FC] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">查看错题库</Link>
      </div>

      {today.data ? (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[#E4E8F2] bg-white px-4 py-3">
          <div>
            <label htmlFor="daily-review-limit" className="text-sm font-medium text-[#0D1B4C]">每日复习数量</label>
            <p className="mt-1 text-xs text-[#6A7893]">调整后从下一次生成计划开始生效。</p>
          </div>
          <select
            id="daily-review-limit"
            value={today.data.daily_review_limit}
            disabled={settings.isPending}
            onChange={(event) => {
              setStatusMessage(null);
              settings.mutate(Number(event.target.value) as (typeof reviewLimits)[number]);
            }}
            className="h-10 rounded-lg border border-[#D7DDEA] bg-white px-3 text-sm text-[#0D1B4C] outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15"
          >
            {reviewLimits.map((limit) => <option key={limit} value={limit}>{limit} 题</option>)}
          </select>
          {statusMessage ? <p className={settings.isError ? "w-full text-right text-xs text-[#C33746]" : "w-full text-right text-xs text-[#078766]"} role="status">{statusMessage}</p> : null}
        </div>
      ) : null}

      {today.isPending ? <div className="rounded-xl border border-[#E4E8F2] bg-white px-6 py-16 text-center text-sm text-[#6A7893]" role="status">正在生成今日复习计划…</div> : null}
      {today.error ? <div className="rounded-xl border border-[#FFD7DB] bg-[#FFF7F8] p-5 text-sm text-[#C33746]" role="alert"><p>{reviewError(today.error)}</p><Button className="mt-3" size="sm" variant="secondary" onClick={() => today.refetch()}>重新加载</Button></div> : null}
      {today.data ? <ReviewSession key={`${today.data.daily_review_limit}-${today.data.completed_count}-${today.data.pending.map((question) => question.id).join("-")}`} data={today.data} /> : null}
    </div>
  );
}
