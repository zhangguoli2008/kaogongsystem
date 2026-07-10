import { RoutePlaceholder } from "@/components/layout/route-placeholder";

export default function AnalyticsPage() {
  return (
    <RoutePlaceholder
      title="数据统计"
      description="知识模块与复习趋势会在这里以可读的数据方式呈现。"
      action={{ href: "/questions", label: "查看错题库" }}
    />
  );
}
