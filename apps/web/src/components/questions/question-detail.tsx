"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileText } from "lucide-react";
import Link from "next/link";
import Image from "next/image";

import { AnalysisPanel } from "@/components/questions/analysis-panel";
import { QuestionForm } from "@/components/questions/question-form";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch, apiUrl } from "@/lib/api";
import type { Question, QuestionOcrMedia, ReviewRecordPage } from "@/types/api";

interface QuestionDetailProps {
  id: string;
}

function detailError(error: unknown) {
  if (error instanceof ApiError && error.status === 404) return "这道错题不存在，或你没有访问权限。";
  return error instanceof ApiError ? error.body.message : "错题详情加载失败，请检查网络后重试";
}

function displayText(value: string | null | undefined, fallback = "暂无内容") {
  return value?.trim() || fallback;
}

function protectedUploadUrl(assetId: string) {
  return apiUrl(`/uploads/${encodeURIComponent(assetId)}`);
}

function OcrMediaGrid({
  title,
  items,
  questionNumber,
  kind,
}: {
  title: string;
  items: QuestionOcrMedia[];
  questionNumber: string;
  kind: "图形" | "表格";
}) {
  const visible = items.filter((item) => item.asset || item.text?.trim());
  if (!visible.length) return null;
  return (
    <section aria-label={title}>
      <h3 className="text-sm font-semibold text-[#52627F]">{title}</h3>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {visible.map((item, index) => (
          <figure key={`${kind}-${item.index ?? index}`} className="overflow-hidden rounded-lg border border-[#E4E8F2] bg-[#F7F8FC]">
            {item.asset ? (
              <Image
                src={protectedUploadUrl(item.asset.asset_id)}
                alt={`${questionNumber}${kind} ${index + 1}`}
                width={960}
                height={640}
                unoptimized
                className="max-h-64 w-full object-contain"
              />
            ) : <p className="px-3 py-5 text-sm text-[#6A7893]">该素材未生成裁剪图，请结合原始文件核对。</p>}
            {item.text ? <figcaption className="border-t border-[#E4E8F2] bg-white px-3 py-2 text-xs leading-5 text-[#52627F]">{item.text}</figcaption> : null}
          </figure>
        ))}
      </div>
    </section>
  );
}

function OcrVisualContext({ question }: { question: Question }) {
  const metadata = question.ocr_metadata;
  if (!metadata) return null;
  const numberLabel = `第 ${metadata.question_number?.trim() || "当前"} 题`;
  const optionAssets = metadata.options.filter((option) => option.asset);

  return (
    <section className="rounded-xl border border-[#E4E8F2] bg-white p-5 sm:p-6" aria-labelledby="ocr-visual-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="ocr-visual-title" className="text-base font-semibold text-[#0D1B4C]">OCR 原始视觉材料</h2>
          <p className="mt-1 text-sm leading-6 text-[#6A7893]">以下内容保留识别来源，OCR 答案与解析未自动写入正式字段。</p>
        </div>
        <a
          href={protectedUploadUrl(metadata.source.asset_id)}
          target="_blank"
          rel="noreferrer"
          className="text-sm font-medium text-[#4F46E5] hover:text-[#4338CA]"
        >
          查看 OCR 原始文件
        </a>
      </div>

      {metadata.warnings.length ? (
        <ul className="mt-4 rounded-lg border border-[#F5D797] bg-[#FFF9E9] px-4 py-3 text-sm leading-6 text-[#7A5A12]" aria-label="OCR 核对提醒">
          {metadata.warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      ) : null}

      <div className="mt-5 space-y-5">
        {metadata.crop ? (
          <figure className="overflow-hidden rounded-lg border border-[#E4E8F2] bg-[#F7F8FC]">
            <Image
              src={protectedUploadUrl(metadata.crop.asset_id)}
              alt={`${numberLabel}裁剪图`}
              width={1200}
              height={800}
              unoptimized
              className="max-h-96 w-full object-contain"
            />
            <figcaption className="border-t border-[#E4E8F2] bg-white px-3 py-2 text-xs text-[#6A7893]">识别时保存的整题裁剪图</figcaption>
          </figure>
        ) : null}

        <OcrMediaGrid title="题内图形" items={metadata.figures} questionNumber={numberLabel} kind="图形" />
        <OcrMediaGrid title="题内表格" items={metadata.tables} questionNumber={numberLabel} kind="表格" />

        {optionAssets.length ? (
          <section aria-label="选项图形">
            <h3 className="text-sm font-semibold text-[#52627F]">选项图形</h3>
            <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {optionAssets.map((option) => (
                <figure key={option.label} className="overflow-hidden rounded-lg border border-[#E4E8F2] bg-[#F7F8FC]">
                  <Image
                    src={protectedUploadUrl(option.asset!.asset_id)}
                    alt={`${numberLabel}选项 ${option.label} 图形`}
                    width={720}
                    height={480}
                    unoptimized
                    className="max-h-48 w-full object-contain"
                  />
                  <figcaption className="border-t border-[#E4E8F2] bg-white px-3 py-2 text-xs font-semibold text-[#52627F]">选项 {option.label}</figcaption>
                </figure>
              ))}
            </div>
          </section>
        ) : null}

        <dl className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-lg border border-[#E4E8F2] bg-[#F7F8FC] p-4">
            <dt className="text-xs font-semibold text-[#6A7893]">OCR 识别答案（未确认）</dt>
            <dd className="mt-2 whitespace-pre-wrap text-sm text-[#0D1B4C]">{displayText(metadata.recognized_answer, "未识别到答案")}</dd>
          </div>
          <div className="rounded-lg border border-[#E4E8F2] bg-[#F7F8FC] p-4">
            <dt className="text-xs font-semibold text-[#6A7893]">OCR 识别解析（未确认）</dt>
            <dd className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#0D1B4C]">{displayText(metadata.recognized_parse, "未识别到解析")}</dd>
          </div>
        </dl>

        <details className="rounded-lg border border-[#E4E8F2] px-4 py-3">
          <summary className="cursor-pointer text-sm font-medium text-[#52627F]">查看保存的 OCR 完整原文</summary>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-[#314568]">{metadata.full_text}</p>
        </details>
      </div>
    </section>
  );
}

export function QuestionDetail({ id }: QuestionDetailProps) {
  const queryClient = useQueryClient();
  const [historyPage, setHistoryPage] = useState(1);
  const detail = useQuery({
    queryKey: ["question", id],
    queryFn: () => apiFetch<Question>(`/questions/${id}`),
  });
  const history = useQuery({
    queryKey: ["question-reviews", id, historyPage],
    queryFn: () => apiFetch<ReviewRecordPage>(`/reviews/questions/${id}?page=${historyPage}&page_size=10`),
    enabled: Boolean(detail.data),
  });

  if (detail.isPending) {
    return <div className="rounded-xl border border-[#E4E8F2] bg-white px-6 py-14 text-center text-sm text-[#6A7893]" role="status">正在加载错题详情…</div>;
  }

  if (detail.error || !detail.data) {
    return <div className="rounded-xl border border-[#FFD7DB] bg-[#FFF7F8] px-5 py-5 text-sm text-[#C33746]" role="alert"><p>{detailError(detail.error)}</p><div className="mt-4 flex gap-3"><Button variant="secondary" size="sm" onClick={() => detail.refetch()}>重新加载</Button><Link href="/questions" className="inline-flex h-9 items-center rounded-lg px-3 text-sm font-medium text-[#4F46E5] hover:bg-[#EEF0FF]">返回错题库</Link></div></div>;
  }

  const question = detail.data;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/questions" className="inline-flex items-center gap-1 text-sm font-medium text-[#4F46E5] hover:text-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]"><ArrowLeft className="size-4" aria-hidden="true" />返回错题库</Link>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-[#0D1B4C] sm:text-3xl">错题详情</h1>
          <p className="mt-2 text-sm text-[#6A7893]">{question.exam_type} · {question.module} · {new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(new Date(question.created_at))}</p>
        </div>
        <span className="rounded-md bg-[#F1F3F9] px-2.5 py-1.5 text-sm font-medium text-[#52627F]">{question.mastery_status}</span>
      </div>

      <section className="rounded-xl border border-[#E4E8F2] bg-white p-5 sm:p-6" aria-labelledby="detail-question-title">
        <div className="flex gap-3"><span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true"><FileText className="size-5" /></span><div><h2 id="detail-question-title" className="text-lg font-semibold text-[#0D1B4C]">题目</h2><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-[#314568]">{question.stem}</p></div></div>
        {question.options.length ? <ol className="mt-5 space-y-2 pl-13 text-sm leading-6 text-[#52627F]">{question.options.map((option) => <li key={`${option.label}-${option.content}`}><span className="mr-2 font-semibold text-[#0D1B4C]">{option.label}.</span>{option.content}</li>)}</ol> : null}
      </section>

      <section className="grid gap-4 sm:grid-cols-2" aria-labelledby="detail-answer-title">
        <div className="rounded-xl border border-[#E4E8F2] bg-white p-5"><h2 id="detail-answer-title" className="text-base font-semibold text-[#0D1B4C]">答案</h2><dl className="mt-4 space-y-3 text-sm"><div><dt className="text-[#6A7893]">我的答案</dt><dd className="mt-1 font-medium text-[#D84755]">{question.user_answer}</dd></div><div><dt className="text-[#6A7893]">正确答案</dt><dd className="mt-1 font-medium text-[#079976]">{question.correct_answer}</dd></div></dl></div>
        <div className="rounded-xl border border-[#E4E8F2] bg-white p-5"><h2 className="text-base font-semibold text-[#0D1B4C]">原解析</h2><p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-[#52627F]">{displayText(question.original_explanation)}</p></div>
      </section>

      <OcrVisualContext question={question} />

      <AnalysisPanel question={question} />

      <section className="rounded-xl border border-[#E4E8F2] bg-white p-5 sm:p-6" aria-labelledby="notes-title"><h2 id="notes-title" className="text-base font-semibold text-[#0D1B4C]">个人笔记</h2><p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-[#52627F]">{displayText(question.notes, "暂无个人笔记，可在下方编辑区补充。")}</p></section>
      <section className="rounded-xl border border-[#E4E8F2] bg-white p-5 sm:p-6" aria-labelledby="review-history-title">
        <h2 id="review-history-title" className="text-base font-semibold text-[#0D1B4C]">复习记录</h2>
        {history.isPending ? <p className="mt-3 text-sm leading-6 text-[#6A7893]" role="status">正在加载复习记录…</p> : null}
        {history.error ? (
          <div className="mt-3 rounded-lg border border-[#FFD7DB] bg-[#FFF7F8] px-4 py-3 text-sm text-[#C33746]" role="alert">
            <p>复习记录加载失败，请稍后重试</p>
            <Button className="mt-3" size="sm" variant="secondary" onClick={() => history.refetch()}>重新加载复习记录</Button>
          </div>
        ) : null}
        {history.data?.items.length === 0 ? <p className="mt-3 text-sm leading-6 text-[#6A7893]">暂无复习记录。完成今日复习后，系统会保存本次结果和笔记。</p> : null}
        {history.data?.items.length ? (
          <ol className="mt-4 divide-y divide-[#E8ECF4]">
            {history.data.items.map((record) => (
              <li key={record.id} className="py-4 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="rounded-md bg-[#F1F3F9] px-2 py-1 text-xs font-medium text-[#52627F]">{record.result_status}</span>
                  <time className="text-xs text-[#6A7893]" dateTime={record.reviewed_at}>
                    {new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(record.reviewed_at))}
                  </time>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#52627F]">{displayText(record.review_note, "本次复习未填写笔记")}</p>
              </li>
            ))}
          </ol>
        ) : null}
        {history.data && history.data.total > history.data.page_size ? (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[#E8ECF4] pt-4 text-sm text-[#6A7893]" aria-label="复习记录分页">
            <span>第 {history.data.page} / {Math.ceil(history.data.total / history.data.page_size)} 页，共 {history.data.total} 条</span>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" aria-label="上一页复习记录" disabled={history.data.page <= 1} onClick={() => setHistoryPage((page) => page - 1)}>上一页</Button>
              <Button size="sm" variant="secondary" aria-label="下一页复习记录" disabled={history.data.page * history.data.page_size >= history.data.total} onClick={() => setHistoryPage((page) => page + 1)}>下一页</Button>
            </div>
          </div>
        ) : null}
      </section>

      <QuestionForm mode="manual" question={question} onSaved={(saved) => queryClient.setQueryData(["question", id], saved)} />
    </div>
  );
}
