import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "./page";
import { apiFetch } from "@/lib/api";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);
const emptyReview = {
  daily_review_limit: 20,
  pending: [],
  completed: [],
  completed_count: 0,
  total: 0,
};

describe("ReviewPage", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it.each([10, 30] as const)("refreshes the complete plan after changing the daily limit to %s", async (newLimit) => {
    const user = userEvent.setup();
    let todayCalls = 0;
    apiFetchMock.mockImplementation(async (path, init) => {
      if (path === "/reviews/today") {
        todayCalls += 1;
        return todayCalls === 1 ? emptyReview : reviewWithQuestion(newLimit);
      }
      if (path === "/reviews/settings" && init?.method === "PATCH") {
        return { daily_review_limit: newLimit };
      }
      throw new Error(`unexpected request: ${path}`);
    });

    renderWithProviders(<ReviewPage />);

    const limit = await screen.findByRole("combobox", { name: "每日复习数量" });
    expect(limit).toHaveValue("20");
    expect(screen.getByText("保存后会按新数量重新生成当前计划。")).toBeVisible();
    await user.selectOptions(limit, String(newLimit));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/reviews/settings", {
        method: "PATCH",
        body: JSON.stringify({ daily_review_limit: newLimit }),
      });
    });
    expect(await screen.findByText(`刷新后的 ${newLimit} 题计划`)).toBeVisible();
    expect(screen.getByText("0 / 1")).toBeVisible();
    expect(apiFetchMock.mock.calls.filter(([path]) => path === "/reviews/today")).toHaveLength(2);
    expect(screen.getByText("每日数量已更新")).toBeVisible();
  });
});

function reviewWithQuestion(limit: 10 | 30) {
  return {
    daily_review_limit: limit,
    pending: [{
      id: `q-${limit}`,
      user_id: "u1",
      exam_type: "国考",
      module: "资料分析",
      stem: `刷新后的 ${limit} 题计划`,
      options: [],
      user_answer: "A",
      correct_answer: "B",
      original_explanation: "解析",
      source: null,
      notes: null,
      image_path: null,
      ocr_raw_text: null,
      knowledge_points: ["增长率"],
      error_reason: "计算错",
      mastery_status: "未掌握",
      analysis_status: "未分析",
      tags: [],
      current_analysis_id: null,
      current_analysis: null,
      analysis_error_code: null,
      created_at: "2026-07-10T08:00:00Z",
      updated_at: "2026-07-10T08:00:00Z",
    }],
    completed: [],
    completed_count: 0,
    total: 1,
  };
}
