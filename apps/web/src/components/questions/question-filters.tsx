"use client";

import { FilterX } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { errorReasons, examModules, masteryStatuses, analysisStatuses } from "@/types/api";

function selectClassName() {
  return "h-10 w-full rounded-lg border border-[#E4E8F2] bg-white px-3 text-sm text-[#314568] outline-none focus:border-[#4F46E5] focus:ring-2 focus:ring-[#4F46E5]/15";
}

export function QuestionFilters() {
  const pathname = usePathname() || "/questions";
  const router = useRouter();
  const searchParams = useSearchParams();

  function updateParam(name: string, value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(name, value);
    } else {
      params.delete(name);
    }
    params.delete("page");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  }

  return (
    <section className="rounded-xl border border-[#E4E8F2] bg-white p-4 sm:p-5" aria-labelledby="question-filter-title">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 id="question-filter-title" className="text-base font-semibold text-[#0D1B4C]">筛选错题</h2>
          <p className="mt-1 text-sm text-[#6A7893]">筛选条件会保留在当前链接中。</p>
        </div>
        {searchParams.size ? (
          <Button variant="ghost" size="sm" onClick={() => router.replace(pathname)}>
            <FilterX className="size-4" aria-hidden="true" />
            清除筛选
          </Button>
        ) : null}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <label className="space-y-1.5 text-sm font-medium text-[#314568]">
          <span>考试模块</span>
          <select className={selectClassName()} value={searchParams.get("module") ?? ""} onChange={(event) => updateParam("module", event.target.value)}>
            <option value="">全部模块</option>
            {examModules.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="space-y-1.5 text-sm font-medium text-[#314568]">
          <span>知识点</span>
          <input className={selectClassName()} value={searchParams.get("knowledge_point") ?? ""} placeholder="例如：增长率" onChange={(event) => updateParam("knowledge_point", event.target.value)} />
        </label>
        <label className="space-y-1.5 text-sm font-medium text-[#314568]">
          <span>错因</span>
          <select className={selectClassName()} value={searchParams.get("error_reason") ?? ""} onChange={(event) => updateParam("error_reason", event.target.value)}>
            <option value="">全部错因</option>
            {errorReasons.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="space-y-1.5 text-sm font-medium text-[#314568]">
          <span>掌握状态</span>
          <select className={selectClassName()} value={searchParams.get("mastery_status") ?? ""} onChange={(event) => updateParam("mastery_status", event.target.value)}>
            <option value="">全部状态</option>
            {masteryStatuses.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="space-y-1.5 text-sm font-medium text-[#314568]">
          <span>AI 状态</span>
          <select className={selectClassName()} value={searchParams.get("analysis_status") ?? ""} onChange={(event) => updateParam("analysis_status", event.target.value)}>
            <option value="">全部 AI 状态</option>
            {analysisStatuses.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="space-y-1.5 text-sm font-medium text-[#314568]">
          <span>录入开始日期</span>
          <input className={selectClassName()} type="date" value={searchParams.get("created_from") ?? ""} onChange={(event) => updateParam("created_from", event.target.value)} />
        </label>
        <label className="space-y-1.5 text-sm font-medium text-[#314568]">
          <span>录入结束日期</span>
          <input className={selectClassName()} type="date" value={searchParams.get("created_to") ?? ""} onChange={(event) => updateParam("created_to", event.target.value)} />
        </label>
      </div>
    </section>
  );
}
