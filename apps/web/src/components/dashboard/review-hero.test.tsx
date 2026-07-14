import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewHero } from "./review-hero";

const question = {
  id: "q1",
  user_id: "u1",
  exam_type: "国考" as const,
  module: "资料分析" as const,
  stem: "某地区工业企业利润同比下降多少？",
  options: [{ label: "A", content: "4.0%" }],
  user_answer: "A",
  correct_answer: "B",
  original_explanation: "按同比增长率计算。",
  source: "2024 年国考",
  notes: null,
  image_path: null,
  ocr_raw_text: null,
  ocr_metadata: null,
  knowledge_points: ["增长率计算"],
  error_reason: "计算错" as const,
  mastery_status: "复习中" as const,
  analysis_status: "已完成" as const,
  tags: [],
  current_analysis_id: null,
  current_analysis: null,
  analysis_error_code: null,
  created_at: "2026-07-10T08:00:00Z",
  updated_at: "2026-07-10T08:00:00Z",
};

describe("ReviewHero", () => {
  it("shows today's review as the dominant dashboard action", () => {
    render(
      <ReviewHero
        data={{
          daily_review_limit: 20,
          pending: [question],
          completed: [],
          completed_count: 12,
          total: 20,
        }}
        currentQuestion={question}
      />,
    );

    expect(screen.getByRole("heading", { name: "今日复习" })).toBeVisible();
    expect(screen.getByText("12 / 20")).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "今日复习进度" })).toHaveAttribute(
      "aria-valuenow",
      "12",
    );
    expect(screen.getByRole("link", { name: "继续复习" })).toHaveAttribute("href", "/review");
    expect(screen.getByText("增长率计算")).toBeVisible();
  });

  it("guides an empty account to capture its first question", () => {
    render(
      <ReviewHero
        data={{
          daily_review_limit: 20,
          pending: [],
          completed: [],
          completed_count: 0,
          total: 0,
        }}
        currentQuestion={null}
      />,
    );

    expect(screen.getByText("录入错题后，系统会生成今日复习计划。")).toBeVisible();
    expect(screen.getByRole("link", { name: "录入第一道错题" })).toHaveAttribute(
      "href",
      "/questions/new",
    );
  });

  it("links to analytics after every scheduled item is complete", () => {
    render(
      <ReviewHero
        data={{
          daily_review_limit: 20,
          pending: [],
          completed: [
            {
              id: "r1",
              question_id: "q1",
              user_id: "u1",
              result_status: "已掌握",
              review_note: null,
              reviewed_at: "2026-07-10T09:00:00Z",
            },
          ],
          completed_count: 1,
          total: 1,
        }}
        currentQuestion={null}
      />,
    );

    expect(screen.getByText("今日计划已完成")).toBeVisible();
    expect(screen.getByRole("link", { name: "查看学习统计" })).toHaveAttribute(
      "href",
      "/analytics",
    );
  });
});
