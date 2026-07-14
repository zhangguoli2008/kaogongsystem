"use client";

import { Bot, FilePenLine, Sparkles, Trash2 } from "lucide-react";
import Image from "next/image";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiUrl } from "@/lib/api";
import type { OcrMedia, OcrQuestion } from "@/types/api";

export type OcrLoadIntent = "edit" | "analyze";

interface OcrQuestionCardProps {
  position: number;
  question: OcrQuestion;
  sourceImageUrl: string;
  onChange: (question: OcrQuestion) => void;
  onDelete: () => void;
  onLoad: (intent: OcrLoadIntent) => void;
  onAdoptAnswer: (answer: string) => void;
  onAdoptParse: (parse: string) => void;
  draftActionsDisabled?: boolean;
}

const typeLabels: Record<OcrQuestion["question_type"], string> = {
  multiple_choice_unknown: "选择题",
  fill_blank: "填空题",
  problem_solving: "解答题",
  arithmetic: "计算题",
  unknown: "待确认题型",
};

function protectedAssetUrl(path: string | null | undefined) {
  return path?.startsWith("/uploads/") ? apiUrl(path) : null;
}

function VisualList({
  title,
  items,
  number,
  kind,
  onChange,
}: {
  title: string;
  items: OcrMedia[];
  number: string;
  kind: "图形" | "表格";
  onChange: (index: number, text: string) => void;
}) {
  if (!items.length) return null;

  return (
    <section className="mt-4" aria-label={`${number} ${title}`}>
      <h4 className="text-xs font-semibold tracking-wide text-[#6A7893]">{title}</h4>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {items.map((item, index) => {
          const imageUrl = protectedAssetUrl(item.image_url);
          return (
            <figure key={`${kind}-${item.index ?? index}`} className="overflow-hidden rounded-lg border border-[#E4E8F2] bg-white">
              {imageUrl ? (
                <Image
                  src={imageUrl}
                  alt={`${number}${kind} ${index + 1}`}
                  width={960}
                  height={640}
                  unoptimized
                  className="max-h-56 w-full object-contain"
                />
              ) : null}
              <figcaption className="border-t border-[#E8ECF4] p-2">
                <label className="sr-only" htmlFor={`${kind}-${number}-${index}`}>{number}{kind} {index + 1} 文字</label>
                <textarea
                  id={`${kind}-${number}-${index}`}
                  value={item.text ?? ""}
                  onChange={(event) => onChange(index, event.target.value)}
                  placeholder={`${kind}识别文字`}
                  className="min-h-16 w-full rounded-md border border-[#E4E8F2] px-2 py-1.5 text-xs leading-5 text-[#52627F] outline-none focus:border-[#4F46E5]"
                />
              </figcaption>
            </figure>
          );
        })}
      </div>
    </section>
  );
}

export function OcrQuestionCard({
  position,
  question,
  sourceImageUrl,
  onChange,
  onDelete,
  onLoad,
  onAdoptAnswer,
  onAdoptParse,
  draftActionsDisabled = false,
}: OcrQuestionCardProps) {
  const displayNumber = question.question_number?.trim() || String(position + 1);
  const numberLabel = `第 ${displayNumber} 题`;
  const sourceUrl = protectedAssetUrl(sourceImageUrl);
  const cropUrl = protectedAssetUrl(question.crop_image_url);

  return (
    <article className="rounded-xl border border-[#DDE3F0] bg-[#F9FAFD] p-4" aria-labelledby={`ocr-draft-${question.temporary_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={`ocr-draft-${question.temporary_id}`} className="font-semibold text-[#0D1B4C]">{numberLabel}</h3>
            <span className="rounded-md bg-[#EEF0FF] px-2 py-1 text-xs font-medium text-[#4F46E5]">{typeLabels[question.question_type]}</span>
          </div>
          <p className="mt-1 text-xs text-[#6A7893]">识别草稿不会自动保存，请核对后再载入右侧表单。</p>
        </div>
        <Button variant="ghost" size="sm" aria-label={`删除${numberLabel}`} onClick={onDelete}>
          <Trash2 className="size-4" aria-hidden="true" />
          删除
        </Button>
      </div>

      {question.warnings.length ? (
        <ul className="mt-3 rounded-lg border border-[#F5D797] bg-[#FFF9E9] px-3 py-2 text-xs leading-5 text-[#7A5A12]" aria-label={`${numberLabel}识别提醒`}>
          {question.warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      ) : null}

      <div className="mt-4">
        <label htmlFor={`ocr-stem-${question.temporary_id}`} className="text-sm font-medium text-[#0D1B4C]">题干</label>
        <textarea
          id={`ocr-stem-${question.temporary_id}`}
          aria-label={`${numberLabel}题干`}
          value={question.question_text}
          onChange={(event) => onChange({ ...question, question_text: event.target.value })}
          className="mt-2 min-h-28 w-full rounded-lg border border-[#DDE3F0] bg-white px-3 py-2.5 text-sm leading-6 text-[#0D1B4C] outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15"
        />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={`ocr-number-${question.temporary_id}`} className="text-sm font-medium text-[#0D1B4C]">题号</label>
          <Input
            id={`ocr-number-${question.temporary_id}`}
            className="mt-2"
            aria-label={`${numberLabel}题号`}
            value={question.question_number ?? ""}
            onChange={(event) => onChange({ ...question, question_number: event.target.value || null })}
          />
        </div>
        <div>
          <label htmlFor={`ocr-type-${question.temporary_id}`} className="text-sm font-medium text-[#0D1B4C]">题型</label>
          <select
            id={`ocr-type-${question.temporary_id}`}
            className="mt-2 h-11 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 text-sm text-[#0D1B4C] outline-none focus:border-[#4F46E5]"
            value={question.question_type}
            onChange={(event) => onChange({ ...question, question_type: event.target.value as OcrQuestion["question_type"] })}
          >
            {Object.entries(typeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      </div>

      {question.options.length ? (
        <fieldset className="mt-4 space-y-3">
          <legend className="text-sm font-medium text-[#0D1B4C]">选项</legend>
          {question.options.map((option, index) => {
            const optionImageUrl = protectedAssetUrl(option.image_url);
            return (
              <div key={`${option.label}-${index}`} className="rounded-lg border border-[#E4E8F2] bg-white p-3">
                <div className="flex items-center gap-2">
                  <Input
                    aria-label={`${numberLabel}选项 ${index + 1} 标签`}
                    className="w-16 shrink-0 font-semibold text-[#4F46E5]"
                    value={option.label}
                    onChange={(event) => onChange({
                      ...question,
                      options: question.options.map((candidate, candidateIndex) => (
                        candidateIndex === index ? { ...candidate, label: event.target.value } : candidate
                      )),
                    })}
                  />
                  <Input
                    aria-label={`${numberLabel}选项 ${option.label}`}
                    value={option.text}
                    onChange={(event) => onChange({
                      ...question,
                      options: question.options.map((candidate, candidateIndex) => (
                        candidateIndex === index ? { ...candidate, text: event.target.value } : candidate
                      )),
                    })}
                  />
                </div>
                {optionImageUrl ? (
                  <Image
                    src={optionImageUrl}
                    alt={`${numberLabel}选项 ${option.label} 图形`}
                    width={720}
                    height={480}
                    unoptimized
                    className="mt-3 max-h-44 w-full rounded-md border border-[#E8ECF4] object-contain"
                  />
                ) : null}
              </div>
            );
          })}
        </fieldset>
      ) : null}

      {cropUrl ? (
        <figure className="mt-4 overflow-hidden rounded-lg border border-[#E4E8F2] bg-white">
          <Image src={cropUrl} alt={`${numberLabel}裁剪图`} width={1200} height={800} unoptimized className="max-h-72 w-full object-contain" />
          <figcaption className="border-t border-[#E8ECF4] px-3 py-2 text-xs text-[#6A7893]">整题裁剪图，请与可编辑文本交叉核对</figcaption>
        </figure>
      ) : null}

      <VisualList
        title="题内图形"
        items={question.figures}
        number={numberLabel}
        kind="图形"
        onChange={(index, text) => onChange({
          ...question,
          figures: question.figures.map((item, itemIndex) => itemIndex === index ? { ...item, text } : item),
        })}
      />
      <VisualList
        title="题内表格"
        items={question.tables}
        number={numberLabel}
        kind="表格"
        onChange={(index, text) => onChange({
          ...question,
          tables: question.tables.map((item, itemIndex) => itemIndex === index ? { ...item, text } : item),
        })}
      />

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <section className="rounded-lg border border-[#E4E8F2] bg-white p-3">
          <h4 className="text-xs font-semibold text-[#6A7893]">图片中的答案（未确认）</h4>
          <Input
            className="mt-2"
            aria-label={`${numberLabel}识别答案`}
            value={question.recognized_answer ?? ""}
            placeholder="未识别到答案"
            onChange={(event) => onChange({ ...question, recognized_answer: event.target.value || null })}
          />
          {question.recognized_answer?.trim() ? (
            <Button className="mt-3" size="sm" variant="secondary" disabled={draftActionsDisabled} onClick={() => onAdoptAnswer(question.recognized_answer!.trim())}>
              采用识别答案 {question.recognized_answer.trim()}
            </Button>
          ) : null}
        </section>
        <section className="rounded-lg border border-[#E4E8F2] bg-white p-3">
          <h4 className="text-xs font-semibold text-[#6A7893]">图片中的解析（未确认）</h4>
          <textarea
            className="mt-2 min-h-24 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 py-2 text-sm leading-6 text-[#0D1B4C] outline-none focus:border-[#4F46E5]"
            aria-label={`${numberLabel}识别解析`}
            value={question.recognized_parse ?? ""}
            placeholder="未识别到解析"
            onChange={(event) => onChange({ ...question, recognized_parse: event.target.value || null })}
          />
          {question.recognized_parse?.trim() ? (
            <Button className="mt-3" size="sm" variant="secondary" disabled={draftActionsDisabled} onClick={() => onAdoptParse(question.recognized_parse!.trim())}>
              采用{numberLabel}识别解析
            </Button>
          ) : null}
        </section>
      </div>

      <details className="mt-4 rounded-lg border border-[#E4E8F2] bg-white p-3">
        <summary className="cursor-pointer text-sm font-medium text-[#52627F]">编辑 OCR 原文与分段文字</summary>
        <label htmlFor={`ocr-full-text-${question.temporary_id}`} className="mt-3 block text-xs font-medium text-[#6A7893]">OCR 完整原文</label>
        <textarea
          id={`ocr-full-text-${question.temporary_id}`}
          aria-label={`${numberLabel} OCR 完整原文`}
          value={question.full_text}
          onChange={(event) => onChange({ ...question, full_text: event.target.value })}
          className="mt-2 min-h-28 w-full rounded-lg border border-[#E4E8F2] px-3 py-2 text-sm leading-6 text-[#0D1B4C] outline-none focus:border-[#4F46E5]"
        />
        {question.question_elements.map((element, index) => (
          <div key={`${element.index ?? index}-${index}`} className="mt-3">
            <label htmlFor={`ocr-element-${question.temporary_id}-${index}`} className="text-xs font-medium text-[#6A7893]">分段文字 {index + 1}</label>
            <Input
              id={`ocr-element-${question.temporary_id}-${index}`}
              className="mt-1"
              value={element.text ?? ""}
              onChange={(event) => onChange({
                ...question,
                question_elements: question.question_elements.map((candidate, candidateIndex) => (
                  candidateIndex === index ? { ...candidate, text: event.target.value || null } : candidate
                )),
              })}
            />
          </div>
        ))}
      </details>

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-[#E1E6F0] pt-4">
        <Button size="sm" disabled={draftActionsDisabled} onClick={() => onLoad("edit")} aria-label={`载入${numberLabel}到表单`}>
          <FilePenLine className="size-4" aria-hidden="true" />
          载入表单
        </Button>
        <Button size="sm" variant="secondary" disabled={draftActionsDisabled} onClick={() => onLoad("analyze")} aria-label={`载入${numberLabel}并准备 AI 分析`}>
          <Sparkles className="size-4" aria-hidden="true" />
          保存后准备 AI 分析
        </Button>
        <span className="inline-flex items-center gap-1 text-xs text-[#6A7893]"><Bot className="size-3.5" aria-hidden="true" />需先保存错题，再使用现有 AI 分析按钮</span>
        {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer" className="ml-auto text-xs font-medium text-[#4F46E5] hover:text-[#4338CA]">查看识别原始文件</a> : null}
      </div>
    </article>
  );
}
