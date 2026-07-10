import { RoutePlaceholder } from "@/components/layout/route-placeholder";

export default function QuestionsPage() {
  return (
    <RoutePlaceholder
      title="错题库"
      description="你可以在这里查找、筛选和管理已经保存的错题。"
      action={{ href: "/questions/new", label: "录入错题" }}
    />
  );
}
