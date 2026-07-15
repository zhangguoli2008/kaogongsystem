"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, RefreshCw } from "lucide-react";
import Link from "next/link";

import { DistributionList } from "@/components/analytics/distribution-list";
import { ModuleChart } from "@/components/analytics/module-chart";
import { TrendChart } from "@/components/analytics/trend-chart";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api";
import type { AnalyticsAdviceResult, AnalyticsSummary } from "@/types/api";

function analyticsError(error: unknown) {
  if (error instanceof ApiError && error.status === 404) return "统计数据暂不可用，请稍后重试。";
  return error instanceof ApiError ? error.body.message : "统计数据加载失败，请检查网络后重试。";
}

function adviceError(error: unknown) {
  return error instanceof ApiError ? error.body.message : "AI 建议刷新失败，请检查网络后重试。";
}

export default function AnalyticsPage() {
  const queryClient = useQueryClient();
  const analytics = useQuery({
    queryKey: ["analytics"],
    queryFn: () => apiFetch<AnalyticsSummary>("/analytics/summary"),
  });
  const advice = useMutation({
    mutationFn: () => apiFetch<AnalyticsAdviceResult>("/analytics/advice", { method: "POST" }),
    onSuccess: (result) => {
      queryClient.setQueryData<AnalyticsSummary>(["analytics"], (previous) => previous ? {
        ...previous,
        ai_summary: result.advice,
        is_demo: result.is_demo,
      } : previous);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-sm font-medium text-[#4F46E5]">学习诊断</p><h1 className="mt-2 text-2xl font-semibold tracking-tight text-[#0D1B4C] sm:text-3xl">数据统计</h1><p className="mt-2 text-sm leading-6 text-[#52627F]">从模块、考点、错因和趋势中找到下一步复习重点。</p></div>
        <Link href="/questions" className="inline-flex h-10 items-center rounded-lg border border-[#E4E8F2] bg-white px-4 text-sm font-medium text-[#0D1B4C] hover:bg-[#F7F8FC] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">查看错题库</Link>
      </div>

      {analytics.isPending ? <div className="rounded-xl border border-[#E4E8F2] bg-white px-6 py-16 text-center text-sm text-[#52627F]" role="status">正在汇总学习数据…</div> : null}
      {analytics.error ? <div className="rounded-xl border border-[#FFD7DB] bg-[#FFF7F8] p-5 text-sm text-[#C33746]" role="alert"><p>{analyticsError(analytics.error)}</p><Button className="mt-3" size="sm" variant="secondary" onClick={() => analytics.refetch()}>重新加载</Button></div> : null}
      {analytics.data?.total_questions === 0 ? (
        <section className="rounded-xl border border-dashed border-[#CBD3E3] bg-white px-6 py-12 text-center" aria-labelledby="analytics-empty-title">
          <h2 id="analytics-empty-title" className="text-xl font-semibold text-[#0D1B4C]">还没有可统计的错题数据</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-[#52627F]">完成错题录入后，系统会显示五大模块、知识点、错因、掌握状态和录入趋势。</p>
          <Link href="/questions/new" className="mt-6 inline-flex h-11 items-center rounded-lg bg-[#4F46E5] px-4 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5] focus-visible:ring-offset-2">录入错题</Link>
        </section>
      ) : null}
      {analytics.data && analytics.data.total_questions > 0 ? (
        <>
          <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-[#E4E8F2] bg-white p-5" aria-label="错题总览"><div><p className="text-sm text-[#52627F]">总错题数</p><p className="mt-1 text-3xl font-semibold text-[#0D1B4C]">{analytics.data.total_questions}</p></div><p className="max-w-lg text-sm leading-6 text-[#52627F]">统计按当前账号的全部错题实时汇总，复习结果会同步更新掌握状态分布。</p></section>
          <div className="grid gap-5 xl:grid-cols-2"><ModuleChart data={analytics.data.module_distribution} total={analytics.data.total_questions} /><DistributionList title="知识点错题排行" data={analytics.data.knowledge_point_ranking} /></div>
          <div className="grid gap-5 xl:grid-cols-2"><DistributionList title="错误原因分布" data={analytics.data.error_reason_distribution} /><DistributionList title="掌握状态分布" data={analytics.data.mastery_distribution} /></div>
          <TrendChart trend7d={analytics.data.trend_7d} trend30d={analytics.data.trend_30d} />
          <section className="rounded-xl border border-[#D7E2FF] bg-white p-5" aria-labelledby="analytics-ai-title"><div className="flex items-start gap-4"><span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true"><BrainCircuit className="size-6" /></span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 id="analytics-ai-title" className="font-semibold text-[#0D1B4C]">AI 薄弱点总结</h2>{analytics.data.is_demo ? <span className="rounded-md bg-[#EEF0FF] px-2 py-0.5 text-xs font-medium text-[#4F46E5]">演示模式</span> : null}</div><p className="mt-2 text-sm leading-6 text-[#52627F]">{analytics.data.ai_summary}</p>{advice.error ? <p className="mt-3 text-sm text-[#9F2636]" role="alert">{adviceError(advice.error)}</p> : null}<Button className="mt-3" size="sm" variant="ghost" disabled={advice.isPending} onClick={() => advice.mutate()} aria-label={advice.error ? "重试刷新建议" : "刷新统计建议"}><RefreshCw className="size-4" aria-hidden="true" />{advice.isPending ? "正在刷新" : advice.error ? "重试刷新" : "刷新建议"}</Button></div></div></section>
        </>
      ) : null}
    </div>
  );
}
