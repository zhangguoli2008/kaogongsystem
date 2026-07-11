"use client";

import { useState } from "react";
import { ArrowLeft, FilePenLine, ImageUp } from "lucide-react";
import Link from "next/link";

import { QuestionForm } from "@/components/questions/question-form";

export default function NewQuestionPage() {
  const [mode, setMode] = useState<"image" | "manual">("image");

  return (
    <div className="space-y-6">
      <div>
        <Link href="/questions" className="inline-flex items-center gap-1 text-sm font-medium text-[#4F46E5] hover:text-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]"><ArrowLeft className="size-4" aria-hidden="true" />返回错题库</Link>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight text-[#0D1B4C] sm:text-3xl">录入错题</h1>
        <p className="mt-2 text-sm leading-6 text-[#6A7893]">从图片识别或手动录入开始。保存后再决定是否进行 AI 诊断。</p>
      </div>
      <div className="inline-flex rounded-lg border border-[#E4E8F2] bg-white p-1" role="tablist" aria-label="录入方式">
        <button type="button" role="tab" aria-selected={mode === "image"} className={`inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium ${mode === "image" ? "bg-[#4F46E5] text-white" : "text-[#52627F] hover:bg-[#F1F3F9]"}`} onClick={() => setMode("image")}><ImageUp className="size-4" aria-hidden="true" />图片识别</button>
        <button type="button" role="tab" aria-selected={mode === "manual"} className={`inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium ${mode === "manual" ? "bg-[#4F46E5] text-white" : "text-[#52627F] hover:bg-[#F1F3F9]"}`} onClick={() => setMode("manual")}><FilePenLine className="size-4" aria-hidden="true" />手动录入</button>
      </div>
      <QuestionForm mode={mode} />
    </div>
  );
}
