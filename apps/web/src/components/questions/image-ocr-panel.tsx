"use client";

import { useEffect, useState } from "react";
import { FileImage, ScanLine, Upload as UploadIcon } from "lucide-react";
import Image from "next/image";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api";
import type { OcrResult, Upload } from "@/types/api";

interface ImageOcrPanelProps {
  onRecognized: (result: OcrResult, upload: Upload) => void;
}

function messageFor(error: unknown) {
  return error instanceof ApiError ? error.body.message : "图片处理失败，请检查网络后重试";
}

export function ImageOcrPanel({ onRecognized }: ImageOcrPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDemo, setIsDemo] = useState(false);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  function selectFile(nextFile: File | null) {
    setError(null);
    setUpload(null);
    setIsDemo(false);
    setFile(null);
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }

    if (!nextFile) {
      return;
    }
    if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(nextFile.type)) {
      setError("仅支持 JPEG、PNG 或 WebP 图片");
      return;
    }
    if (nextFile.size > 10 * 1024 * 1024) {
      setError("图片大小不能超过 10MB");
      return;
    }

    setFile(nextFile);
    setPreviewUrl(URL.createObjectURL(nextFile));
  }

  async function uploadImage() {
    if (!file) {
      setError("请先选择一张错题图片");
      return;
    }

    setUploading(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      setUpload(await apiFetch<Upload>("/uploads/questions", { method: "POST", body }));
    } catch (nextError) {
      setError(messageFor(nextError));
    } finally {
      setUploading(false);
    }
  }

  async function recognizeImage() {
    if (!upload) {
      return;
    }

    setRecognizing(true);
    setError(null);
    try {
      const result = await apiFetch<OcrResult>("/ocr", {
        method: "POST",
        body: JSON.stringify({ upload_id: upload.id }),
      });
      setIsDemo(result.is_demo);
      onRecognized(result, upload);
    } catch (nextError) {
      setError(messageFor(nextError));
    } finally {
      setRecognizing(false);
    }
  }

  return (
    <section className="rounded-xl border border-[#E4E8F2] bg-white p-5 sm:p-6" aria-labelledby="ocr-panel-title">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true">
          <FileImage className="size-5" />
        </span>
        <div>
          <h2 id="ocr-panel-title" className="text-base font-semibold text-[#0D1B4C]">图片识别</h2>
          <p className="mt-1 text-sm leading-6 text-[#6A7893]">上传后请确认预览，再手动开始识别。识别结果可继续修改。</p>
        </div>
      </div>

      <div className="mt-5 space-y-4">
        <div>
          <label className="sr-only" htmlFor="question-image">上传错题图片</label>
          <Input
            id="question-image"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            aria-label="上传错题图片"
            onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
          />
          <p className="mt-2 text-xs leading-5 text-[#6A7893]">支持 JPEG、PNG、WebP，单张不超过 10MB。</p>
        </div>

        {previewUrl ? (
          <div className="overflow-hidden rounded-lg border border-[#E4E8F2] bg-[#F7F8FC]">
            <Image src={previewUrl} alt="待识别错题预览" width={1200} height={800} unoptimized className="max-h-80 w-full object-contain" />
          </div>
        ) : (
          <div className="grid min-h-44 place-items-center rounded-lg border border-dashed border-[#CBD4E6] bg-[#F7F8FC] px-5 text-center text-sm text-[#6A7893]">
            选择图片后将在这里预览
          </div>
        )}

        {error ? <p className="text-sm text-[#D84755]" role="alert">{error}</p> : null}
        {isDemo ? <p className="inline-flex rounded-md bg-[#EEF0FF] px-2 py-1 text-xs font-medium text-[#4F46E5]">演示模式识别结果</p> : null}

        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={uploadImage} disabled={!file || uploading}>
            <UploadIcon className="size-4" aria-hidden="true" />
            {uploading ? "正在上传…" : upload ? "重新上传图片" : "上传图片"}
          </Button>
          <Button onClick={recognizeImage} disabled={!upload || recognizing}>
            <ScanLine className="size-4" aria-hidden="true" />
            {recognizing ? "正在识别…" : "开始识别"}
          </Button>
        </div>
      </div>
    </section>
  );
}
