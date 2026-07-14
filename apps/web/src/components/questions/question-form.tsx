"use client";

import { useEffect, useRef, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { Plus, Save, Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ImageOcrPanel } from "@/components/questions/image-ocr-panel";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api";
import {
  errorReasons,
  examModules,
  examTypes,
  masteryStatuses,
  type ErrorReason,
  type ExamModule,
  type ExamType,
  type MasteryStatus,
  type OcrQuestion,
  type OcrResult,
  type Question,
  type QuestionInput,
  type QuestionOcrMetadata,
  type QuestionOption,
} from "@/types/api";

export interface QuestionFormValues {
  exam_type: ExamType;
  module: ExamModule;
  stem: string;
  options: QuestionOption[];
  user_answer: string;
  correct_answer: string;
  original_explanation: string;
  source: string;
  notes: string;
  image_path: string;
  ocr_raw_text: string;
  knowledge_points_text: string;
  error_reason: ErrorReason | "";
  mastery_status: MasteryStatus;
}

interface QuestionSaveSubmission {
  values: QuestionFormValues;
  ocrMetadata: QuestionOcrMetadata | null;
  ocrDraftId: string | null;
  removeOcrDraftAfterSave: (() => void) | null;
  prepareAiAfterSave: boolean;
}

interface QuestionFormProps {
  mode: "image" | "manual";
  question?: Question;
  onSaved?: (question: Question) => void;
}

const defaultOptions: QuestionOption[] = ["A", "B", "C", "D"].map((label) => ({ label, content: "" }));

function valuesFor(question?: Question): QuestionFormValues {
  return {
    exam_type: question?.exam_type ?? "国考",
    module: question?.module ?? "言语理解",
    stem: question?.stem ?? "",
    options: question?.options.length ? question.options : defaultOptions,
    user_answer: question?.user_answer ?? "",
    correct_answer: question?.correct_answer ?? "",
    original_explanation: question?.original_explanation ?? "",
    source: question?.source ?? "",
    notes: question?.notes ?? "",
    image_path: question?.image_path ?? "",
    ocr_raw_text: question?.ocr_raw_text ?? "",
    knowledge_points_text: question?.knowledge_points.join("、") ?? "",
    error_reason: question?.error_reason ?? "",
    mastery_status: question?.mastery_status ?? "未掌握",
  };
}

function fieldClassName() {
  return "min-h-28 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 py-2.5 text-sm text-[#0D1B4C] outline-none placeholder:text-[#94A0B8] focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15";
}

function apiMessage(error: unknown) {
  return error instanceof ApiError ? error.body.message : "保存失败，请检查网络后重试";
}

function nextOptionLabel(options: QuestionOption[]) {
  const index = options.length;
  return String.fromCharCode("A".charCodeAt(0) + index);
}

function ocrMetadataFor(question: OcrQuestion, result: OcrResult): QuestionOcrMetadata {
  return {
    source: { asset_id: result.source.file_id },
    question_number: question.question_number,
    question_type: question.question_type,
    full_text: question.full_text,
    question_elements: question.question_elements,
    coord: question.coord,
    crop: question.crop_asset_id ? { asset_id: question.crop_asset_id } : null,
    figures: question.figures.map((item) => ({
      index: item.index,
      text: item.text,
      coord: item.coord,
      asset: item.asset_id ? { asset_id: item.asset_id } : null,
    })),
    tables: question.tables.map((item) => ({
      index: item.index,
      text: item.text,
      coord: item.coord,
      asset: item.asset_id ? { asset_id: item.asset_id } : null,
    })),
    options: question.options.map((option) => ({
      label: option.label,
      coord: option.coord,
      asset: option.asset_id ? { asset_id: option.asset_id } : null,
    })),
    recognized_answer: question.recognized_answer,
    recognized_parse: question.recognized_parse,
    warnings: [...new Set([...result.warnings, ...question.warnings])],
  };
}

function formHasUserContent(values: QuestionFormValues) {
  return Boolean(
    values.stem.trim() ||
    values.options.some((option) => option.content.trim()) ||
    values.user_answer.trim() ||
    values.correct_answer.trim() ||
    values.original_explanation.trim() ||
    values.notes.trim() ||
    values.ocr_raw_text.trim(),
  );
}

function valuesAfterImageSave(values: QuestionFormValues): QuestionFormValues {
  return {
    ...valuesFor(),
    exam_type: values.exam_type,
    module: values.module,
    source: values.source,
  };
}

export function QuestionForm({ mode, question, onSaved }: QuestionFormProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const {
    control,
    register,
    handleSubmit,
    reset,
    getValues,
    setValue,
    setError,
    clearErrors,
    formState: { errors, isDirty },
  } = useForm<QuestionFormValues>({ defaultValues: valuesFor(question) });
  const options = useFieldArray({ control, name: "options" });
  const loadedQuestionId = useRef(question?.id);
  const [loadedOcrDraft, setLoadedOcrDraft] = useState<{
    temporaryId: string;
    removeAfterSave: () => void;
  } | null>(null);
  const [ocrMetadata, setOcrMetadata] = useState<QuestionOcrMetadata | null>(question?.ocr_metadata ?? null);
  const [prepareAiAfterSave, setPrepareAiAfterSave] = useState(false);
  const [lastSaved, setLastSaved] = useState<{ question: Question; prepareAi: boolean } | null>(null);

  useEffect(() => {
    if (loadedQuestionId.current === question?.id) return;
    loadedQuestionId.current = question?.id;
    setLoadedOcrDraft(null);
    setOcrMetadata(question?.ocr_metadata ?? null);
    setPrepareAiAfterSave(false);
    setLastSaved(null);
    reset(valuesFor(question));
  }, [question, reset]);

  const saveQuestion = useMutation({
    mutationFn: (submission: QuestionSaveSubmission) => {
      const { values } = submission;
      const payload: QuestionInput = {
        exam_type: values.exam_type,
        module: values.module,
        stem: values.stem.trim(),
        options: values.options
          .map((option) => ({ label: option.label.trim(), content: option.content.trim() }))
          .filter((option) => option.label && option.content),
        user_answer: values.user_answer.trim(),
        correct_answer: values.correct_answer.trim(),
        original_explanation: values.original_explanation.trim() || null,
        source: values.source.trim() || null,
        notes: values.notes.trim() || null,
        image_path: values.image_path || null,
        ocr_raw_text: values.ocr_raw_text || null,
        ocr_metadata: submission.ocrMetadata,
        knowledge_points: values.knowledge_points_text.split(/[、,，]/).map((value) => value.trim()).filter(Boolean),
        error_reason: values.error_reason || null,
        mastery_status: values.mastery_status,
      };
      const path = question ? `/questions/${question.id}` : "/questions";
      return apiFetch<Question>(path, {
        method: question ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: (saved, submission) => {
      queryClient.setQueryData(["question", saved.id], saved);
      queryClient.invalidateQueries({ queryKey: ["questions"] });
      onSaved?.(saved);
      if (!question) {
        if (mode === "image") {
          submission.removeOcrDraftAfterSave?.();
          setLastSaved({
            question: saved,
            prepareAi: submission.prepareAiAfterSave,
          });
          if (loadedOcrDraft?.temporaryId === submission.ocrDraftId) {
            setLoadedOcrDraft(null);
            setOcrMetadata(null);
            setPrepareAiAfterSave(false);
            reset(valuesAfterImageSave(submission.values));
          }
        } else {
          router.push(`/questions/${saved.id}`);
        }
      }
    },
    onError: (error) => {
      if (!(error instanceof ApiError) || !error.body.field_errors) return;
      const supportedFields = new Set<keyof QuestionFormValues>([
        "exam_type",
        "module",
        "stem",
        "options",
        "user_answer",
        "correct_answer",
        "original_explanation",
        "source",
        "notes",
        "image_path",
        "ocr_raw_text",
        "error_reason",
        "mastery_status",
      ]);
      for (const [field, messages] of Object.entries(error.body.field_errors)) {
        if (supportedFields.has(field as keyof QuestionFormValues) && messages[0]) {
          setError(field as keyof QuestionFormValues, { type: "server", message: messages[0] });
        }
      }
    },
  });

  function loadOcrQuestion(
    ocrQuestion: OcrQuestion,
    result: OcrResult,
    intent: "edit" | "analyze",
    removeAfterSave: () => void,
  ) {
    if (saveQuestion.isPending) return false;
    const currentValues = getValues();
    const wouldOverwrite = isDirty || loadedOcrDraft !== null || formHasUserContent(currentValues);
    if (wouldOverwrite && !window.confirm("当前表单有未保存内容，载入识别题目会覆盖题干和选项，确定继续吗？")) {
      return false;
    }

    reset({
      ...currentValues,
      stem: ocrQuestion.question_text,
      options: ocrQuestion.options
        .map((option) => ({ label: option.label, content: option.text }))
        .filter((option) => option.label.trim() && option.content.trim()),
      image_path: result.source.image_url,
      ocr_raw_text: ocrQuestion.full_text,
    });
    setLoadedOcrDraft({
      temporaryId: ocrQuestion.temporary_id,
      removeAfterSave,
    });
    setOcrMetadata(ocrMetadataFor(ocrQuestion, result));
    setPrepareAiAfterSave(intent === "analyze");
    return true;
  }

  function adoptOcrAnswer(
    ocrQuestion: OcrQuestion,
    result: OcrResult,
    removeAfterSave: () => void,
  ) {
    if (loadedOcrDraft?.temporaryId !== ocrQuestion.temporary_id && !loadOcrQuestion(ocrQuestion, result, "edit", removeAfterSave)) return;
    setLoadedOcrDraft({ temporaryId: ocrQuestion.temporary_id, removeAfterSave });
    setOcrMetadata(ocrMetadataFor(ocrQuestion, result));
    if (ocrQuestion.recognized_answer?.trim()) {
      setValue("correct_answer", ocrQuestion.recognized_answer.trim(), { shouldDirty: true });
    }
  }

  function adoptOcrParse(
    ocrQuestion: OcrQuestion,
    result: OcrResult,
    removeAfterSave: () => void,
  ) {
    if (loadedOcrDraft?.temporaryId !== ocrQuestion.temporary_id && !loadOcrQuestion(ocrQuestion, result, "edit", removeAfterSave)) return;
    setLoadedOcrDraft({ temporaryId: ocrQuestion.temporary_id, removeAfterSave });
    setOcrMetadata(ocrMetadataFor(ocrQuestion, result));
    if (ocrQuestion.recognized_parse?.trim()) {
      setValue("original_explanation", ocrQuestion.recognized_parse.trim(), { shouldDirty: true });
    }
  }

  function submitQuestion(values: QuestionFormValues) {
    clearErrors();
    saveQuestion.mutate({
      values,
      ocrMetadata,
      ocrDraftId: loadedOcrDraft?.temporaryId ?? null,
      removeOcrDraftAfterSave: loadedOcrDraft?.removeAfterSave ?? null,
      prepareAiAfterSave,
    });
  }

  return (
    <div className={mode === "image" ? "grid gap-6 xl:grid-cols-[minmax(19rem,0.8fr)_minmax(0,1.2fr)]" : "mx-auto max-w-4xl"}>
      {mode === "image" ? (
        <ImageOcrPanel
          draftActionsDisabled={saveQuestion.isPending}
          onLoadQuestion={loadOcrQuestion}
          onAdoptAnswer={adoptOcrAnswer}
          onAdoptParse={adoptOcrParse}
        />
      ) : null}
      <form className="rounded-xl border border-[#E4E8F2] bg-white p-5 sm:p-6" noValidate onSubmit={handleSubmit(submitQuestion)}>
        <fieldset className="contents" disabled={saveQuestion.isPending}>
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#E8ECF4] pb-5">
          <div>
            <h2 className="text-lg font-semibold text-[#0D1B4C]">{question ? "编辑错题" : "题目内容"}</h2>
            <p className="mt-1 text-sm text-[#6A7893]">考试类型、考试模块、题干和答案为必填项；保存后可在详情页单独进行 AI 分析。</p>
          </div>
          {mode === "image" ? <span className="rounded-md bg-[#EEF0FF] px-2 py-1 text-xs font-medium text-[#4F46E5]">识别结果可编辑</span> : null}
        </div>

        {prepareAiAfterSave ? (
          <p className="mt-5 rounded-lg border border-[#D9DDFE] bg-[#F5F5FF] px-4 py-3 text-sm leading-6 text-[#4338CA]" role="status">
            已准备 AI 分析：请先保存这道错题，进入详情页后再点击现有“开始分析”按钮。
          </p>
        ) : null}

        {lastSaved ? (
          <div className="mt-5 rounded-lg border border-[#BDE7D8] bg-[#F2FBF7] px-4 py-3 text-sm leading-6 text-[#087F67]" role="status">
            <span>错题已保存，可继续载入下一道识别题。</span>{" "}
            <Link className="font-semibold underline underline-offset-2" href={`/questions/${lastSaved.question.id}`}>
              查看已保存错题
            </Link>
            {lastSaved.prepareAi ? <span>；打开详情后可手动开始 AI 分析。</span> : null}
          </div>
        ) : null}

        <div className="mt-6 grid gap-5 sm:grid-cols-2">
          <Field label="考试类型" htmlFor="exam_type" error={errors.exam_type?.message}>
            <select id="exam_type" className="h-11 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 text-sm text-[#0D1B4C] outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15" {...register("exam_type", { required: "请选择考试类型" })}>
              {examTypes.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </Field>
          <Field label="考试模块" htmlFor="module" error={errors.module?.message}>
            <select id="module" className="h-11 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 text-sm text-[#0D1B4C] outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15" {...register("module", { required: "请选择考试模块" })}>
              {examModules.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </Field>
        </div>

        <div className="mt-5">
          <Field label="题干" htmlFor="stem" error={errors.stem?.message}>
            <textarea id="stem" className={fieldClassName()} placeholder="输入完整题干" aria-invalid={Boolean(errors.stem)} aria-describedby={errors.stem ? "stem-error" : undefined} {...register("stem", { required: "请输入题干" })} />
          </Field>
        </div>

        <fieldset className="mt-6">
          <div className="flex items-center justify-between gap-3">
            <legend className="text-sm font-medium text-[#0D1B4C]">选项</legend>
            <Button variant="ghost" size="sm" onClick={() => options.append({ label: nextOptionLabel(getValues("options")), content: "" })}>
              <Plus className="size-4" aria-hidden="true" />
              添加选项
            </Button>
          </div>
          <div className="mt-3 space-y-3">
            {options.fields.map((option, index) => (
              <div key={option.id} className="flex items-center gap-2">
                <Input aria-label={`选项 ${index + 1} 标签`} className="w-16 shrink-0" {...register(`options.${index}.label`)} />
                <Input aria-label={`选项 ${index + 1} 内容`} placeholder="选项内容" {...register(`options.${index}.content`)} />
                <Button variant="ghost" size="icon" aria-label={`删除选项 ${index + 1}`} onClick={() => options.remove(index)} disabled={options.fields.length <= 1}>
                  <Trash2 className="size-4" aria-hidden="true" />
                </Button>
              </div>
            ))}
          </div>
        </fieldset>

        <div className="mt-6 grid gap-5 sm:grid-cols-2">
          <Field label="我的答案" htmlFor="user_answer" error={errors.user_answer?.message}>
            <Input id="user_answer" placeholder="例如：A" aria-invalid={Boolean(errors.user_answer)} aria-describedby={errors.user_answer ? "user_answer-error" : undefined} {...register("user_answer", { required: "请输入我的答案" })} />
          </Field>
          <Field label="正确答案" htmlFor="correct_answer" error={errors.correct_answer?.message}>
            <Input id="correct_answer" placeholder="例如：B" aria-invalid={Boolean(errors.correct_answer)} aria-describedby={errors.correct_answer ? "correct_answer-error" : undefined} {...register("correct_answer", { required: "请输入正确答案" })} />
          </Field>
        </div>

        <div className="mt-5">
          <Field label="原解析" htmlFor="original_explanation">
            <textarea id="original_explanation" className={fieldClassName()} placeholder="可选：记录题目原有解析" {...register("original_explanation")} />
          </Field>
        </div>

        <div className="mt-5 grid gap-5 sm:grid-cols-2">
          <Field label="知识点" htmlFor="knowledge_points_text" hint="多个知识点用顿号或逗号分隔">
            <Input id="knowledge_points_text" placeholder="例如：增长率、比重" {...register("knowledge_points_text")} />
          </Field>
          <Field label="错因" htmlFor="error_reason">
            <select id="error_reason" className="h-11 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 text-sm text-[#0D1B4C] outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15" {...register("error_reason")}>
              <option value="">暂不标记</option>
              {errorReasons.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </Field>
          <Field label="掌握状态" htmlFor="mastery_status">
            <select id="mastery_status" className="h-11 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 text-sm text-[#0D1B4C] outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15" {...register("mastery_status")}>
              {masteryStatuses.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </Field>
          <Field label="来源" htmlFor="source">
            <Input id="source" placeholder="例如：2026 国考真题" {...register("source")} />
          </Field>
        </div>

        <div className="mt-5">
          <Field label="个人笔记" htmlFor="notes">
            <textarea id="notes" className={fieldClassName()} placeholder="记录这道题下次复习时要注意的事项" {...register("notes")} />
          </Field>
        </div>

        {saveQuestion.error ? <p className="mt-5 text-sm text-[#D84755]" role="alert">{apiMessage(saveQuestion.error)}</p> : null}
        <div className="mt-6 flex justify-end border-t border-[#E8ECF4] pt-5">
          <Button type="submit" disabled={saveQuestion.isPending}>
            <Save className="size-4" aria-hidden="true" />
            {saveQuestion.isPending ? "正在保存…" : question ? "保存修改" : "保存错题"}
          </Button>
        </div>
        </fieldset>
      </form>
    </div>
  );
}
