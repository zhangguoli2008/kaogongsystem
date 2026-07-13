"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, RefreshCw, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api";
import type { Analysis, Question } from "@/types/api";

interface AnalysisPanelProps {
  question: Question;
}

const providerMessages: Record<string, string> = {
  provider_timeout: "AI 分析服务响应超时，请稍后重新分析",
  provider_connection_error: "AI 分析服务连接失败，请稍后重新分析",
  provider_rate_limited: "AI 分析服务请求过于频繁，请稍后再试",
  provider_invalid_response: "AI 分析服务返回内容无效，请重新分析",
  provider_api_error: "AI 分析服务暂时不可用，请稍后重新分析",
};

function stableErrorMessage(code?: string | null) {
  return code ? providerMessages[code] ?? providerMessages.provider_api_error : providerMessages.provider_api_error;
}

export function AnalysisPanel({ question }: AnalysisPanelProps) {
  const queryClient = useQueryClient();

  const analyze = useMutation({
    mutationFn: () => apiFetch<Analysis>(`/questions/${question.id}/analyze`, { method: "POST" }),
    onSuccess: (result) => {
      queryClient.setQueryData<Question>(["question", question.id], (current) => current ? {
        ...current,
        current_analysis: result,
        current_analysis_id: result.id,
        analysis_status: "已完成",
        analysis_error_code: null,
        knowledge_points: result.knowledge_points,
        error_reason: result.suggested_error_reason,
      } : current);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
    },
  });

  const analysis = analyze.data ?? question.current_analysis ?? null;
  const errorCode = analyze.error
    ? analyze.error instanceof ApiError ? analyze.error.body.code : "provider_api_error"
    : analyze.data
      ? null
      : question.analysis_status === "失败"
        ? question.analysis_error_code ?? "provider_api_error"
        : null;
  const isFailed = Boolean(errorCode);

  return (
    <section className="rounded-xl border border-[#DDE4FF] bg-white p-5 sm:p-6" aria-labelledby="analysis-title">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#E8ECF4] pb-5">
        <div className="flex gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true"><Bot className="size-5" /></span>
          <div>
            <h2 id="analysis-title" className="text-lg font-semibold text-[#0D1B4C]">AI 诊断</h2>
            <p className="mt-1 text-sm text-[#6A7893]">分析只会在你主动点击后发送已保存的题目内容。</p>
          </div>
        </div>
        <Button onClick={() => analyze.mutate()} disabled={analyze.isPending}>
          {analysis || isFailed ? <RefreshCw className="size-4" aria-hidden="true" /> : <Sparkles className="size-4" aria-hidden="true" />}
          {analyze.isPending ? "正在分析…" : analysis || isFailed ? "重新分析" : "开始分析"}
        </Button>
      </div>

      {isFailed ? <div className="mt-5 rounded-lg border border-[#FFD7DB] bg-[#FFF7F8] px-4 py-3 text-sm text-[#C33746]" role="alert">{stableErrorMessage(errorCode)}</div> : null}

      {analysis ? (
        <div className="mt-5 space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            {analysis.is_demo ? <span className="rounded-md bg-[#EEF0FF] px-2 py-1 text-xs font-medium text-[#4F46E5]">演示模式</span> : null}
            <span className="text-xs text-[#6A7893]">{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(analysis.created_at))}</span>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg bg-[#F7F8FC] p-4"><h3 className="text-sm font-semibold text-[#0D1B4C]">错因诊断</h3><p className="mt-2 text-sm leading-6 text-[#52627F]">{analysis.cause_analysis}</p></div>
            <div className="rounded-lg bg-[#F7F8FC] p-4"><h3 className="text-sm font-semibold text-[#0D1B4C]">正确思路</h3><p className="mt-2 text-sm leading-6 text-[#52627F]">{analysis.correct_approach}</p></div>
          </div>
          <div><h3 className="text-sm font-semibold text-[#0D1B4C]">建议复习的知识点</h3><div className="mt-2 flex flex-wrap gap-2">{analysis.knowledge_points.map((point) => <span key={point} className="rounded-md bg-[#EEF0FF] px-2 py-1 text-xs font-medium text-[#4F46E5]">{point}</span>)}</div></div>
          <div><h3 className="text-sm font-semibold text-[#0D1B4C]">学习建议</h3><p className="mt-2 text-sm leading-6 text-[#52627F]">{analysis.study_advice}</p></div>
        </div>
      ) : !isFailed ? <p className="mt-5 rounded-lg bg-[#F7F8FC] px-4 py-4 text-sm leading-6 text-[#6A7893]">尚未生成 AI 诊断。请先确认并保存题目，再手动开始分析。</p> : null}
    </section>
  );
}
