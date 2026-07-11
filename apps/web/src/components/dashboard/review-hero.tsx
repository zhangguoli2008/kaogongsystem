import { ArrowRight, CheckCircle2, Clock3, FileQuestion } from "lucide-react";
import Link from "next/link";

import type { Question, TodayReviewResponse } from "@/types/api";

interface ReviewHeroProps {
  data: TodayReviewResponse;
  currentQuestion: Question | null;
}

function actionLink(href: string, label: string) {
  return (
    <Link
      href={href}
      className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-[#4F46E5] px-5 text-sm font-semibold text-white transition-colors hover:bg-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5] focus-visible:ring-offset-2"
    >
      {label}
      <ArrowRight className="size-4" aria-hidden="true" />
    </Link>
  );
}

export function ReviewHero({ data, currentQuestion }: ReviewHeroProps) {
  const total = data.total;
  const completed = Math.min(data.completed_count, total);
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
  const remainingMinutes = data.pending.length * 2;

  return (
    <section
      className="rounded-xl border border-[#DDE3F0] bg-white p-5 sm:p-7"
      aria-labelledby="today-review-title"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-4">
          <h2 id="today-review-title" className="text-2xl font-semibold tracking-tight text-[#0D1B4C]">
            今日复习
          </h2>
          <p className="text-2xl font-semibold text-[#4F46E5]">{completed} / {total}</p>
        </div>
        {total > 0 ? <span className="text-2xl font-medium text-[#4F46E5]">{percent}%</span> : null}
      </div>

      {total === 0 ? (
        <div className="mt-6 flex flex-col items-start gap-5 border-t border-[#E8ECF4] pt-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium text-[#0D1B4C]">录入错题后，系统会生成今日复习计划。</p>
            <p className="mt-2 text-sm leading-6 text-[#6A7893]">系统会优先安排未掌握、复习中和近期新增的题目。</p>
          </div>
          {actionLink("/questions/new", "录入第一道错题")}
        </div>
      ) : (
        <>
          <div
            className="mt-5 h-2.5 overflow-hidden rounded-full bg-[#EEF0F6]"
            role="progressbar"
            aria-label="今日复习进度"
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={completed}
          >
            <div className="h-full rounded-full bg-[#4F46E5]" style={{ width: `${percent}%` }} />
          </div>
          <p className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-[#6A7893]">
            <span className="inline-flex items-center gap-1.5">
              <CheckCircle2 className="size-4 text-[#10B981]" aria-hidden="true" />
              已完成 {completed} 题
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock3 className="size-4" aria-hidden="true" />
              预计还需 {remainingMinutes} 分钟
            </span>
          </p>

          {data.pending.length === 0 ? (
            <div className="mt-6 flex flex-col items-start gap-5 border-t border-[#E8ECF4] pt-6 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-lg font-semibold text-[#0D1B4C]">今日计划已完成</p>
                <p className="mt-2 text-sm text-[#6A7893]">做得不错，去统计页看看本轮复习后的变化。</p>
              </div>
              {actionLink("/analytics", "查看学习统计")}
            </div>
          ) : currentQuestion ? (
            <div className="mt-6 grid gap-5 border-t border-[#E8ECF4] pt-6 lg:grid-cols-[auto_1fr_auto] lg:items-center">
              <span className="flex size-14 items-center justify-center rounded-full bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true">
                <FileQuestion className="size-7" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-[#4F46E5]">当前题目</p>
                <p className="mt-1 font-semibold text-[#0D1B4C]">{currentQuestion.module}</p>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-[#52627F]">{currentQuestion.stem}</p>
                {currentQuestion.knowledge_points.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {currentQuestion.knowledge_points.slice(0, 3).map((point) => (
                      <span key={point} className="rounded-md bg-[#EEF0FF] px-2 py-1 text-xs font-medium text-[#4F46E5]">
                        {point}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="lg:pl-4">{actionLink("/review", "继续复习")}</div>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
