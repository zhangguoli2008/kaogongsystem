import { QuestionDetail } from "@/components/questions/question-detail";

export default async function QuestionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <QuestionDetail id={id} />;
}
