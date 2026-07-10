import { RoutePlaceholder } from "@/components/layout/route-placeholder";

export default function DashboardPage() {
  return (
    <RoutePlaceholder
      title="今日学习概览"
      description="完成认证后，今日复习、学习建议与近期错题将在这里汇总呈现。"
      action={{ href: "/questions/new", label: "录入错题" }}
    />
  );
}
