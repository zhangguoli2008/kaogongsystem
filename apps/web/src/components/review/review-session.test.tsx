import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReviewSession } from "./review-session";
import { renderWithProviders } from "@/test/test-utils";
import type { ReviewRecord, TodayReviewResponse } from "@/types/api";

const questions = [
  {
    id: "q1",
    user_id: "u1",
    exam_type: "国考" as const,
    module: "资料分析" as const,
    stem: "第一题题干",
    options: [{ label: "A", content: "选项 A" }],
    user_answer: "A",
    correct_answer: "B",
    original_explanation: "第一题解析",
    source: null,
    notes: null,
    image_path: null,
    ocr_raw_text: null,
    knowledge_points: ["增长率"],
    error_reason: "计算错" as const,
    mastery_status: "未掌握" as const,
    analysis_status: "已完成" as const,
    tags: [],
    current_analysis_id: null,
    current_analysis: {
      id: "a1",
      question_id: "q1",
      user_id: "u1",
      cause_analysis: "没有识别基期",
      knowledge_points: ["增长率"],
      correct_approach: "先确认基期",
      study_advice: "再练两题",
      suggested_error_reason: "计算错" as const,
      raw_response: {},
      provider_name: "demo",
      model_name: null,
      is_demo: true,
      created_at: "2026-07-10T08:00:00Z",
    },
    analysis_error_code: null,
    created_at: "2026-07-10T08:00:00Z",
    updated_at: "2026-07-10T08:00:00Z",
  },
  {
    id: "q2",
    user_id: "u1",
    exam_type: "国考" as const,
    module: "判断推理" as const,
    stem: "第二题题干",
    options: [],
    user_answer: "C",
    correct_answer: "D",
    original_explanation: "第二题解析",
    source: null,
    notes: null,
    image_path: null,
    ocr_raw_text: null,
    knowledge_points: ["定义判断"],
    error_reason: "理解错" as const,
    mastery_status: "复习中" as const,
    analysis_status: "未分析" as const,
    tags: [],
    current_analysis_id: null,
    current_analysis: null,
    analysis_error_code: null,
    created_at: "2026-07-09T08:00:00Z",
    updated_at: "2026-07-09T08:00:00Z",
  },
] satisfies TodayReviewResponse["pending"];

const todayReview: TodayReviewResponse = {
  daily_review_limit: 20,
  pending: questions,
  completed: [],
  completed_count: 0,
  total: 2,
};

describe("ReviewSession", () => {
  it("hides the answer until the learner explicitly reveals it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ReviewSession data={todayReview} submitReview={vi.fn()} />);

    expect(screen.queryByText("第一题解析")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "已掌握" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看答案与解析" }));

    expect(screen.getByText("第一题解析")).toBeVisible();
    expect(screen.getByRole("button", { name: "已掌握" })).toBeVisible();
  });

  it("submits mastery and advances without repeating the completed question", async () => {
    const user = userEvent.setup();
    const submitReview = vi.fn(async (questionId: string, payload: { result_status: string; review_note?: string | null }) => ({
      id: "r1",
      question_id: questionId,
      user_id: "u1",
      result_status: payload.result_status,
      review_note: payload.review_note ?? null,
      reviewed_at: "2026-07-10T09:00:00Z",
    } as ReviewRecord));
    renderWithProviders(<ReviewSession data={todayReview} submitReview={submitReview} />);

    await user.click(screen.getByRole("button", { name: "查看答案与解析" }));
    await user.type(screen.getByLabelText("本次复习笔记"), "记住先找基期");
    await user.click(screen.getByRole("button", { name: "复习中" }));

    expect(submitReview).toHaveBeenCalledWith("q1", {
      result_status: "复习中",
      review_note: "记住先找基期",
    });
    expect(await screen.findByText("第二题题干")).toBeVisible();
    expect(screen.queryByText("第一题题干")).not.toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeVisible();
  });
});
