import type { CountByLabel } from "@/types/api";

interface DistributionListProps {
  title: string;
  data: CountByLabel[];
  emptyText?: string;
}

export function DistributionList({ title, data, emptyText = "暂无分布数据" }: DistributionListProps) {
  const total = data.reduce((sum, item) => sum + item.count, 0);

  return (
    <section className="rounded-xl border border-[#E4E8F2] bg-white p-5" aria-labelledby={`${title}-title`}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 id={`${title}-title`} className="font-semibold text-[#0D1B4C]">{title}</h2>
        <span className="text-sm text-[#52627F]">{total} 题</span>
      </div>
      {data.length ? (
        <ul className="mt-5 space-y-4" aria-label={`${title}明细`}>
          {data.map((item) => {
            const percent = total ? Math.round((item.count / total) * 100) : 0;
            return (
              <li key={item.label}>
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-medium text-[#314568]">{item.label}</span>
                  <span className="text-[#0D1B4C]">{item.count} 题</span><span className="text-[#52627F]">{percent}%</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#EEF0F6]" role="img" aria-label={`${item.label} ${item.count} 题，占 ${percent}%`}>
                  <div className="h-full rounded-full bg-[#4F46E5]" style={{ width: `${percent}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      ) : <p className="mt-5 text-sm text-[#52627F]">{emptyText}</p>}
    </section>
  );
}
