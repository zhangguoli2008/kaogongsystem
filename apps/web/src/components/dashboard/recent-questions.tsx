import { ArrowRight } from "lucide-react";
import Link from "next/link";

import type { MasteryStatus, Question } from "@/types/api";

export const recentQuestionStatusColors: Record<MasteryStatus, { foreground: string; background: string; className: string }> = {
  未掌握: { foreground: "#9F2636", background: "#FFF0F1", className: "bg-[#FFF0F1] text-[#9F2636]" },
  复习中: { foreground: "#8A4B00", background: "#FFF4DE", className: "bg-[#FFF4DE] text-[#8A4B00]" },
  已掌握: { foreground: "#006B50", background: "#E8F8F3", className: "bg-[#E8F8F3] text-[#006B50]" },
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(value));
}

export function RecentQuestions({ questions }: { questions: Question[] }) {
  return (
    <section aria-labelledby="recent-questions-title">
      <div className="flex items-center justify-between gap-4">
        <h2 id="recent-questions-title" className="text-lg font-semibold text-[#0D1B4C]">近期错题回顾</h2>
        <Link href="/questions" className="text-sm font-medium text-[#4F46E5] hover:text-[#4338CA] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">
          查看全部
        </Link>
      </div>
      {questions.length === 0 ? (
        <div className="mt-4 rounded-xl border border-dashed border-[#CBD3E3] bg-white px-5 py-9 text-center">
          <p className="font-medium text-[#0D1B4C]">还没有错题记录</p>
          <p className="mt-2 text-sm text-[#52627F]">先录入一道错题，近期回顾会在这里持续更新。</p>
          <Link href="/questions/new" className="mt-4 inline-flex items-center gap-1 text-sm font-semibold text-[#4F46E5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">
            录入错题 <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </div>
      ) : (
        <div className="mt-4 overflow-hidden rounded-xl border border-[#E4E8F2] bg-white">
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#FAFBFD] text-xs font-medium text-[#52627F]">
                <tr>
                  <th className="px-5 py-3" scope="col">日期</th>
                  <th className="px-5 py-3" scope="col">题目</th>
                  <th className="px-5 py-3" scope="col">模块</th>
                  <th className="px-5 py-3" scope="col">考点</th>
                  <th className="px-5 py-3" scope="col">掌握状态</th>
                  <th className="px-5 py-3" scope="col">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E8ECF4]">
                {questions.map((question) => (
                  <tr key={question.id}>
                    <td className="whitespace-nowrap px-5 py-4 text-[#52627F]">{formatDate(question.created_at)}</td>
                    <td className="max-w-sm px-5 py-4 font-medium text-[#0D1B4C]"><span className="line-clamp-1">{question.stem}</span></td>
                    <td className="whitespace-nowrap px-5 py-4 text-[#314568]">{question.module}</td>
                    <td className="px-5 py-4 text-[#314568]">{question.knowledge_points[0] ?? "待补充"}</td>
                    <td className="whitespace-nowrap px-5 py-4"><span className={`rounded-md px-2 py-1 text-xs font-medium ${recentQuestionStatusColors[question.mastery_status].className}`}>{question.mastery_status}</span></td>
                    <td className="whitespace-nowrap px-5 py-4"><Link href={`/questions/${question.id}`} className="inline-flex items-center gap-1 font-medium text-[#4F46E5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5]">查看详情 <ArrowRight className="size-4" aria-hidden="true" /></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="divide-y divide-[#E8ECF4] md:hidden" aria-label="近期错题">
            {questions.map((question) => (
              <li key={question.id} className="p-4">
                <div className="flex items-center justify-between gap-3"><span className="text-xs text-[#52627F]">{formatDate(question.created_at)} · {question.module}</span><span className={`rounded-md px-2 py-1 text-xs font-medium ${recentQuestionStatusColors[question.mastery_status].className}`}>{question.mastery_status}</span></div>
                <p className="mt-3 line-clamp-2 text-sm font-medium leading-6 text-[#0D1B4C]">{question.stem}</p>
                <Link href={`/questions/${question.id}`} className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-[#4F46E5]">查看详情 <ArrowRight className="size-4" aria-hidden="true" /></Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
