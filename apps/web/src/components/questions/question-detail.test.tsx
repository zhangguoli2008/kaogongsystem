import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuestionDetail } from "./question-detail";
import { ApiError, apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);

const question = {
  id: "q1",
  user_id: "u1",
  exam_type: "国考",
  module: "资料分析",
  stem: "某地区第二季度生产总值是多少？",
  options: [{ label: "A", content: "120 亿元" }],
  user_answer: "A",
  correct_answer: "B",
  original_explanation: "按增长率公式计算。",
  source: null,
  notes: "先确定基期。",
  image_path: null,
  ocr_raw_text: null,
  knowledge_points: ["增长率"],
  error_reason: "计算错",
  mastery_status: "复习中",
  analysis_status: "未分析",
  tags: [],
  current_analysis_id: null,
  current_analysis: null,
  analysis_error_code: null,
  created_at: "2026-07-10T08:00:00Z",
  updated_at: "2026-07-10T08:00:00Z",
};

describe("QuestionDetail", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("loads and displays real review history newest first", async () => {
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/questions/q1") return question;
      if (path === "/reviews/questions/q1") {
        return [
          {
            id: "r2",
            question_id: "q1",
            user_id: "u1",
            result_status: "已掌握",
            review_note: "第二次复盘",
            reviewed_at: "2026-07-11T08:00:00Z",
          },
          {
            id: "r1",
            question_id: "q1",
            user_id: "u1",
            result_status: "复习中",
            review_note: "第一次复盘",
            reviewed_at: "2026-07-10T08:00:00Z",
          },
        ];
      }
      throw new Error(`unexpected path: ${path}`);
    });

    renderWithProviders(<QuestionDetail id="q1" />);

    expect(await screen.findByText("第二次复盘")).toBeVisible();
    expect(screen.getByText("第一次复盘")).toBeVisible();
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/reviews/questions/q1");
    });
  });

  it("shows a recoverable review-history error", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path) => {
      if (path === "/questions/q1") return question;
      throw new ApiError(503, { code: "service_unavailable", message: "服务暂时不可用" });
    });

    renderWithProviders(<QuestionDetail id="q1" />);

    expect(await screen.findByText("复习记录加载失败，请稍后重试")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重新加载复习记录" }));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.filter(([path]) => path === "/reviews/questions/q1")).toHaveLength(2);
    });
  });
});
