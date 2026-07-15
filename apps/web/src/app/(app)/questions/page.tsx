import { Suspense } from "react";

import { QuestionLibrary } from "@/components/questions/question-library";

export default function QuestionsPage() {
  return (
    <Suspense fallback={<div className="rounded-xl border border-[#E4E8F2] bg-white px-6 py-14 text-center text-sm text-[#6A7893]" role="status">正在加载错题库…</div>}>
      <QuestionLibrary />
    </Suspense>
  );
}
