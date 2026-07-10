import { RoutePlaceholder } from "@/components/layout/route-placeholder";

export default function NewQuestionPage() {
  return (
    <RoutePlaceholder
      title="录入错题"
      description="从图片识别或手动记录开始，逐步建立自己的错题档案。"
      action={{ href: "/questions", label: "返回错题库" }}
    />
  );
}
