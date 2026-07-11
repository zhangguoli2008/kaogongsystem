import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnalysisPanel } from "./analysis-panel";
import { apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";
import type { Question } from "@/types/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

const failedQuestion = {
  id: "q1",
  user_id: "u1",
  stem: "资料分析题",
  exam_type: "国考",
  module: "资料分析",
  options: [],
  user_answer: "A",
  correct_answer: "B",
  original_explanation: null,
  source: null,
  notes: null,
  image_path: null,
  ocr_raw_text: null,
  knowledge_points: [],
  error_reason: null,
  mastery_status: "未掌握",
  analysis_status: "失败",
  analysis_error_code: "provider_rate_limited",
  tags: [],
  current_analysis_id: null,
  current_analysis: null,
  created_at: "2026-07-10T08:00:00Z",
  updated_at: "2026-07-10T08:00:00Z",
} satisfies Question;

describe("AnalysisPanel", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({
      id: "analysis-1",
      question_id: "q1",
      user_id: "u1",
      cause_analysis: "审题时忽略了增长率的基期。",
      knowledge_points: ["增长率"],
      correct_approach: "先确定比较基期。",
      study_advice: "复习增长率公式。",
      suggested_error_reason: "理解错",
      raw_response: {},
      provider_name: "demo",
      model_name: null,
      is_demo: true,
      created_at: "2026-07-10T08:00:00Z",
    });
  });

  it("shows a stable provider error and retries only on explicit action", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AnalysisPanel question={failedQuestion} />);

    expect(screen.getByText("AI 分析服务请求过于频繁，请稍后再试")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重新分析" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/questions/q1/analyze", {
        method: "POST",
      });
    });
    expect(await screen.findByText("审题时忽略了增长率的基期。")).toBeVisible();
    expect(screen.getByText("演示模式")).toBeVisible();
  });
});
