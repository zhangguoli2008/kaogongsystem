import { BrainCircuit, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

interface AiAdviceProps {
  advice: string;
  providerMode: string;
  onRefresh: () => void;
  refreshing?: boolean;
  error?: string | null;
}

export function AiAdvice({ advice, providerMode, onRefresh, refreshing = false, error = null }: AiAdviceProps) {
  const isDemo = providerMode === "demo";

  return (
    <section className="h-full rounded-xl border border-[#D7E2FF] bg-white p-5" aria-labelledby="ai-advice-title">
      <div className="flex items-start gap-4">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-[#EEF0FF] text-[#4F46E5]" aria-hidden="true">
          <BrainCircuit className="size-6" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="ai-advice-title" className="font-semibold text-[#3158D8]">AI 学习建议</h2>
            {isDemo ? <span className="rounded-md bg-[#EEF0FF] px-2 py-0.5 text-xs font-medium text-[#4F46E5]">演示模式</span> : null}
          </div>
          <p className="mt-2 text-sm leading-6 text-[#52627F]">{advice}</p>
          {error ? <p className="mt-3 text-sm text-[#9F2636]" role="alert">{error}</p> : null}
          <Button
            className="mt-3"
            size="sm"
            variant="ghost"
            disabled={refreshing}
            onClick={onRefresh}
            aria-label={error ? "重试刷新建议" : "刷新学习建议"}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
            {refreshing ? "正在刷新" : error ? "重试刷新" : "刷新建议"}
          </Button>
        </div>
      </div>
    </section>
  );
}
