"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { CountByLabel } from "@/types/api";

const chartColors = ["#4F46E5", "#2F80ED", "#10B981", "#F59E0B", "#EF5D68"];

export function ModuleChart({ data, total }: { data: CountByLabel[]; total: number }) {
  const denominator = total || data.reduce((sum, item) => sum + item.count, 0);

  return (
    <section className="rounded-xl border border-[#E4E8F2] bg-white p-5" aria-labelledby="module-chart-title">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="module-chart-title" className="font-semibold text-[#0D1B4C]">五大模块错题占比</h2>
        <p className="text-sm text-[#6A7893]">共 {total} 题</p>
      </div>
      <div className="mt-4 grid gap-5 sm:grid-cols-[minmax(13rem,0.9fr)_minmax(0,1.1fr)] sm:items-center">
        <div className="h-52 min-w-0" aria-hidden="true">
          <ResponsiveContainer width="100%" height="100%" minWidth={208} minHeight={208}>
            <PieChart>
              <Pie data={data} dataKey="count" nameKey="label" innerRadius={52} outerRadius={82} paddingAngle={2} stroke="none">
                {data.map((item, index) => <Cell key={item.label} fill={chartColors[index % chartColors.length]} />)}
              </Pie>
              <Tooltip formatter={(value) => [`${value} 题`, "错题"]} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <ul className="space-y-3" aria-label="模块错题明细">
          {data.map((item, index) => {
            const percent = denominator ? (item.count / denominator) * 100 : 0;
            return (
              <li key={item.label} className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-2 text-sm">
                <span className="size-2.5 rounded-full" style={{ backgroundColor: chartColors[index % chartColors.length] }} aria-hidden="true" />
                <span className="font-medium text-[#314568]">{item.label}</span>
                <span className="text-[#0D1B4C]">{item.count} 题</span>
                <span className="w-12 text-right text-[#6A7893]">{percent.toFixed(1)}%</span>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
