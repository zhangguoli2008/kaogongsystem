import { RoutePlaceholder } from "@/components/layout/route-placeholder";

export default function ReviewPage() {
  return (
    <RoutePlaceholder
      title="今日复习"
      description="准备好后，你可以按照每日计划依次复习已保存的错题。"
      action={{ href: "/questions", label: "查看错题库" }}
    />
  );
}
