"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Eye, RotateCcw, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api";
import type { MasteryStatus, Question, ReviewRecord, TodayReviewResponse } from "@/types/api";

interface ReviewPayload {
  result_status: MasteryStatus;
  review_note: string | null;
}

interface ReviewSessionProps {
  data: TodayReviewResponse;
  submitReview?: (questionId: string, payload: ReviewPayload) => Promise<ReviewRecord>;
}

function submitError(error: unknown) {
  if (error instanceof ApiError && error.status === 404) return "这道错题已不存在，刷新后继续复习。";
  return error instanceof ApiError ? error.body.message : "复习结果提交失败，请检查网络后重试。";
}

function AnswerAnalysis({ question }: { question: Question }) {
  return (
    <div className="mt-6 space-y-4 border-t border-[#E8ECF4] pt-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg bg-[#FFF7F8] p-4">
          <p className="text-xs font-medium text-[#A44A55]">我的答案</p>
          <p className="mt-2 font-semibold text-[#C33746]">{question.user_answer}</p>
        </div>
        <div className="rounded-lg bg-[#F0FAF7] p-4">
          <p className="text-xs font-medium text-[#397967]">正确答案</p>
          <p className="mt-2 font-semibold text-[#006B50]">{question.correct_answer}</p>
        </div>
      </div>
      <div>
        <h3 className="font-semibold text-[#0D1B4C]">原解析</h3>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-[#52627F]">{question.original_explanation?.trim() || "暂无原解析"}</p>
      </div>
      {question.current_analysis ? (
        <div className="rounded-lg border border-[#D7E2FF] bg-[#FAFBFF] p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-[#0D1B4C]">AI 诊断</h3>
            {question.current_analysis.is_demo ? <span className="rounded-md bg-[#EEF0FF] px-2 py-0.5 text-xs font-medium text-[#4F46E5]">演示模式</span> : null}
          </div>
          <dl className="mt-3 space-y-3 text-sm leading-6">
            <div><dt className="font-medium text-[#314568]">错因分析</dt><dd className="mt-1 text-[#52627F]">{question.current_analysis.cause_analysis}</dd></div>
            <div><dt className="font-medium text-[#314568]">正确思路</dt><dd className="mt-1 text-[#52627F]">{question.current_analysis.correct_approach}</dd></div>
            <div><dt className="font-medium text-[#314568]">学习建议</dt><dd className="mt-1 text-[#52627F]">{question.current_analysis.study_advice}</dd></div>
          </dl>
        </div>
      ) : null}
    </div>
  );
}

export function ReviewSession({ data, submitReview }: ReviewSessionProps) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(data.pending);
  const [completedCount, setCompletedCount] = useState(data.completed_count);
  const [revealed, setRevealed] = useState(false);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = pending[0];

  const sendReview = submitReview ?? ((questionId: string, payload: ReviewPayload) =>
    apiFetch<ReviewRecord>(`/reviews/${questionId}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }));

  async function handleSubmit(resultStatus: MasteryStatus) {
    if (!current || submitting) return;
    setSubmitting(true);
    setError(null);
    const payload: ReviewPayload = {
      result_status: resultStatus,
      review_note: note.trim() || null,
    };
    try {
      const record = await sendReview(current.id, payload);
      const nextPending = pending.slice(1);
      const nextCompletedCount = completedCount + 1;
      setPending(nextPending);
      setCompletedCount(nextCompletedCount);
      setRevealed(false);
      setNote("");
      queryClient.setQueryData<TodayReviewResponse>(["today-review"], (previous) => previous ? {
        ...previous,
        pending: previous.pending.filter((question) => question.id !== current.id),
        completed: [record, ...previous.completed],
        completed_count: nextCompletedCount,
      } : previous);
      queryClient.setQueryData<Question>(["question", current.id], (previous) => previous ? { ...previous, mastery_status: resultStatus } : previous);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["analytics"] }),
        queryClient.invalidateQueries({ queryKey: ["questions"] }),
      ]);
    } catch (reason) {
      setError(submitError(reason));
    } finally {
      setSubmitting(false);
    }
  }

  if (!current) {
    const hasCompleted = completedCount > 0 || data.total > 0;
    return (
      <section className="rounded-xl border border-[#E4E8F2] bg-white px-6 py-12 text-center" aria-labelledby="review-finished-title">
        <CheckCircle2 className="mx-auto size-11 text-[#10B981]" aria-hidden="true" />
        <h2 id="review-finished-title" className="mt-4 text-xl font-semibold text-[#0D1B4C]">{hasCompleted ? "今日复习已完成" : "暂时没有待复习题"}</h2>
        <p className="mt-2 text-sm leading-6 text-[#52627F]">{hasCompleted ? `今天已完成 ${completedCount} 题，学习记录已同步。` : "录入错题后，系统会按掌握状态和薄弱考点安排复习。"}</p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link href={hasCompleted ? "/analytics" : "/questions/new"} className="inline-flex h-11 items-center rounded-lg bg-[#4F46E5] px-4 text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5] focus-visible:ring-offset-2">{hasCompleted ? "查看学习统计" : "录入错题"}</Link>
          <Link href="/questions" className="inline-flex h-11 items-center rounded-lg border border-[#E4E8F2] bg-white px-4 text-sm font-medium text-[#0D1B4C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">查看错题库</Link>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="review-question-title">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="font-medium text-[#4F46E5]">{completedCount} / {data.total}</p>
        <p className="text-[#52627F]">剩余 {pending.length} 题</p>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[#E9ECF3]" role="progressbar" aria-label="复习进度" aria-valuemin={0} aria-valuemax={data.total} aria-valuenow={completedCount}>
        <div className="h-full rounded-full bg-[#4F46E5]" style={{ width: `${data.total ? Math.round((completedCount / data.total) * 100) : 0}%` }} />
      </div>

      <article className="mt-6 rounded-xl border border-[#E4E8F2] bg-white p-5 sm:p-7">
        <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
          <span className="rounded-md bg-[#EEF0FF] px-2.5 py-1 text-[#4F46E5]">{current.module}</span>
          {current.knowledge_points.map((point) => <span key={point} className="rounded-md bg-[#F1F3F9] px-2.5 py-1 text-[#52627F]">{point}</span>)}
        </div>
        <h2 id="review-question-title" className="mt-5 whitespace-pre-wrap text-lg font-semibold leading-8 text-[#0D1B4C]">{current.stem}</h2>
        {current.options.length ? <ol className="mt-5 space-y-3">{current.options.map((option) => <li key={`${option.label}-${option.content}`} className="rounded-lg border border-[#E8ECF4] px-4 py-3 text-sm leading-6 text-[#314568]"><span className="mr-2 font-semibold text-[#0D1B4C]">{option.label}.</span>{option.content}</li>)}</ol> : null}
        <div className="mt-5 rounded-lg bg-[#F7F8FC] p-4"><p className="text-xs font-medium text-[#52627F]">我的答案</p><p className="mt-2 font-semibold text-[#0D1B4C]">{current.user_answer}</p></div>

        {!revealed ? (
          <Button className="mt-6 w-full sm:w-auto" onClick={() => setRevealed(true)}><Eye className="size-4" aria-hidden="true" />查看答案与解析</Button>
        ) : (
          <>
            <AnswerAnalysis question={current} />
            <div className="mt-6 border-t border-[#E8ECF4] pt-6">
              <label htmlFor="review-note" className="text-sm font-medium text-[#0D1B4C]">本次复习笔记</label>
              <textarea id="review-note" rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录本次容易忽略的步骤（可选）" className="mt-2 w-full resize-y rounded-lg border border-[#D7DDEA] bg-white px-3 py-2.5 text-sm text-[#0D1B4C] outline-none placeholder:text-[#52627F] focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15" />
              {error ? <p className="mt-3 text-sm text-[#C33746]" role="alert">{error}</p> : null}
              <div className="mt-5 grid gap-3 sm:grid-cols-3" aria-label="选择本次掌握状态">
                <Button variant="secondary" disabled={submitting} onClick={() => handleSubmit("未掌握")}><XCircle className="size-4 text-[#EF5D68]" aria-hidden="true" />仍未掌握</Button>
                <Button variant="secondary" disabled={submitting} onClick={() => handleSubmit("复习中")}><RotateCcw className="size-4 text-[#D98200]" aria-hidden="true" />复习中</Button>
                <Button disabled={submitting} onClick={() => handleSubmit("已掌握")}><CheckCircle2 className="size-4" aria-hidden="true" />已掌握</Button>
              </div>
            </div>
          </>
        )}
      </article>
    </section>
  );
}
