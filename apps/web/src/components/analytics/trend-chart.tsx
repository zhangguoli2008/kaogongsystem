"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { TrendPoint } from "@/types/api";

export function TrendChart({ trend7d, trend30d }: { trend7d: TrendPoint[]; trend30d: TrendPoint[] }) {
  const [days, setDays] = useState<7 | 30>(7);
  const data = days === 7 ? trend7d : trend30d;
  const total = data.reduce((sum, item) => sum + item.count, 0);

  return (
    <section className="rounded-xl border border-[#E4E8F2] bg-white p-5" aria-labelledby="trend-chart-title">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><h2 id="trend-chart-title" className="font-semibold text-[#0D1B4C]">错题录入趋势</h2><p className="mt-1 text-sm text-[#6A7893]">当前周期共录入 {total} 题</p></div>
        <div className="flex rounded-lg border border-[#E4E8F2] bg-[#F7F8FC] p-1" role="group" aria-label="趋势周期">
          {([7, 30] as const).map((value) => <button key={value} type="button" aria-pressed={days === value} onClick={() => setDays(value)} className={`h-8 rounded-md px-3 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#4F46E5] ${days === value ? "bg-white text-[#4F46E5] shadow-sm" : "text-[#6A7893]"}`}>最近 {value} 天</button>)}
        </div>
      </div>
      <div className="mt-5 h-64 min-w-0" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%" minWidth={260} minHeight={256}>
          <LineChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="#E8ECF4" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tickFormatter={(value: string) => value.slice(5)} tick={{ fill: "#6A7893", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={20} />
            <YAxis allowDecimals={false} tick={{ fill: "#6A7893", fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip formatter={(value) => [`${value} 题`, "录入"]} labelFormatter={(label) => String(label)} />
            <Line type="monotone" dataKey="count" stroke="#4F46E5" strokeWidth={2.5} dot={{ fill: "#4F46E5", r: 3 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-4 max-h-44 overflow-auto rounded-lg border border-[#E8ECF4]">
        <table className="w-full text-left text-xs" aria-label={`最近 ${days} 天录入明细`}>
          <thead className="sticky top-0 bg-[#FAFBFD] text-[#6A7893]"><tr><th className="px-3 py-2" scope="col">日期</th><th className="px-3 py-2 text-right" scope="col">录入题数</th></tr></thead>
          <tbody className="divide-y divide-[#E8ECF4]">{data.map((item) => <tr key={item.date}><td className="px-3 py-2 text-[#52627F]">{item.date}</td><td className="px-3 py-2 text-right font-medium text-[#0D1B4C]">{item.count}</td></tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}
