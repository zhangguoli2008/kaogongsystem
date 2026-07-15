"use client";

import { useEffect, useRef, useState } from "react";
import { Camera, FileImage, ScanLine, Upload as UploadIcon } from "lucide-react";
import Image from "next/image";

import { OcrQuestionCard, type OcrLoadIntent } from "@/components/questions/ocr-question-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api";
import type { OcrQuestion, OcrResult, OcrStatus, Upload } from "@/types/api";

interface ImageOcrPanelProps {
  draftActionsDisabled?: boolean;
  onLoadQuestion: (
    question: OcrQuestion,
    result: OcrResult,
    intent: OcrLoadIntent,
    removeAfterSave: () => void,
  ) => void;
  onAdoptAnswer: (
    question: OcrQuestion,
    result: OcrResult,
    removeAfterSave: () => void,
  ) => void;
  onAdoptParse: (
    question: OcrQuestion,
    result: OcrResult,
    removeAfterSave: () => void,
  ) => void;
}

const supportedMimeTypes = new Set([
  "image/jpeg",
  "image/png",
  "image/bmp",
  "image/x-ms-bmp",
  "application/pdf",
]);
const supportedExtensions = new Set(["jpg", "jpeg", "png", "bmp", "pdf"]);
const maxBase64Bytes = 10 * 1024 * 1024;

function messageFor(error: unknown) {
  return error instanceof ApiError ? error.body.message : "文件处理失败，请检查网络后重试";
}

function isSupportedFile(file: File) {
  const extension = file.name.split(".").pop()?.toLowerCase();
  return supportedMimeTypes.has(file.type.toLowerCase()) || Boolean(extension && supportedExtensions.has(extension));
}

function cloneQuestion(question: OcrQuestion): OcrQuestion {
  return {
    ...question,
    question_elements: question.question_elements.map((item) => ({ ...item })),
    options: question.options.map((option) => ({ ...option })),
    figures: question.figures.map((item) => ({ ...item })),
    tables: question.tables.map((item) => ({ ...item })),
    coord: [...question.coord],
    warnings: [...question.warnings],
  };
}

export function ImageOcrPanel({
  draftActionsDisabled = false,
  onLoadQuestion,
  onAdoptAnswer,
  onAdoptParse,
}: ImageOcrPanelProps) {
  const [status, setStatus] = useState<OcrStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [pdfPageNumber, setPdfPageNumber] = useState(1);
  const [uploading, setUploading] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OcrResult | null>(null);
  const [drafts, setDrafts] = useState<OcrQuestion[]>([]);
  const [draftsDirty, setDraftsDirty] = useState(false);
  const currentRequestId = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    apiFetch<OcrStatus>("/ocr/status")
      .then((nextStatus) => {
        if (active) setStatus(nextStatus);
      })
      .catch((nextError) => {
        if (active) setStatusError(messageFor(nextError));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  function selectFile(nextFile: File | null) {
    setError(null);
    if (!nextFile) return;

    if (!isSupportedFile(nextFile)) {
      setError("仅支持 JPEG、PNG、BMP 图片或 PDF 文件");
      return;
    }
    if (4 * Math.ceil(nextFile.size / 3) > maxBase64Bytes) {
      setError("文件经 Base64 编码后不能超过 10 MiB（原文件最大 7.5 MiB）");
      return;
    }

    if (draftsDirty && !window.confirm("选择新文件会丢弃当前已编辑的识别草稿，确定继续吗？")) return;
    setFile(nextFile);
    setPreviewUrl(URL.createObjectURL(nextFile));
    setUpload(null);
    setPdfPageNumber(1);
    setResult(null);
    currentRequestId.current = null;
    setDrafts([]);
    setDraftsDirty(false);
  }

  async function uploadFile() {
    if (!file) {
      setError("请先选择错题图片或 PDF 文件");
      return;
    }

    setUploading(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const nextUpload = await apiFetch<Upload>("/uploads/questions", { method: "POST", body });
      setUpload(nextUpload);
      setPdfPageNumber(1);
    } catch (nextError) {
      setError(messageFor(nextError));
    } finally {
      setUploading(false);
    }
  }

  async function recognizeFile() {
    if (!upload || !status?.configured) return;
    if (draftsDirty && !window.confirm("重新识别会覆盖当前已编辑的识别草稿，确定继续吗？")) return;

    setRecognizing(true);
    setError(null);
    try {
      const nextResult = await apiFetch<OcrResult>("/ocr", {
        method: "POST",
        body: JSON.stringify({ upload_id: upload.id, pdf_page_number: pdfPageNumber }),
      });
      setResult(nextResult);
      currentRequestId.current = nextResult.request_id;
      setDrafts(nextResult.questions.map(cloneQuestion));
      setDraftsDirty(false);
    } catch (nextError) {
      setError(messageFor(nextError));
    } finally {
      setRecognizing(false);
    }
  }

  function updateDraft(index: number, question: OcrQuestion) {
    setDrafts((current) => current.map((candidate, candidateIndex) => candidateIndex === index ? question : candidate));
    setDraftsDirty(true);
  }

  function deleteDraft(index: number) {
    setDrafts((current) => current.filter((_, candidateIndex) => candidateIndex !== index));
    setDraftsDirty(true);
  }

  function removeDraftAfterSave(temporaryId: string, requestId: string) {
    if (currentRequestId.current !== requestId) return;
    setDrafts((current) => current.filter(
      (question) => question.temporary_id !== temporaryId,
    ));
  }

  const isPdf = file?.type === "application/pdf" || file?.name.toLowerCase().endsWith(".pdf");
  const invalidPdfPage = Boolean(upload?.file_kind === "pdf" && (
    pdfPageNumber < 1 || (upload.page_count !== null && pdfPageNumber > upload.page_count)
  ));

  return (
    <section className="rounded-xl border border-[#E4E8F2] bg-white p-5 sm:p-6" aria-labelledby="ocr-panel-title">
      <fieldset className="contents" disabled={draftActionsDisabled}>
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true">
          <FileImage className="size-5" />
        </span>
        <div>
          <h2 id="ocr-panel-title" className="text-base font-semibold text-[#0D1B4C]">多题图片识别</h2>
          <p className="mt-1 text-sm leading-6 text-[#6A7893]">支持一张图中的多道题。识别后先编辑草稿，再选择一道载入表单。</p>
        </div>
      </div>

      <div className="mt-4">
        {!status && !statusError ? <p className="text-xs text-[#6A7893]" role="status">正在检查 OCR 服务…</p> : null}
        {status?.configured ? (
          <p className="text-xs font-medium text-[#087F67]">
            {status.provider === "mock" ? "演示 OCR（不会调用腾讯云）" : "腾讯云真实 OCR"}
          </p>
        ) : null}
        {status && !status.configured ? (
          <p className="rounded-lg border border-[#FFD7DB] bg-[#FFF7F8] px-3 py-2 text-sm text-[#C33746]" role="alert">OCR 服务尚未配置。请先在服务端配置腾讯云凭证，页面其他功能仍可正常使用。</p>
        ) : null}
        {statusError ? <p className="rounded-lg border border-[#FFD7DB] bg-[#FFF7F8] px-3 py-2 text-sm text-[#C33746]" role="alert">OCR 状态检查失败：{statusError}</p> : null}
      </div>

      <div className="mt-5 space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-[#DDE3F0] bg-white px-3 text-sm font-medium text-[#0D1B4C] hover:bg-[#F7F8FC]">
            <UploadIcon className="size-4" aria-hidden="true" />
            从相册或文件选择
            <input
              type="file"
              accept="image/jpeg,image/png,image/bmp,.bmp,application/pdf"
              aria-label="从相册或文件选择错题"
              className="sr-only"
              disabled={uploading || recognizing}
              onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <label className="flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-[#DDE3F0] bg-white px-3 text-sm font-medium text-[#0D1B4C] hover:bg-[#F7F8FC]">
            <Camera className="size-4" aria-hidden="true" />
            拍照录入
            <input
              type="file"
              accept="image/jpeg,image/png,image/bmp,.bmp"
              capture="environment"
              aria-label="拍摄错题"
              className="sr-only"
              disabled={uploading || recognizing}
              onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
            />
          </label>
        </div>
        <p className="text-xs leading-5 text-[#6A7893]">支持 JPEG、PNG、BMP、PDF；Base64 编码后不超过 10 MiB（原文件最大 7.5 MiB）；PDF 每次识别一页。</p>

        {previewUrl && isPdf ? (
          <object data={previewUrl} type="application/pdf" aria-label="待识别 PDF 预览" className="h-80 w-full rounded-lg border border-[#E4E8F2] bg-[#F7F8FC]">
            <a href={previewUrl}>打开待识别 PDF</a>
          </object>
        ) : previewUrl ? (
          <div className="overflow-hidden rounded-lg border border-[#E4E8F2] bg-[#F7F8FC]">
            <Image src={previewUrl} alt="待识别错题预览" width={1200} height={800} unoptimized className="max-h-80 w-full object-contain" />
          </div>
        ) : (
          <div className="grid min-h-44 place-items-center rounded-lg border border-dashed border-[#CBD4E6] bg-[#F7F8FC] px-5 text-center text-sm text-[#6A7893]">
            选择图片、拍照或选择 PDF 后将在这里预览
          </div>
        )}

        {upload?.warnings.length ? (
          <ul className="rounded-lg border border-[#F5D797] bg-[#FFF9E9] px-3 py-2 text-xs leading-5 text-[#7A5A12]" aria-label="文件处理提醒">
            {upload.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        ) : null}

        {upload?.file_kind === "pdf" ? (
          <div className="max-w-48">
            <label htmlFor="pdf-page-number" className="text-sm font-medium text-[#0D1B4C]">PDF 页码</label>
            <Input
              id="pdf-page-number"
              className="mt-2"
              type="number"
              min={1}
              max={upload.page_count ?? undefined}
              value={pdfPageNumber}
              aria-invalid={invalidPdfPage}
              onChange={(event) => setPdfPageNumber(Number(event.target.value))}
            />
            <p className="mt-1 text-xs text-[#6A7893]">共 {upload.page_count ?? "未知"} 页</p>
          </div>
        ) : null}

        {error ? <p className="text-sm text-[#D84755]" role="alert">{error}</p> : null}

        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={uploadFile} disabled={!file || uploading || recognizing}>
            <UploadIcon className="size-4" aria-hidden="true" />
            {uploading ? "正在上传…" : upload ? "重新上传文件" : "上传文件"}
          </Button>
          <Button onClick={recognizeFile} disabled={!upload || recognizing || uploading || !status?.configured || invalidPdfPage}>
            <ScanLine className="size-4" aria-hidden="true" />
            {recognizing ? "正在识别…" : result ? "重新识别" : "开始识别"}
          </Button>
        </div>

        {result ? (
          <div className="space-y-4 border-t border-[#E8ECF4] pt-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-semibold text-[#0D1B4C]">识别到 {drafts.length} 道题</h3>
              {result.is_demo ? <span className="rounded-md bg-[#EEF0FF] px-2 py-1 text-xs font-medium text-[#4F46E5]">演示模式识别结果</span> : null}
            </div>
            {result.warnings.length ? (
              <ul className="rounded-lg border border-[#F5D797] bg-[#FFF9E9] px-3 py-2 text-xs leading-5 text-[#7A5A12]" aria-label="本页识别提醒">
                {result.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            ) : null}
            {drafts.length ? drafts.map((question, index) => {
              const removeAfterSave = () => removeDraftAfterSave(
                question.temporary_id,
                result.request_id,
              );
              return (
                <OcrQuestionCard
                  key={question.temporary_id}
                  position={index}
                  question={question}
                  sourceImageUrl={result.source.image_url}
                  draftActionsDisabled={draftActionsDisabled}
                  onChange={(nextQuestion) => updateDraft(index, nextQuestion)}
                  onDelete={() => deleteDraft(index)}
                  onLoad={(intent: OcrLoadIntent) => onLoadQuestion(
                    question,
                    result,
                    intent,
                    removeAfterSave,
                  )}
                  onAdoptAnswer={() => onAdoptAnswer(question, result, removeAfterSave)}
                  onAdoptParse={() => onAdoptParse(question, result, removeAfterSave)}
                />
              );
            }) : <p className="rounded-lg border border-dashed border-[#CBD4E6] px-4 py-6 text-center text-sm text-[#6A7893]">没有待处理的识别草稿，可重新识别恢复。</p>}
          </div>
        ) : null}
      </div>
      </fieldset>
    </section>
  );
}
